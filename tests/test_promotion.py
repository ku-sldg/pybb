"""
Promotion predicate behavior (no CVM needed): pipeline stages, target
regeneration, golden movement, opt-in validation gate, partition write
order, and error paths.
"""

import base64
import json
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    ProtocolDir,
    make_promotion_predicate,
    make_provision_predicate,
    promotion_request,
    request_promotion,
)
from pybb.attestation.client import AttestationClient
from pybb.attestation.snapshot import mirror_path


def _model_tree(tmp_path):
    """A tiny model workspace: one AADL file with one contract."""
    aadl = tmp_path / "model" / "Sys.aadl"
    aadl.parent.mkdir(parents=True)
    aadl.write_text(
        "package Sys\n"
        "annex GUMBO {**\n"
        "  inv Inv1:\n"
        "    x > 0;\n"
        "**};\n"
    )
    comp = tmp_path / "model" / "Comp.scala"
    comp.write_text("// BEGIN STATE VARS\nvar x = 0\n// END STATE VARS\n")
    return aadl, comp


def _spec(aadl, comp):
    return {
        "hash_files": [str(aadl)],
        "aadl": [(str(aadl), "sys_aadl")],
        "gumbox": [],
        "components": [(str(comp), "c")],
    }


def _protocols(tmp_path, aadl, comp):
    protocols = {}
    for pid in ("gumbo_l1a", "gumbo_l1b", "gumbo_l2"):
        proto_dir = tmp_path / "protos" / pid
        proto_dir.mkdir(parents=True)
        protocols[pid] = ProtocolDir(
            protocol_id=pid, path=str(proto_dir), term={},
            session={"Session_Plc": "P0"}, manifest={"ASPS": []},
            asp_args={"hashfile": {"t": {"filepath": str(aadl)}}},
        )
    return protocols


def test_promotion_regenerates_targets_and_moves_gold(tmp_path):
    aadl, comp = _model_tree(tmp_path)
    protocols = _protocols(tmp_path, aadl, comp)
    golden_root = tmp_path / "golden"
    calls = []
    predicate = make_promotion_predicate(
        protocols, golden_root, _spec(aadl, comp),
        codegen_fn=lambda: calls.append("codegen") or "ran",
    )

    outcome = predicate(promotion_request("sys"))

    assert outcome and calls == ["codegen"]
    # targets regenerated from content: 1 hash, 1 block, 1 contract range
    assert outcome.targets == {"gumbo_l1a": 1, "gumbo_l1b": 1, "gumbo_l2": 1}
    l2_args = protocols["gumbo_l2"].asp_args["readfile_range"]
    assert l2_args["sys_aadl_3_4_targ"]["start_index"] == 3
    assert "golden_b64" not in l2_args["sys_aadl_3_4_targ"]  # provisioning fills
    # protocol dirs written through
    on_disk = json.loads(
        (Path(protocols["gumbo_l2"].path) / "asp_args.json").read_text())
    assert "sys_aadl_3_4_targ" in on_disk["readfile_range"]
    # gold moved: the watched files now have golden copies
    assert outcome.captured >= 1
    assert mirror_path(golden_root, aadl).read_text() == aadl.read_text()


def test_promotion_tracks_shifted_contract(tmp_path):
    aadl, comp = _model_tree(tmp_path)
    aadl.write_text("-- header comment\n" + aadl.read_text())  # shift by one
    protocols = _protocols(tmp_path, aadl, comp)
    predicate = make_promotion_predicate(
        protocols, tmp_path / "golden", _spec(aadl, comp),
        codegen_fn=lambda: "ran")

    outcome = predicate(promotion_request("sys"))

    assert outcome
    assert "sys_aadl_4_5_targ" in protocols["gumbo_l2"].asp_args["readfile_range"]


def test_codegen_failure_stops_the_pipeline(tmp_path):
    aadl, comp = _model_tree(tmp_path)
    protocols = _protocols(tmp_path, aadl, comp)

    def broken():
        raise RuntimeError("phantom exploded")

    predicate = make_promotion_predicate(
        protocols, tmp_path / "golden", _spec(aadl, comp), codegen_fn=broken)
    outcome = predicate(promotion_request("sys"))

    assert not outcome and "phantom exploded" in outcome.error
    assert not (tmp_path / "golden").exists()  # gold never moved
    assert "readfile_range" not in protocols["gumbo_l2"].asp_args  # targets untouched


class _GateClient(AttestationClient):
    def __init__(self, ok: bool):
        raw = [base64.b64encode(b"" if ok else b"tests failed").decode()]
        et = {"EvidenceT_CONSTRUCTOR": "asp_evt", "EvidenceT_BODY": [
            "P0", {"ASP_ID": "x_appr", "ASP_ARGS": {}},
            {"EvidenceT_CONSTRUCTOR": "mt_evt"}]}
        self.response = {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True,
                         "PAYLOAD": [{"RawEv": raw}, et]}

    def run_protocol(self, protocol):
        return self.response


def test_validation_gate_blocks_promotion(tmp_path):
    aadl, comp = _model_tree(tmp_path)
    protocols = _protocols(tmp_path, aadl, comp)
    protocols["val"] = protocols["gumbo_l1a"].model_copy()
    predicate = make_promotion_predicate(
        protocols, tmp_path / "golden", _spec(aadl, comp),
        codegen_fn=lambda: "ran", client=_GateClient(ok=False),
        validate_with="val")

    outcome = predicate(promotion_request("sys"))

    assert not outcome and outcome.validated is False
    assert "does not verify" in outcome.error
    assert not (tmp_path / "golden").exists()


def test_validation_gate_passes_when_project_verifies(tmp_path):
    aadl, comp = _model_tree(tmp_path)
    protocols = _protocols(tmp_path, aadl, comp)
    protocols["val"] = protocols["gumbo_l1a"].model_copy()
    predicate = make_promotion_predicate(
        protocols, tmp_path / "golden", _spec(aadl, comp),
        codegen_fn=lambda: "ran", client=_GateClient(ok=True),
        validate_with="val")

    outcome = predicate(promotion_request("sys"))
    assert outcome and outcome.validated is True


def test_promotion_runs_before_provisioning_in_partition_order(tmp_path):
    aadl, comp = _model_tree(tmp_path)
    protocols = _protocols(tmp_path, aadl, comp)
    golden_root = tmp_path / "golden"
    order = []

    ctl = BlackboardController()
    ctl.register_predicate("promotion", lambda m: order.append("promote") or
                           {"ok": True})
    ctl.register_predicate("provision", lambda m: order.append(f"provision:{m['protocol']}") or
                           {"ok": True})
    request_promotion(ctl.blackboard, "sys", ["gumbo_l1a", "gumbo_l2"])
    ctl.run()

    assert order[:3] == ["promote", "provision:gumbo_l1a", "provision:gumbo_l2"]
    assert "promote:sys" in ctl.blackboard.provision  # rests as the record
