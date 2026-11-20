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


def test_blessing_the_real_stack_and_runs_reference_it(tmp_path, config):
    """B.8 default cadence: provision attestation_tools once (the CVM hashes
    the live CVM, summarizer, ASPs and key, then signs), record the bundle,
    and every later run carries that bundle's hash as its tooling ref."""
    from pybb.attestation.client import CvmConfig
    from pybb.attestation.ledger import ToolingRef
    from pybb.attestation.ledger_tooling import (
        TOOLING_PROTOCOL_ID, bless_tools, build_attestation_tools_protocol, tooling_ref_for)

    proto = ProtocolDir.load(str(L1A))
    cfg = config.model_copy(update={"golden_root": str(tmp_path / "golden")})
    tp = build_attestation_tools_protocol(tmp_path / TOOLING_PROTOCOL_ID, CvmConfig(),
                                          {proto.protocol_id: proto}, cfg)
    assert len(tp.asp_args["hashfile"]) >= 6  # cvm, summarizer, key, several ASPs
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CvmSubprocessClient()

    b = bless_tools(client, tp, cfg.golden_root, ledger, cfg)
    assert b.error == "", b.error
    assert Path(b.bundle_path).is_file() and b.ledger_key and b.ledger_key.startswith("bundle/")
    assert len(b.provisioned) == len(tp.asp_args["hashfile"])
    rec = ledger.get_record(b.ledger_key)
    # provisioning runs carry generate_nonce (plan point 4): the blessing is a
    # signed+nonce package keyed by its nonce id
    assert rec.protocol_id == TOOLING_PROTOCOL_ID and rec.assurance == "signed+nonce" and rec.signature.present
    assert rec.role == "provision" and rec.bid and b.ledger_key == f"bundle/{rec.bid}"
    # idempotent: unchanged tools -> same bundle, no second record
    b2 = bless_tools(client, tp, cfg.golden_root, ledger, cfg)
    assert b2.bundle_sha256 == b.bundle_sha256 and len(ledger.bundles(role="provision")) == 1

    protocols = {proto.protocol_id: proto, tp.protocol_id: tp}
    assert tooling_ref_for(ledger, cfg, protocols) == ToolingRef(kind="bundle", ref=b.bundle_sha256)
    predicate = make_attestation_predicate(client, protocols, archive_dir=tmp_path / "evidence",
                                           ledger=ledger, ledger_config=cfg)
    v = predicate({"protocol": proto.protocol_id})
    assert v.error == "", v.error
    m = ledger.get(v.bid)
    assert m.tooling == ToolingRef(kind="bundle", ref=b.bundle_sha256)
    assert ledger.appraisals_of(v.bid)[0].tooling == m.tooling

    # the blessing bundle itself is re-verifiable through verify_bundle's APPR-only path
    from pybb.attestation import verify_bundle
    report = verify_bundle(client, tp, Path(cfg.golden_root))
    assert report, report.problems


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
