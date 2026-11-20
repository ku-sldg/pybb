"""Two-run ledger attestation over real CVM packages (tests/fixtures/ledger,
captured from the 2026-11-17 spike) served by a canned client — no CVM."""

import base64
import gzip
import json
from pathlib import Path

import pytest

from pybb.attestation import (
    AttestationClient,
    FileLedger,
    ProtocolDir,
    make_attestation_predicate,
)
from pybb.attestation.ledger import (
    APPRAISER_NONCE_TARGID,
    DuplicateNonceError,
    EvidenceLayoutError,
    LedgerConfig,
    describe_package,
    sha256_hex,
)
from pybb.attestation.ledger_runs import (
    appraisal_branch,
    appraisal_term,
    attest,
    ledger_protocol,
    measurement_term,
)

FIXTURES = Path(__file__).parent / "fixtures"
L1A = FIXTURES / "temp_control_aadl_slang_l1a"
RAW = json.loads((FIXTURES / "ledger/l1a_measurement.response.json").read_text())
APPR = json.loads((FIXTURES / "ledger/l1a_appraisal.response.json").read_text())


def _has_appr(term) -> bool:
    if not isinstance(term, dict):
        return False
    body = term.get("TERM_BODY")
    if term.get("TERM_CONSTRUCTOR") == "asp":
        return isinstance(body, dict) and body.get("ASP_CONSTRUCTOR") == "APPR"
    return any(_has_appr(x) for x in (body if isinstance(body, list) else []))


class CannedClient(AttestationClient):
    """Serves the spike's real packages: the measurement request gets the raw
    package, the appraisal request (its term contains APPR) gets the signed
    appraisal package. Records every request for assertions."""

    def __init__(self, raw=RAW, appr=APPR, fail_on=None):
        self.raw, self.appr, self.fail_on = raw, appr, fail_on
        self.requests = []

    def run_protocol(self, protocol: ProtocolDir) -> dict:
        req = protocol.prebuilt_request
        assert req is not None, "ledger runs always use prebuilt requests"
        self.requests.append(req)
        kind = "appraisal" if _has_appr(req["TERM"]) else "measurement"
        if self.fail_on == kind:
            return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": False, "PAYLOAD": "boom"}
        return self.raw if kind == "measurement" else self.appr


@pytest.fixture
def proto() -> ProtocolDir:
    return ProtocolDir.load(str(L1A))


@pytest.fixture
def config(tmp_path) -> LedgerConfig:
    return LedgerConfig(state_dir=str(tmp_path / "state"), appraiser_id="ap-test", evidence_repo="",
                        verify_key_path=str(tmp_path / "no-such-key.pem"))


# ── terms and sessions ───────────────────────────────────────────────────────


def test_measurement_term_puts_one_nonce_in_a_left_path_split(proto):
    t = measurement_term(proto)
    assert t["TERM_CONSTRUCTOR"] == "lseq"
    split, sig = t["TERM_BODY"]
    assert sig == {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}
    assert split["TERM_CONSTRUCTOR"] == "bseq" and split["TERM_BODY"][0] == "left_path"
    nonce = split["TERM_BODY"][1]["TERM_BODY"]["ASP_BODY"]
    assert nonce == {"ASP_ID": "generate_nonce", "ASP_ARGS": {"asp_targid": "nonce_targ", "bytes": 32}}
    assert not _has_appr(t), "the measurement run never appraises"
    assert _has_appr(appraisal_term())


def test_ledger_protocol_adds_asps_without_touching_disk(proto):
    lp = ledger_protocol(proto)
    types = lp.session["Session_Context"]["ASP_Types"]
    comps = lp.session["Session_Context"]["ASP_Comps"]
    assert types["generate_nonce"]["FWD"]["FWD"] == "EXTEND"
    assert types["hashevidence"]["FWD"]["FWD"] == "REPLACE"
    assert comps["generate_nonce"] == "nonce_appr"
    assert {"generate_nonce", "nonce_appr", "hashevidence", "magic_appr"} <= set(lp.manifest["ASPS"])
    assert "generate_nonce" not in proto.session["Session_Context"]["ASP_Types"]
    assert json.loads((L1A / "manifest.json").read_text()) == proto.manifest


# ── the real packages ────────────────────────────────────────────────────────


def test_real_raw_package_lays_out_as_sig_nonce_measurements(proto):
    d = describe_package(RAW["PAYLOAD"], ledger_protocol(proto).session)
    assert [s.asp for s in d.spans] == ["sig", "generate_nonce"] + ["hashfile"] * 4
    assert d.nonce.slot == 1 and d.signature_ref.slot == 0 and d.assurance == "signed+nonce"
    assert d.bid == sha256_hex(base64.b64decode(RAW["PAYLOAD"][0]["RawEv"][1]))


def test_real_appraisal_package_binds_the_raw_package(proto):
    session = ledger_protocol(proto).session
    raw = describe_package(RAW["PAYLOAD"], session)
    appr = describe_package(APPR["PAYLOAD"], session, nonce_targid=APPRAISER_NONCE_TARGID)
    assert [s.asp for s in appr.spans][:3] == ["sig", "generate_nonce", "hashevidence"]
    binding = base64.b64decode(APPR["PAYLOAD"][0]["RawEv"][2]).hex()
    assert binding == raw.rawev_sha256
    assert appr.assurance == "signed+nonce" and appr.bid != raw.bid


def test_appraisal_branch_is_the_pure_appr_evidence(proto):
    session = ledger_protocol(proto).session
    branch = appraisal_branch(APPR["PAYLOAD"], session)
    raw_slots = APPR["PAYLOAD"][0]["RawEv"]
    assert branch["PAYLOAD"][0]["RawEv"] == raw_slots[3:]
    d = describe_package(branch["PAYLOAD"], session, nonce_targid=None)
    assert [s.asp for s in d.spans] == ["sig_appr", "nonce_appr"] + ["goldenbytes_appr"] * 4
    with pytest.raises(EvidenceLayoutError):
        appraisal_branch(RAW["PAYLOAD"], session)  # a raw package has no binding


# ── the two-run flow ─────────────────────────────────────────────────────────


def test_attest_with_ledger_commits_a_full_run(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CannedClient()
    archived = {}

    def archive(obj, pid, kind):
        p = tmp_path / "evidence" / f"{pid}.{kind}.json.gz"
        p.parent.mkdir(exist_ok=True)
        with gzip.open(p, "wb") as f:
            f.write(json.dumps(obj).encode())
        archived[kind] = str(p)
        return str(p)

    r = attest(client, proto, ledger, config, archive=archive)
    assert r.error == "", r.error
    assert r.passed and len(r.components) == 6
    assert {c.appr_asp for c in r.components} == {"sig_appr", "nonce_appr", "goldenbytes_appr"}
    assert set(archived) == {"response", "appraisal", "components"}
    assert r.evidence_ref == archived["response"] and r.appraisal_ref == archived["appraisal"]
    assert len(client.requests) == 2
    assert client.requests[1]["EVIDENCE"] == RAW["PAYLOAD"], "run 2 appraises run 1's package"

    m = ledger.get(r.bid)
    a = ledger.get(r.appraisal_bid)
    assert r.ledger_ref == f"bundle/{r.appraisal_bid}"
    assert m.role == "measurement" and m.protocol_id == proto.protocol_id and m.freshness == "post-hoc"
    assert m.assurance == "signed+nonce" and m.nonce.asp == "generate_nonce" and m.bid == sha256_hex(base64.b64decode(m.nonce.b64))
    assert m.signature == __import__("pybb.attestation.ledger", fromlist=["SignatureInfo"]).SignatureInfo(present=True, asp="sig", signer_fp=None)
    assert m.blob.blob_sha256 == sha256_hex(Path(archived["response"]).read_bytes())
    assert [l.store for l in m.blob.locations] == ["local"] and m.appraiser_id == "ap-test"
    assert m.verdict is None and m.inputs is None
    assert a.role == "appraisal" and a.appraisal_kind == "live" and a.protocol_id == proto.protocol_id
    assert a.inputs == [__import__("pybb.attestation.ledger", fromlist=["InputRef"]).InputRef(
        bid=m.bid, binding_hash=m.rawev_sha256)]
    assert a.verdict.passed and a.verdict.components_total == 6 and a.verdict.failing == []
    assert a.verdict.components_blob.blob_sha256 == sha256_hex(Path(archived["components"]).read_bytes())
    assert a.verdict.interpreter.kind in ("verified-summary", "legacy-walker")
    assert ledger.appraisals_of(m.bid) == [a] and ledger.exists(f"judged_by/{m.bid}/{a.bid}")
    assert len(ledger) == 1  # one batch


def test_duplicate_package_is_refused_and_fails_closed(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    first = attest(CannedClient(), proto, ledger, config)
    assert first.passed and first.ledger_ref
    again = attest(CannedClient(), proto, ledger, config)  # same canned nonce
    assert not again.passed and "duplicate nonce" in again.error and again.ledger_ref == ""
    assert len(ledger) == 1


def test_cvm_failures_fail_closed(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest(CannedClient(fail_on="measurement"), proto, ledger, config)
    assert not r.passed and r.error.startswith("measurement run failed") and len(ledger) == 0
    # plan N.4: a good measurement whose appraisal run fails is still recorded, with `error`
    r = attest(CannedClient(fail_on="appraisal"), proto, ledger, config)
    assert not r.passed and r.error.startswith("appraisal run failed") and len(ledger) == 1
    m = ledger.get(r.bid)
    assert m.role == "measurement" and m.error.startswith("appraisal run failed") and m.shape == "measure"
    assert r.ledger_ref == f"bundle/{r.bid}" and ledger.appraisals_of(r.bid) == []


def test_assurance_policy_refuses_unsigned_runs_unless_excepted(proto, config, tmp_path):
    # strip the signature from the real raw package: a `nonce`-level package
    raw = json.loads(json.dumps(RAW))
    et = raw["PAYLOAD"][1]
    assert et["EvidenceT_BODY"][1]["ASP_ID"] == "sig"
    raw["PAYLOAD"] = [{"RawEv": raw["PAYLOAD"][0]["RawEv"][1:]}, et["EvidenceT_BODY"][2]]
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest(CannedClient(raw=raw), proto, ledger, config)
    assert not r.passed and "assurance nonce below minimum signed+nonce" in r.error
    assert len(ledger) == 0
    cfg = config.model_copy(update={"assurance_exceptions": {proto.protocol_id: "demo tier"}})
    r = attest(CannedClient(raw=raw), proto, ledger, cfg)
    assert r.error == "" and r.ledger_ref
    m = ledger.get(r.bid)
    assert m.assurance == "nonce" and m.exception_reason == "demo tier"


def test_predicate_uses_ledger_flow_and_verdict_carries_refs(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CannedClient()
    predicate = make_attestation_predicate(client, {proto.protocol_id: proto},
                                           archive_dir=tmp_path / "evidence",
                                           ledger=ledger, ledger_config=config)
    verdict = predicate({"protocol": proto.protocol_id})
    assert verdict and verdict.bid and verdict.ledger_ref.startswith("bundle/")
    assert ledger.get(verdict.ledger_ref.split("/", 1)[1]).inputs[0].bid == verdict.bid
    for ref in (verdict.evidence_ref, verdict.appraisal_ref, verdict.components_ref):
        assert Path(ref).is_file() and ref.endswith(".json.gz")
    episode_dir = Path(verdict.evidence_ref).parent
    assert len(episode_dir.name) == len("20260101-000000-abcd")
    assert sorted(p.name.split(".")[1] for p in episode_dir.iterdir()) == ["appraisal", "components", "response"]
    comps = json.loads(gzip.open(verdict.components_ref).read())
    assert len(comps) == 6
    # memoized: a second evaluation runs nothing new
    assert predicate({"protocol": proto.protocol_id}) is verdict and len(client.requests) == 2


def test_predicate_without_ledger_is_the_legacy_single_run(proto, tmp_path):
    class Legacy(AttestationClient):
        def run_protocol(self, protocol):
            assert protocol.prebuilt_request is None
            return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": False, "PAYLOAD": "n/a"}

    predicate = make_attestation_predicate(Legacy(), {proto.protocol_id: proto})
    v = predicate({"protocol": proto.protocol_id})
    assert not v and v.bid == "" and v.ledger_ref == ""


# ── fetch and re-appraise from the ledger (plan B.5 / E) ─────────────────────


def _archiver(tmp_path):
    def archive(obj, pid, kind):
        p = tmp_path / "evidence" / f"{pid}.{kind}.json.gz"
        p.parent.mkdir(exist_ok=True)
        with gzip.open(p, "wb") as f:
            f.write(json.dumps(obj).encode())
        return str(p)
    return archive


def test_fetch_bundle_resolves_local_location_and_checks_hash(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import fetch_bundle
    from pybb.attestation.ledger import LedgerError

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest(CannedClient(), proto, ledger, config, archive=_archiver(tmp_path))
    fetched = fetch_bundle(ledger, r.bid)
    assert fetched.payload == RAW["PAYLOAD"] and fetched.location.store == "local"
    # corrupt the archived bytes: the fetch refuses rather than returning them
    Path(r.evidence_ref).write_bytes(gzip.compress(b'{"PAYLOAD": "tampered"}'))
    with pytest.raises(LedgerError, match="sha256"):
        fetch_bundle(ledger, r.bid)
    # no resolvable location at all
    Path(r.evidence_ref).unlink()
    with pytest.raises(LedgerError, match="no location"):
        fetch_bundle(ledger, r.bid)


def _distinct_appraisal(tag: int):
    """The canned appraisal package carries the same appraiser nonce as the
    live one; a real CVM draws a fresh one — give each appraisal a distinct
    canned nonce."""
    pkg = json.loads(json.dumps(APPR))
    pkg["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([tag]) * 32).decode()
    return pkg


def test_appraise_bundle_records_another_appraisal_of_the_measurement(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import appraise_bundle

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    archive = _archiver(tmp_path)
    live = attest(CannedClient(), proto, ledger, config, archive=archive)
    rep = appraise_bundle(CannedClient(appr=_distinct_appraisal(7)), proto, ledger, config, live.bid, archive=archive)
    assert rep.error == "", rep.error
    assert rep and rep.ledger_verified and rep.bytes_match and rep.bid_ok and rep.input_role == "measurement"
    assert rep.signature_ok is True and rep.nonce_wellformed is True and rep.binding_ok is None
    assert rep.agrees_with_live is True and rep.appraisal_kind == "audit"
    assert rep.ledger_ref == f"bundle/{rep.appraisal_bid}"
    of_m = ledger.appraisals_of(live.bid)
    assert [a.appraisal_kind for a in of_m] == ["live", "audit"]
    audit = of_m[1]
    assert audit.inputs[0].bid == live.bid and audit.inputs[0].binding_hash == ledger.get(live.bid).rawev_sha256
    assert audit.verdict.checks == {"ledger_verified": True, "bytes_match": True, "bid_ok": True}
    assert audit.verdict.agrees_with_live is True and audit.session_sha256 == of_m[0].session_sha256
    # the same canned appraiser nonce again: refused as a duplicate
    again = appraise_bundle(CannedClient(appr=_distinct_appraisal(7)), proto, ledger, config, live.bid)
    assert "duplicate" in again.error and not again
    # a different policy: a session override is pinned by session_sha256 and not compared with live
    # (the canned package fixes the companions that ran; the override differs by an extra ASP type)
    session = json.loads(json.dumps(proto.session))
    session["Session_Context"]["ASP_Types"]["extra_appr"] = {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []}
    rep2 = appraise_bundle(CannedClient(appr=_distinct_appraisal(8)), proto, ledger, config, live.bid,
                           session_override=session, appraisal_kind="no-goldens")
    assert rep2.error == "" and rep2.agrees_with_live is None
    other = ledger.get(rep2.appraisal_bid)
    assert other.appraisal_kind == "no-goldens" and other.session_sha256 != audit.session_sha256


def test_appraise_bundle_fails_closed_on_unknown_bundle_and_wrong_protocol(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import appraise_bundle

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    rep = appraise_bundle(CannedClient(), proto, ledger, config, "00" * 32)
    assert not rep and rep.error.startswith("fetch failed")
    live = attest(CannedClient(), proto, ledger, config, archive=_archiver(tmp_path))
    other = proto.model_copy(update={"protocol_id": "some_other_protocol"})
    rep = appraise_bundle(CannedClient(), other, ledger, config, live.bid)
    assert "is of protocol" in rep.error


def test_ledger_request_routes_the_predicate_to_an_audit(proto, config, tmp_path):
    from pybb.attestation import ledger_request

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CannedClient()
    predicate = make_attestation_predicate(client, {proto.protocol_id: proto},
                                           archive_dir=tmp_path / "evidence",
                                           ledger=ledger, ledger_config=config)
    live = predicate({"protocol": proto.protocol_id})
    assert live
    client.appr = _distinct_appraisal(9)
    audit = predicate(ledger_request(live.bid))
    assert audit.error == "", audit.error
    assert audit and audit.bid == live.bid and audit.ledger_ref.startswith("bundle/") and audit.ledger_ref != live.ledger_ref
    assert audit.protocol == proto.protocol_id and Path(audit.appraisal_ref).name.startswith(proto.protocol_id + ".appraisal-audit")
    assert len(client.requests) == 3  # two live runs + one audit appraisal run

    # a disagreeing audit is a failing verdict with an explicit reason
    failing_pkg = _distinct_appraisal(11)
    failing_pkg["PAYLOAD"][0]["RawEv"][5] = base64.b64encode(b"File contents do not match").decode()
    client.appr = failing_pkg
    predicate.forget(ledger_request(live.bid))
    disagree = predicate(ledger_request(live.bid))
    assert not disagree and "disagrees with the live appraisal" in disagree.error

    # without a ledger the audit request is a configuration error
    plain = make_attestation_predicate(CannedClient(), {proto.protocol_id: proto})
    v = plain(ledger_request(live.bid))
    assert not v and "no ledger is configured" in v.error


# ── shape `combined` (plan M.2), on the spiked l1a packages ──────────────────

COMBINED = json.loads((FIXTURES / "ledger/l1a_combined.response.json").read_text())
COMBINED_AUDIT = json.loads((FIXTURES / "ledger/l1a_combined_audit.response.json").read_text())
COMBINED_TERM = json.loads((FIXTURES / "ledger/l1a_combined.term.json").read_text())


def test_combined_term_and_session_match_the_spike(proto):
    from pybb.attestation.ledger_runs import combined_session, combined_term

    assert combined_term(proto) == COMBINED_TERM
    types = combined_session(proto.session)["Session_Context"]["ASP_Types"]
    assert types["hashevidence"]["FWD"] == {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "ALL"}
    assert types["goldenbytes_appr"]["FWD"]["FWD"] == "REPLACE"  # companions unchanged
    assert "hashevidence" in types and types["sig"]["FWD"]["FWD"] == "EXTEND"


def test_hash_lane_offsets_for_replace_and_extend(proto):
    from pybb.attestation.ledger_runs import combined_session, hash_lane, lift_measurement

    split_sess = ledger_protocol(proto).session
    _l, right, off = hash_lane(APPR["PAYLOAD"], split_sess)
    assert off == 3  # sig, nonce, H under a REPLACE hashevidence
    comb_sess = combined_session(proto.session)
    _l, right, off = hash_lane(COMBINED["PAYLOAD"], comb_sess)
    assert off == 9  # sig2, nonce2, H, then the six retained slots of P
    p = lift_measurement(COMBINED["PAYLOAD"], comb_sess)
    assert len(p[0]["RawEv"]) == 6
    dp = describe_package(p, comb_sess)
    assert dp.assurance == "signed+nonce" and dp.bid
    H = base64.b64decode(COMBINED["PAYLOAD"][0]["RawEv"][2]).hex()
    assert dp.rawev_sha256 == H
    # the whole package: one appraiser nonce, a different bundle id
    da = describe_package(COMBINED["PAYLOAD"], comb_sess, nonce_targid=APPRAISER_NONCE_TARGID)
    assert da.assurance == "signed+nonce" and da.bid != dp.bid and da.rawev_count == 13


def test_attest_combined_yields_the_split_artifacts_from_one_run(proto, config, tmp_path):
    from pybb.attestation.ledger import InputRef
    from pybb.attestation.ledger_runs import fetch_bundle, lift_measurement, combined_session

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CannedClient(appr=COMBINED)  # the combined term contains APPR: served the combined package
    r = attest(client, proto, ledger, config, archive=_archiver(tmp_path), shape="combined")
    assert r.error == "", r.error
    assert r.shape == "combined" and r.passed and len(client.requests) == 1
    assert [c.appr_asp for c in r.components] == ["goldenbytes_appr"] * 4  # M only: no sig/nonce verdicts
    m, a = ledger.get(r.bid), ledger.get(r.appraisal_bid)
    assert m.shape == a.shape == "combined" and m.role == "measurement" and a.role == "appraisal"
    assert m.blob.derived_from == a.bid and a.blob.derived_from is None
    assert a.inputs == [InputRef(bid=m.bid, binding_hash=m.rawev_sha256)]
    assert a.verdict.passed and a.verdict.components_total == 4 and a.appraisal_kind == "live"
    assert ledger.appraisals_of(m.bid) == [a] and len(ledger) == 1
    # the lifted P is archived as a response of its own and fetches back byte for byte
    fetched = fetch_bundle(ledger, m.bid)
    assert fetched.payload == lift_measurement(COMBINED["PAYLOAD"], combined_session(proto.session))
    assert m.signature.asp == "sig" and m.nonce.asp == "generate_nonce" and m.assurance == "signed+nonce"
    # the whole package is the appraisal bundle's blob
    assert fetch_bundle(ledger, a.bid).payload == COMBINED["PAYLOAD"]


def test_shape_comes_from_config(proto, config, tmp_path, monkeypatch):
    from pybb.attestation.ledger import LedgerConfig

    assert config.shape_for(proto.protocol_id) == "split"
    cfg = config.model_copy(update={"shapes": {proto.protocol_id: "combined"}})
    assert cfg.shape_for(proto.protocol_id) == "combined" and cfg.shape_for("other") == "split"
    monkeypatch.setenv("PYBB_BUNDLE_SHAPE", "combined")
    assert LedgerConfig(evidence_repo="").default_shape == "combined"
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest(CannedClient(appr=COMBINED), proto, ledger, cfg)
    assert r.error == "" and r.shape == "combined"
    bad = attest(CannedClient(), proto, ledger, config, shape="sideways")
    assert not bad.passed and "unknown bundle shape" in bad.error and len(ledger) == 1


def test_appraising_a_combined_appraisal_bundle_keeps_the_extend_typing(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import appraise_bundle, needs_keep

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    archive = _archiver(tmp_path)
    live = attest(CannedClient(appr=COMBINED), proto, ledger, config, archive=archive, shape="combined")
    assert live.error == ""
    a = ledger.get(live.appraisal_bid)
    assert needs_keep(ledger, a) and not needs_keep(ledger, ledger.get(live.bid))
    rep = appraise_bundle(CannedClient(appr=COMBINED_AUDIT), proto, ledger, config, live.appraisal_bid,
                          archive=archive)
    assert rep.error == "", rep.error
    assert rep and rep.input_role == "appraisal" and rep.binding_ok is True
    assert rep.signature_ok is True and rep.nonce_wellformed is True
    kinds = {}
    for c in rep.components:
        kinds[c.appr_asp] = kinds.get(c.appr_asp, 0) + 1
    assert kinds == {"sig_appr": 2, "nonce_appr": 2, "goldenbytes_appr": 5, "magic_appr": 4}
    audit = ledger.get(rep.appraisal_bid)
    assert audit.shape == "appraise" and audit.inputs[0].bid == a.bid and needs_keep(ledger, audit)
    assert ledger.appraisals_of(a.bid) == [audit]


# ── measure now, appraise later (plan N) ─────────────────────────────────────


def test_measure_records_one_bundle_and_nothing_judges_it(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import appraise_bundle, measure

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = measure(CannedClient(), proto, ledger, config, archive=_archiver(tmp_path))
    assert r.error == "", r.error
    assert r.bid and r.ledger_ref == f"bundle/{r.bid}" and r.assurance == "signed+nonce" and r.shape == "measure"
    assert len(ledger) == 1 and [k for _t, k, _r in ledger.history()] == [r.ledger_ref]
    m = ledger.get(r.bid)
    assert m.role == "measurement" and m.shape == "measure" and m.error == "" and ledger.appraisals_of(m.bid) == []
    assert Path(r.evidence_ref).is_file()
    # the same package again is a duplicate
    again = measure(CannedClient(), proto, ledger, config)
    assert "duplicate" in again.error and len(ledger) == 1
    # the first later appraisal is labelled `deferred` (N.3), with no live verdict to agree with
    rep = appraise_bundle(CannedClient(appr=_distinct_appraisal(21)), proto, ledger, config, r.bid)
    assert rep.error == "" and rep.appraisal_kind == "deferred" and rep.agrees_with_live is None
    a = ledger.appraisals_of(r.bid)[0]
    assert a.appraisal_kind == "deferred" and a.shape == "appraise" and a.inputs[0].bid == r.bid
    # the next one is an audit by default, and a caller may still label either
    rep2 = appraise_bundle(CannedClient(appr=_distinct_appraisal(22)), proto, ledger, config, r.bid)
    assert rep2.appraisal_kind == "audit"
    rep3 = appraise_bundle(CannedClient(appr=_distinct_appraisal(23)), proto, ledger, config, r.bid,
                           appraisal_kind="golden-set-2026-11")
    assert ledger.get(rep3.appraisal_bid).appraisal_kind == "golden-set-2026-11"


def test_measure_fails_closed_like_attest(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import measure

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = measure(CannedClient(fail_on="measurement"), proto, ledger, config)
    assert r.error.startswith("measurement run failed") and not r.bid and len(ledger) == 0
    raw = json.loads(json.dumps(RAW)); et = raw["PAYLOAD"][1]
    raw["PAYLOAD"] = [{"RawEv": raw["PAYLOAD"][0]["RawEv"][1:]}, et["EvidenceT_BODY"][2]]  # unsigned
    r = measure(CannedClient(raw=raw), proto, ledger, config)
    assert "assurance nonce below minimum" in r.error and len(ledger) == 0


def test_shape_names_the_constructor(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest(CannedClient(), proto, ledger, config)
    assert ledger.get(r.bid).shape == "measure" and ledger.get(r.appraisal_bid).shape == "appraise"


def test_measurement_predicate_returns_measured_not_appraised(proto, config, tmp_path):
    from pybb.attestation import Appraised, Measured, ledger_request, make_measurement_predicate

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CannedClient()
    measured = make_measurement_predicate(client, {proto.protocol_id: proto}, archive_dir=tmp_path / "evidence",
                                          ledger=ledger, ledger_config=config)
    m = measured({"protocol": proto.protocol_id})
    assert isinstance(m, Measured) and not isinstance(m, Appraised)
    assert m and m.bid and m.ledger_ref == f"bundle/{m.bid}" and Path(m.evidence_ref).is_file()
    assert len(client.requests) == 1 and len(ledger) == 1
    assert measured({"protocol": proto.protocol_id}) is m  # memoized
    assert not measured({"protocol": "nope"}) and "unknown protocol" in measured({"protocol": "nope"}).error
    # judging it later goes through the attestation predicate, as a deferred appraisal
    client.appr = _distinct_appraisal(31)
    judged = make_attestation_predicate(client, {proto.protocol_id: proto}, archive_dir=tmp_path / "evidence",
                                        ledger=ledger, ledger_config=config)(ledger_request(m.bid))
    assert isinstance(judged, Appraised) and judged and judged.bid == m.bid
    assert ledger.get(judged.ledger_ref.split("/", 1)[1]).appraisal_kind == "deferred"
    # without a ledger there is nothing to record into
    unled = make_measurement_predicate(CannedClient(), {proto.protocol_id: proto})({"protocol": proto.protocol_id})
    assert not unled and "needs a ledger" in unled.error
