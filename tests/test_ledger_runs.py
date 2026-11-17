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
    attest_with_ledger,
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
    return LedgerConfig(state_dir=str(tmp_path / "state"), appraiser_id="ap-test",
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
    assert d.nonce.slot == 1 and d.signature.slot == 0 and d.assurance == "signed+nonce"
    assert d.nid == sha256_hex(base64.b64decode(RAW["PAYLOAD"][0]["RawEv"][1]))


def test_real_appraisal_package_binds_the_raw_package(proto):
    session = ledger_protocol(proto).session
    raw = describe_package(RAW["PAYLOAD"], session)
    appr = describe_package(APPR["PAYLOAD"], session, nonce_targid=APPRAISER_NONCE_TARGID)
    assert [s.asp for s in appr.spans][:3] == ["sig", "generate_nonce", "hashevidence"]
    binding = base64.b64decode(APPR["PAYLOAD"][0]["RawEv"][2]).hex()
    assert binding == raw.rawev_sha256
    assert appr.assurance == "signed+nonce" and appr.nid != raw.nid


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

    r = attest_with_ledger(client, proto, ledger, config, archive=archive)
    assert r.error == "", r.error
    assert r.passed and len(r.components) == 6
    assert {c.appr_asp for c in r.components} == {"sig_appr", "nonce_appr", "goldenbytes_appr"}
    assert set(archived) == {"response", "appraisal", "components"}
    assert r.evidence_ref == archived["response"] and r.appraisal_ref == archived["appraisal"]
    assert len(client.requests) == 2
    assert client.requests[1]["EVIDENCE"] == RAW["PAYLOAD"], "run 2 appraises run 1's package"

    run = ledger.get(r.nonce_id)
    assert r.ledger_ref == f"evidence/{r.nonce_id}"
    assert run.nonce.role == "measurement" and run.nonce.protocol_id == proto.protocol_id
    assert run.evidence.assurance == "signed+nonce" and run.evidence.nonce.slot == 1
    assert run.evidence.blob_sha256 == sha256_hex(Path(archived["response"]).read_bytes())
    assert run.evidence.locators[0].appraiser_id == "ap-test"
    assert run.verdict.passed and run.verdict.components_total == 6 and run.verdict.failing == []
    assert run.appraisals[0].mode == "live" and run.appraisals[0].binding.evidence_hash == run.evidence.rawev_sha256
    assert run.appraisals[0].binding.matches_evidence is None  # judged only by a CVM-native audit
    assert run.appraiser_nonces[0].for_nid == r.nonce_id
    assert {l.target for l in run.locators} == {"appraisal", "components"}
    assert len(ledger) == 1  # one batch


def test_duplicate_package_is_refused_and_fails_closed(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    first = attest_with_ledger(CannedClient(), proto, ledger, config)
    assert first.passed and first.ledger_ref
    again = attest_with_ledger(CannedClient(), proto, ledger, config)  # same canned nonce
    assert not again.passed and "duplicate nonce" in again.error and again.ledger_ref == ""
    assert len(ledger) == 1


def test_cvm_failures_fail_closed(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest_with_ledger(CannedClient(fail_on="measurement"), proto, ledger, config)
    assert not r.passed and r.error.startswith("measurement run failed") and len(ledger) == 0
    r = attest_with_ledger(CannedClient(fail_on="appraisal"), proto, ledger, config)
    assert not r.passed and r.error.startswith("appraisal run failed") and len(ledger) == 0


def test_assurance_policy_refuses_unsigned_runs_unless_excepted(proto, config, tmp_path):
    # strip the signature from the real raw package: a `nonce`-level package
    raw = json.loads(json.dumps(RAW))
    et = raw["PAYLOAD"][1]
    assert et["EvidenceT_BODY"][1]["ASP_ID"] == "sig"
    raw["PAYLOAD"] = [{"RawEv": raw["PAYLOAD"][0]["RawEv"][1:]}, et["EvidenceT_BODY"][2]]
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest_with_ledger(CannedClient(raw=raw), proto, ledger, config)
    assert not r.passed and "assurance nonce below minimum signed+nonce" in r.error
    assert len(ledger) == 0
    cfg = config.model_copy(update={"assurance_exceptions": {proto.protocol_id: "demo tier"}})
    r = attest_with_ledger(CannedClient(raw=raw), proto, ledger, cfg)
    assert r.error == "" and r.ledger_ref
    ev = ledger.get(r.nonce_id).evidence
    assert ev.assurance == "nonce" and ev.exception_reason == "demo tier"


def test_predicate_uses_ledger_flow_and_verdict_carries_refs(proto, config, tmp_path):
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CannedClient()
    predicate = make_attestation_predicate(client, {proto.protocol_id: proto},
                                           archive_dir=tmp_path / "evidence",
                                           ledger=ledger, ledger_config=config)
    verdict = predicate({"protocol": proto.protocol_id})
    assert verdict and verdict.nonce_id and verdict.ledger_ref == f"evidence/{verdict.nonce_id}"
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
    assert not v and v.nonce_id == "" and v.ledger_ref == ""


# ── fetch and re-appraise from the ledger (plan B.5 / E) ─────────────────────


def _archiver(tmp_path):
    def archive(obj, pid, kind):
        p = tmp_path / "evidence" / f"{pid}.{kind}.json.gz"
        p.parent.mkdir(exist_ok=True)
        with gzip.open(p, "wb") as f:
            f.write(json.dumps(obj).encode())
        return str(p)
    return archive


def test_fetch_run_resolves_local_locator_and_checks_hash(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import fetch_run
    from pybb.attestation.ledger import LedgerError

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = attest_with_ledger(CannedClient(), proto, ledger, config, archive=_archiver(tmp_path))
    fetched = fetch_run(ledger, r.nonce_id)
    assert fetched.payload == RAW["PAYLOAD"] and fetched.locator.kind == "local"
    # corrupt the archived bytes: the fetch refuses rather than returning them
    Path(r.evidence_ref).write_bytes(gzip.compress(b'{"PAYLOAD": "tampered"}'))
    with pytest.raises(LedgerError, match="sha256"):
        fetch_run(ledger, r.nonce_id)
    # no resolvable locator at all
    Path(r.evidence_ref).unlink()
    with pytest.raises(LedgerError, match="no locator"):
        fetch_run(ledger, r.nonce_id)


def test_appraise_record_appends_a_signed_audit(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import appraise_record

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    archive = _archiver(tmp_path)
    live = attest_with_ledger(CannedClient(), proto, ledger, config, archive=archive)
    # the canned appraisal package carries the same appraiser nonce as the live
    # one; a real CVM draws a fresh one — give the audit a distinct canned nonce
    audit_pkg = json.loads(json.dumps(APPR))
    raw = audit_pkg["PAYLOAD"][0]["RawEv"]
    raw[1] = base64.b64encode(bytes([7]) * 32).decode()
    rep = appraise_record(CannedClient(appr=audit_pkg), proto, ledger, config, live.nonce_id,
                          archive=archive)
    assert rep.error == "", rep.error
    assert rep and rep.ledger_verified and rep.bytes_match and rep.nid_ok
    assert rep.signature_ok is True and rep.nonce_wellformed is True
    assert rep.agrees_with_recorded_verdict is True and rep.seq == 2
    assert rep.ledger_ref == f"appraisal/{live.nonce_id}/2"
    run = ledger.get(live.nonce_id)
    assert [a.seq for a in run.appraisals] == [1, 2]
    assert run.appraisals[1].mode == "audit" and run.appraisals[1].audits_seq is None
    assert run.appraisals[1].checks == {"ledger_verified": True, "bytes_match": True, "nid_ok": True}
    assert len(run.appraiser_nonces) == 2 and run.appraiser_nonces[1].nid == run.appraisals[1].anid
    # the same canned appraiser nonce again: refused as a duplicate
    again = appraise_record(CannedClient(appr=audit_pkg), proto, ledger, config, live.nonce_id)
    assert "duplicate nonce" in again.error and not again


def test_appraise_record_fails_closed_on_unknown_run_and_wrong_protocol(proto, config, tmp_path):
    from pybb.attestation.ledger_runs import appraise_record

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    rep = appraise_record(CannedClient(), proto, ledger, config, "00" * 32)
    assert not rep and rep.error.startswith("fetch failed")
    live = attest_with_ledger(CannedClient(), proto, ledger, config, archive=_archiver(tmp_path))
    other = proto.model_copy(update={"protocol_id": "some_other_protocol"})
    rep = appraise_record(CannedClient(), other, ledger, config, live.nonce_id)
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
    audit_pkg = json.loads(json.dumps(APPR))
    audit_pkg["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([9]) * 32).decode()
    client.appr = audit_pkg
    audit = predicate(ledger_request(live.nonce_id))
    assert audit.error == "", audit.error
    assert audit and audit.nonce_id == live.nonce_id and audit.ledger_ref == f"appraisal/{live.nonce_id}/2"
    assert audit.protocol == proto.protocol_id and Path(audit.appraisal_ref).name.startswith(proto.protocol_id + ".audit-appraisal")
    assert len(client.requests) == 3  # two live runs + one audit appraisal run

    # a disagreeing audit is a failing verdict with an explicit reason
    failing_pkg = json.loads(json.dumps(APPR))
    failing_pkg["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([11]) * 32).decode()
    failing_pkg["PAYLOAD"][0]["RawEv"][5] = base64.b64encode(b"File contents do not match").decode()
    client.appr = failing_pkg
    predicate.forget(ledger_request(live.nonce_id))
    disagree = predicate(ledger_request(live.nonce_id))
    assert not disagree and "disagrees with the recorded verdict" in disagree.error

    # without a ledger the audit request is a configuration error
    plain = make_attestation_predicate(CannedClient(), {proto.protocol_id: proto})
    v = plain(ledger_request(live.nonce_id))
    assert not v and "no ledger is configured" in v.error
