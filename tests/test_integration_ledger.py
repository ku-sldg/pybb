"""End-to-end: the nonce'd two-run ledger flow against the real CVM, asp-libs
ASPs (including generate_nonce / nonce_appr / hashevidence) and the
temp-control-jvm tree, committing to a FileLedger.

Auto-skipped unless those binaries and the fixture's targets are present.
"""

import gzip
import json
import os
from pathlib import Path

import pytest

from pybb.attestation import CvmSubprocessClient, FileLedger, ProtocolDir, make_attestation_predicate
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.ledger import APPRAISER_NONCE_TARGID, LedgerConfig, describe_package
from pybb.attestation.ledger_runs import (
    appraisal_branch,
    attest,
    ledger_protocol,
    measurement_request,
)

FIXTURES = Path(__file__).parent / "fixtures"
L1A = FIXTURES / "temp_control_aadl_slang_l1a"
NEEDED_ASPS = ("hashfile", "sig", "sig_appr", "goldenbytes_appr",
               "generate_nonce", "nonce_appr", "hashevidence", "magic_appr")


def _targets_present() -> bool:
    args = json.loads((L1A / "asp_args.json").read_text())
    return all(os.path.isfile(a["filepath"]) for t in args.values() for a in t.values())


pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (os.path.isfile(DEFAULT_CVM_BINARY)
             and all(os.path.isfile(os.path.join(DEFAULT_ASP_BIN, a)) for a in NEEDED_ASPS)
             and _targets_present()),
        reason="CVM binary, ledger ASPs, or temp-control-jvm targets not present",
    ),
]


@pytest.fixture
def config(tmp_path) -> LedgerConfig:
    return LedgerConfig(state_dir=str(tmp_path / "state"), appraiser_id="ap-itest", evidence_repo="")


def test_two_runs_land_in_the_ledger_with_distinct_nonces(tmp_path, config):
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CvmSubprocessClient()
    predicate = make_attestation_predicate(client, {proto.protocol_id: proto},
                                           archive_dir=tmp_path / "evidence",
                                           ledger=ledger, ledger_config=config)
    v1 = predicate({"protocol": proto.protocol_id})
    assert v1.error == "", v1.error
    assert v1 and v1.bid and v1.ledger_ref.startswith("bundle/")
    assert {c.appr_asp for c in v1.components} == {"sig_appr", "nonce_appr", "goldenbytes_appr"}
    assert all(c.passed for c in v1.components)

    # a second predicate instance = a fresh run with a fresh nonce
    predicate2 = make_attestation_predicate(client, {proto.protocol_id: proto},
                                            archive_dir=tmp_path / "evidence",
                                            ledger=ledger, ledger_config=config)
    v2 = predicate2({"protocol": proto.protocol_id})
    assert v2.error == "" and v2.bid != v1.bid
    assert len(ledger) == 2 and ledger.exists(f"bundle/{v1.bid}") and ledger.exists(f"bundle/{v2.bid}")

    # the archived raw package is re-describable and matches its record
    raw = json.loads(gzip.open(v1.evidence_ref).read())
    lp = ledger_protocol(proto)
    d = describe_package(raw["PAYLOAD"], lp.session)
    m = ledger.get(v1.bid)
    a = ledger.appraisals_of(v1.bid)[0]
    assert d.bid == v1.bid and d.rawev_sha256 == m.rawev_sha256
    assert m.assurance == "signed+nonce" and a.assurance == "signed+nonce" and a.appraisal_kind == "live"
    # the appraisal package binds exactly that raw package
    appr = json.loads(gzip.open(v1.appraisal_ref).read())
    da = describe_package(appr["PAYLOAD"], lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    assert da.bid == a.bid and v1.ledger_ref == f"bundle/{a.bid}"
    assert a.inputs[0].bid == m.bid and a.inputs[0].binding_hash == d.rawev_sha256
    branch = appraisal_branch(appr["PAYLOAD"], lp.session)
    assert len(branch["PAYLOAD"][0]["RawEv"]) == len(v1.components)


def test_replaying_an_archived_package_is_refused(tmp_path, config):
    """A client that returns a previously archived raw package instead of
    measuring: the ledger already holds its nonce and refuses the run."""
    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    real = CvmSubprocessClient()
    first = attest(real, proto, ledger, config)
    assert first.passed, first.error

    class Replayer:
        def __init__(self, raw):
            self.raw = raw

        def run_protocol(self, protocol):
            req = protocol.prebuilt_request
            if req["EVIDENCE"] == [{"RawEv": []}, {"EvidenceT_CONSTRUCTOR": "mt_evt"}]:
                return self.raw  # "measured": actually the old package
            return real.run_protocol(protocol)  # appraise honestly

    # a genuinely fresh raw package, measured once by the real CVM
    lp = ledger_protocol(proto)
    raw_pkg = real.run_protocol(lp.model_copy(update={"prebuilt_request": measurement_request(lp)}))
    r = attest(Replayer(raw_pkg), proto, ledger, config)
    assert r.passed and r.bid != first.bid  # a genuinely new package is fine
    again = attest(Replayer(raw_pkg), proto, ledger, config)
    assert not again.passed and "duplicate nonce" in again.error
    assert len(ledger) == 2


def test_appraisal_paths_against_the_real_cvm(tmp_path, config):
    """B.5 re-appraisal of the measurement bundle and B.6 appraisal of the
    appraisal bundle, both judged inside the CVM; then a tampered appraisal blob."""
    from pybb.attestation.ledger_runs import appraise_bundle

    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CvmSubprocessClient()

    def archive(obj, pid, kind):
        p = tmp_path / "evidence" / f"{pid}.{kind}.json.gz"
        p.parent.mkdir(exist_ok=True)
        with gzip.open(p, "wb") as f:
            f.write(json.dumps(obj).encode())
        return str(p)

    live = attest(client, proto, ledger, config, archive=archive)
    assert live.passed, live.error

    rep = appraise_bundle(client, proto, ledger, config, live.bid, archive=archive)
    assert rep.error == "", rep.error
    assert rep and rep.signature_ok and rep.nonce_wellformed and rep.agrees_with_live
    assert rep.input_role == "measurement" and rep.assurance == "signed+nonce"
    assert [a.appraisal_kind for a in ledger.appraisals_of(live.bid)] == ["live", "audit"]

    audit = appraise_bundle(client, proto, ledger, config, live.appraisal_bid, appraisal_kind="audit", archive=archive)
    assert audit.error == "", audit.error
    assert audit and audit.binding_ok and audit.signature_ok and audit.nonce_wellformed
    assert audit.input_role == "appraisal" and audit.assurance == "signed+nonce"
    of_live = ledger.appraisals_of(live.appraisal_bid)
    assert len(of_live) == 1 and of_live[0].inputs[0].bid == live.appraisal_bid
    assert of_live[0].verdict.interpreter.kind == "legacy-walker" and of_live[0].verdict.agrees_with_live is None

    # tamper the archived live appraisal package: the fetch refuses it
    p = Path(next(l.path for l in ledger.get(live.appraisal_bid).blob.locations if l.store == "local"))
    data = json.loads(gzip.open(p).read())
    slots = data["PAYLOAD"][0]["RawEv"]
    b = bytearray(__import__("base64").b64decode(slots[2])); b[0] ^= 0xFF
    slots[2] = __import__("base64").b64encode(bytes(b)).decode()
    with gzip.open(p, "wb") as f:
        f.write(json.dumps(data).encode())
    tampered = appraise_bundle(client, proto, ledger, config, live.appraisal_bid)
    assert not tampered and "blob_sha256" in tampered.error


def test_stack_and_config_evidence_with_the_real_cvm(tmp_path, config):
    """Plan O: the CVM measures the installation (`stack`) and one protocol's
    inputs (`config`); runs carry no pointer, the reader derives both; an
    audit judges a stack bundle against a blessing's goldens and a config
    bundle against its archived files; a rebuilt binary fails the audit
    against the old blessing and passes after re-blessing."""
    import shutil

    from pybb.attestation.client import CvmConfig
    from pybb.attestation.ledger_context import bless, derive_context, measure_config, measure_stack
    from pybb.attestation.ledger_runs import appraise_bundle, archiver

    proto = ProtocolDir.load(str(L1A))
    cfg = config.model_copy(update={"golden_root": str(tmp_path / "golden")})
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CvmSubprocessClient()
    archive = archiver(tmp_path / "evidence")

    # a copy of the ASP directory stands in for an installation we may rebuild
    real = CvmConfig()
    asps = tmp_path / "asps"
    asps.mkdir()
    for name in ("hashfile", "sig", "sig_appr", "goldenbytes_appr", "generate_nonce", "nonce_appr"):
        shutil.copy2(Path(real.asp_bin) / name, asps / name)
    fake = real.model_copy(update={"asp_bin": str(asps)})

    s1 = measure_stack(client, ledger, cfg, cvm_config=fake, archive=archive)
    assert s1, s1.error
    rec = ledger.get(s1.bid)
    assert rec.role == "stack" and rec.assurance == "signed+nonce" and rec.stack.executables == 8  # cvm, summarizer, 6 asps
    assert s1.targets == 10  # + key + invocation
    b1 = bless(ledger, cfg, s1.bid, note="first install")
    assert set(b1.goldens) == {"stack:cvm", "stack:summarizer", "stack:pubkey", "stack:invocation"} | {
        f"stack:asp:{n}" for n in ("hashfile", "sig", "sig_appr", "goldenbytes_appr", "generate_nonce", "nonce_appr")}
    c1 = measure_config(client, proto, ledger, cfg, archive=archive)
    assert c1, c1.error

    # runs carry no pointer; the reader derives stack, blessing and configuration
    predicate = make_attestation_predicate(client, {proto.protocol_id: proto}, archive_dir=tmp_path / "evidence",
                                           ledger=ledger, ledger_config=cfg)
    v = predicate({"protocol": proto.protocol_id})
    assert v.error == "", v.error
    m = ledger.get(v.bid)
    assert m.tooling is None and m.to_dict().get("context") is None
    d = derive_context(ledger, m)
    assert d and d.constructor == "measure" and d.stack_bid == s1.bid and d.stack_status == "blessed"
    assert d.config_bid == c1.bid and d.pins == {"term": True, "session": True, "manifest": True}
    live = ledger.appraisals_of(v.bid)[0]
    assert derive_context(ledger, live).constructor == "appraise"
    # the B.6 audit of the live appraisal now runs under the static audit session: constructor `audit`
    audit = appraise_bundle(client, proto, ledger, cfg, live.key_id, archive=archive)
    assert audit, audit.error
    assert derive_context(ledger, ledger.get(audit.appraisal_bid)).constructor == "audit"

    # audits of the context bundles themselves (plan O.6)
    sa = appraise_bundle(client, None, ledger, cfg, s1.bid, archive=archive)
    assert sa.error == "", sa.error
    assert sa.passed and sa.baseline == f"blessing/{s1.bid}" and sa.signature_ok and sa.nonce_wellformed
    assert len([c for c in sa.components if c.appr_asp == "goldenbytes_appr"]) == s1.targets
    assert ledger.get(sa.appraisal_bid).baseline == f"blessing/{s1.bid}"
    ca = appraise_bundle(client, None, ledger, cfg, c1.bid, archive=archive)
    assert ca.error == "", ca.error
    assert ca.passed and ca.baseline == "" and ledger.get(ca.appraisal_bid).baseline is None

    # "rebuild" one ASP: the next stack measurement fails the audit against the old blessing
    (asps / "nonce_appr").write_bytes((asps / "nonce_appr").read_bytes() + b"\n# rebuilt\n")
    s2 = measure_stack(client, ledger, cfg, cvm_config=fake, archive=archive)
    assert s2, s2.error
    drift = appraise_bundle(client, None, ledger, cfg, s2.bid, archive=archive)
    assert drift.error == "", drift.error
    assert not drift.passed and drift.baseline == f"blessing/{s1.bid}"
    assert {c.targ_id for c in drift.components if not c.passed} == {"stack:asp:nonce_appr"}
    bless(ledger, cfg, s2.bid, note="rebuilt nonce_appr")
    ok = appraise_bundle(client, None, ledger, cfg, s2.bid, archive=archive)
    assert ok.passed and ok.baseline == f"blessing/{s2.bid}", ok.error
    # runs between the rebuild and `measure stack` derive S1; later ones S2
    assert derive_context(ledger, m).stack_bid == s1.bid
    predicate.forget({"protocol": proto.protocol_id})
    v2 = predicate({"protocol": proto.protocol_id})
    assert v2.error == "", v2.error
    assert derive_context(ledger, ledger.get(v2.bid)).stack_bid == s2.bid


def test_nonced_provisioning_bundle_verifies_and_keys_by_nonce(tmp_path, config):
    """Plan point 4: re-provision l1a into a scratch golden root. The bundle
    carries generate_nonce + SIG, goldens extract unchanged, verify_bundle
    appraises it (nonce_ok), and the ledger keys it by nonce id."""
    import shutil
    from pybb.attestation import TargetSnapshot, verify_bundle
    from pybb.attestation.ledger import LedgerConfig
    from pybb.attestation.ledger_repo import record_provision_bundles
    from pybb.attestation.provision import make_provision_predicate, provision_request

    golden = tmp_path / "golden"
    proto_dir = tmp_path / "protos" / "temp_control_aadl_slang_l1a"
    shutil.copytree(L1A, proto_dir)
    proto = ProtocolDir.load(str(proto_dir))
    before = {t: a["golden_b64"] for t, a in proto.asp_args["hashfile"].items()}
    TargetSnapshot.capture({proto.protocol_id: proto}, dest=golden)
    client = CvmSubprocessClient()

    outcome = make_provision_predicate(client, {proto.protocol_id: proto}, golden)(
        provision_request(proto.protocol_id))
    assert outcome.error == "", outcome.error
    assert set(outcome.provisioned) == set(before)
    after = {t: a["golden_b64"] for t, a in proto.asp_args["hashfile"].items()}
    assert after == before, "unchanged targets must extract the same goldens through the nonce'd layout"

    payload, ctx = json.loads(Path(outcome.bundle_path).read_text())
    assert "generate_nonce" in ctx["ASP_Types"] and ctx["ASP_Comps"]["generate_nonce"] == "nonce_appr"
    from pybb.attestation.ledger import describe_package
    from pybb.attestation.ledger_runs import ledger_protocol
    d = describe_package(payload, ledger_protocol(proto).session)
    assert d.assurance == "signed+nonce" and d.nonce.slot == 1 and d.bid

    ledger = FileLedger(tmp_path / "ledger.jsonl")
    cfg = LedgerConfig(state_dir=str(tmp_path / "state"), appraiser_id="ap-prov", golden_root=str(golden),
                       evidence_repo="")
    report = verify_bundle(client, proto, golden, ledger=ledger)
    assert report.signature_ok and report.nonce_ok is True and len(report.anchored) == 4
    assert report.ledger_ok is False and not report  # not yet recorded
    keys = record_provision_bundles(ledger, golden, {proto.protocol_id: proto}, cfg)
    assert keys == [f"bundle/{d.bid}"]
    rec = ledger.get_record(keys[0])
    assert rec.role == "provision" and rec.assurance == "signed+nonce" and rec.nonce.asp == "generate_nonce" and rec.bid == d.bid
    report = verify_bundle(client, proto, golden, ledger=ledger)
    assert report and report.ledger_ok and report.ledger_key == keys[0]

    # a forced re-blessing is a distinct event: new nonce, new key, both verifiable
    outcome2 = make_provision_predicate(client, {proto.protocol_id: proto}, golden)(
        provision_request(proto.protocol_id, force_timestamp=True))
    assert outcome2.error == ""
    keys2 = record_provision_bundles(ledger, golden, {proto.protocol_id: proto}, cfg)
    assert len(keys2) == 1 and keys2[0] != keys[0]
    assert verify_bundle(client, proto, golden, ledger=ledger)


def test_combined_shape_against_the_real_cvm(tmp_path, config):
    """Plan M.2: one run yields the signed measurement P (lifted) and the live
    appraisal; P re-appraises under the ordinary term and binds to the same
    H; the B.6 audit of the whole package verifies the binding."""
    from pybb.attestation.ledger_runs import appraise_bundle, archiver, needs_keep

    proto = ProtocolDir.load(str(L1A))
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CvmSubprocessClient()
    archive = archiver(tmp_path / "evidence")
    r = attest(client, proto, ledger, config, archive=archive, shape="combined")
    assert r.error == "", r.error
    assert r.passed and [c.appr_asp for c in r.components] == ["goldenbytes_appr"] * 4
    m, a = ledger.get(r.bid), ledger.get(r.appraisal_bid)
    assert m.shape == "combined" and m.blob.derived_from == a.bid
    assert a.inputs[0].binding_hash == m.rawev_sha256 and m.assurance == a.assurance == "signed+nonce"

    later = appraise_bundle(client, proto, ledger, config, m.bid, archive=archive)
    assert later.error == "", later.error
    assert later and later.agrees_with_live is True
    assert ledger.get(later.appraisal_bid).inputs[0].binding_hash == m.rawev_sha256
    assert {c.appr_asp for c in later.components} == {"sig_appr", "nonce_appr", "goldenbytes_appr"}

    audit = appraise_bundle(client, proto, ledger, config, a.bid, archive=archive)
    assert audit.error == "", audit.error
    assert audit and audit.binding_ok is True and audit.signature_ok is True and audit.nonce_wellformed is True
    assert len(audit.components) == 13 and needs_keep(ledger, ledger.get(audit.appraisal_bid))
    assert [x.appraisal_kind for x in ledger.appraisals_of(m.bid)] == ["live", "audit"]
