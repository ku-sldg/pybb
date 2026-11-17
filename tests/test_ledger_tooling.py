"""Tooling identity (plan B.8): the attestation_tools protocol, the blessing
as a bundle record, and the tooling reference on run records.

Unit tests use a fake stack (temp files standing in for the CVM, the
summarizer, ASP binaries and the key) and the canned packages; the
real-CVM blessing lives in test_integration_ledger.py."""

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pybb.attestation import FileLedger, ProtocolDir, make_attestation_predicate
from pybb.attestation.ledger import LedgerConfig, ToolingConfig, ToolingRef, sha256_hex
from pybb.attestation.ledger_tooling import (
    TOOLING_PROTOCOL_ID,
    ToolingResolver,
    asp_names_in_use,
    attestation_stack_artifacts,
    build_attestation_tools_protocol,
    tooling_ref_for,
)

from test_ledger_runs import L1A, CannedClient


@pytest.fixture
def fake_stack(tmp_path):
    asp_bin = tmp_path / "asps"
    asp_bin.mkdir()
    for name in ("hashfile", "sig", "sig_appr", "goldenbytes_appr", "generate_nonce", "nonce_appr",
                 "hashevidence", "magic_appr"):
        (asp_bin / name).write_bytes(b"binary " + name.encode())
    cvm = tmp_path / "cvm"; cvm.write_bytes(b"cvm binary")
    summ = tmp_path / "copland_evidence_tools"; summ.write_bytes(b"summarizer")
    key = tmp_path / "pub.pem"; key.write_bytes(b"-----BEGIN PUBLIC KEY-----\nabc\n")
    return SimpleNamespace(cvm_binary=str(cvm), asp_bin=str(asp_bin), summarizer=str(summ), key=str(key))


@pytest.fixture
def config(tmp_path, fake_stack):
    return LedgerConfig(state_dir=str(tmp_path / "state"), appraiser_id="ap-tool",
                        verify_key_path=fake_stack.key, golden_root=str(tmp_path / "golden"))


def test_stack_artifacts_cover_cvm_summarizer_asps_and_key(fake_stack):
    proto = ProtocolDir.load(str(L1A))
    names = asp_names_in_use({proto.protocol_id: proto})
    assert {"hashfile", "sig", "sig_appr", "goldenbytes_appr", "generate_nonce", "nonce_appr",
            "hashevidence", "magic_appr"} <= set(names)
    arts = attestation_stack_artifacts(fake_stack.cvm_binary, fake_stack.asp_bin, names,
                                       fake_stack.summarizer, fake_stack.key)
    assert arts[0].endswith("/cvm") and arts[1].endswith("copland_evidence_tools") and arts[2].endswith("pub.pem")
    assert len(arts) == 3 + 8  # existing ASPs only; missing ones are skipped silently


def test_build_protocol_dir_is_a_measure_in_place_tools_protocol(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    tp = build_attestation_tools_protocol(tmp_path / TOOLING_PROTOCOL_ID, fake_stack,
                                          {proto.protocol_id: proto}, config, fake_stack.summarizer)
    assert tp.protocol_id == TOOLING_PROTOCOL_ID
    targets = tp.asp_args["hashfile"]
    assert all(a["measure_in_place"] and a["metadata"] == "tool::attestation_stack" for a in targets.values())
    paths = {a["filepath"] for a in targets.values()}
    assert fake_stack.cvm_binary in paths and fake_stack.key in paths and f"{fake_stack.asp_bin}/sig_appr" in paths
    assert tp.manifest["ASPS"] == ["hashfile", "goldenbytes_appr", "sig", "sig_appr"]
    assert (tmp_path / TOOLING_PROTOCOL_ID / "meta.json").is_file()


def _fake_blessing(golden_root: Path, tp: ProtocolDir) -> Path:
    """A plausible blessing bundle on disk: signed hashfile package over the
    tooling targets (the CVM would produce this shape)."""
    raws = [base64.b64encode(b"\x01" * 256).decode()]
    et = {"EvidenceT_CONSTRUCTOR": "mt_evt"}
    for targ, args in tp.asp_args["hashfile"].items():
        raws.append(base64.b64encode(sha256_hex(args["filepath"].encode()).encode()[:32]).decode())
        et = {"EvidenceT_CONSTRUCTOR": "asp_evt", "EvidenceT_BODY": ["P0", {"ASP_ID": "hashfile", "ASP_ARGS": dict(args)}, et]}
    et = {"EvidenceT_CONSTRUCTOR": "asp_evt", "EvidenceT_BODY": ["P0", {"ASP_ID": "sig", "ASP_ARGS": {}}, et]}
    bundle = golden_root / "_bundles" / tp.protocol_id / "provision_bundle.json"
    bundle.parent.mkdir(parents=True)
    bundle.write_text(json.dumps([[{"RawEv": raws}, et], tp.session["Session_Context"]]))
    return bundle


def test_tooling_ref_records_the_blessing_bundle_once(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    tp = build_attestation_tools_protocol(tmp_path / TOOLING_PROTOCOL_ID, fake_stack,
                                          {proto.protocol_id: proto}, config, fake_stack.summarizer)
    protocols = {proto.protocol_id: proto, tp.protocol_id: tp}
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    assert tooling_ref_for(ledger, config, protocols) is None  # no blessing yet
    bundle = _fake_blessing(Path(config.golden_root), tp)
    ref = tooling_ref_for(ledger, config, protocols)
    assert ref == ToolingRef(kind="bundle", ref=sha256_hex(bundle.read_bytes()))
    recs = list(ledger.records(kind="bundle"))
    assert len(recs) == 1 and recs[0].protocol_id == TOOLING_PROTOCOL_ID and recs[0].assurance == "signed"
    assert tooling_ref_for(ledger, config, protocols) == ref and len(list(ledger.records(kind="bundle"))) == 1
    # tooling tracking off
    off = config.model_copy(update={"tooling": ToolingConfig(protocol_id=None)})
    assert tooling_ref_for(ledger, off, protocols) is None


def test_runs_carry_the_blessing_reference_by_default(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    tp = build_attestation_tools_protocol(tmp_path / TOOLING_PROTOCOL_ID, fake_stack,
                                          {proto.protocol_id: proto}, config, fake_stack.summarizer)
    bundle = _fake_blessing(Path(config.golden_root), tp)
    protocols = {proto.protocol_id: proto, tp.protocol_id: tp}
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    client = CannedClient()
    predicate = make_attestation_predicate(client, protocols, archive_dir=tmp_path / "evidence",
                                           ledger=ledger, ledger_config=config)
    v = predicate({"protocol": proto.protocol_id})
    assert v.error == "", v.error
    run = ledger.get(v.nonce_id)
    expect = ToolingRef(kind="bundle", ref=sha256_hex(bundle.read_bytes()))
    assert run.evidence.tooling == expect and run.appraisals[0].tooling == expect
    assert len(client.requests) == 2  # at_provisioning: no tooling run happened


def test_every_run_cadence_runs_the_tooling_protocol_first(tmp_path, fake_stack, config):
    proto = ProtocolDir.load(str(L1A))
    tp = build_attestation_tools_protocol(tmp_path / TOOLING_PROTOCOL_ID, fake_stack,
                                          {proto.protocol_id: proto}, config, fake_stack.summarizer)
    _fake_blessing(Path(config.golden_root), tp)
    protocols = {proto.protocol_id: proto, tp.protocol_id: tp}
    cfg = config.model_copy(update={"tooling": ToolingConfig(measure="every_run")})
    ledger = FileLedger(tmp_path / "ledger.jsonl")

    class Client(CannedClient):
        """Distinct nonces per call so the tooling run and the l1a run never collide."""
        n = 0

        def run_protocol(self, protocol):
            Client.n += 1
            resp = json.loads(json.dumps(super().run_protocol(protocol)))
            resp["PAYLOAD"][0]["RawEv"][1] = base64.b64encode(bytes([Client.n]) * 32).decode()
            return resp

    resolver = ToolingResolver(Client(), protocols, ledger, cfg)
    ref = resolver.ref(proto.protocol_id)
    assert ref is not None and ref.kind == "run"
    tooling_run = ledger.get(ref.ref)
    assert tooling_run.evidence.protocol_id == TOOLING_PROTOCOL_ID
    assert tooling_run.evidence.tooling.kind == "bundle"  # the tooling run itself references the blessing
    # every_episode: the second ask reuses the first run
    cfg2 = cfg.model_copy(update={"tooling": ToolingConfig(measure="every_episode")})
    r2 = ToolingResolver(Client(), protocols, ledger, cfg2)
    a, b = r2.ref(proto.protocol_id), r2.ref(proto.protocol_id)
    assert a == b and a.kind == "run" and a.ref != ref.ref
