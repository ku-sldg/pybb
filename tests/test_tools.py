"""
Tool registry + measure-then-use weaving (structural; no CVM needed).
End-to-end runs with provisioned tool goldens live in the example
integration tests.
"""

import json
from pathlib import Path

import pytest

from pybb.attestation.copland import iter_aspc_bodies
from pybb.attestation.tools import (
    build_tools_protocol_dir,
    cargo_verus_artifacts,
    lean_artifacts,
    register_tool,
    tool_targets,
    tools_for_term,
    weave_tool_measurements,
)

REPO = Path(__file__).parent.parent
LEAN_ROOT = REPO / "targets" / "temp-control-lean"

# "lean" resolves against a Lake package's pin, so it is registered
# per-example (drivers do the same)
register_tool("lean", lambda: lean_artifacts(LEAN_ROOT))

_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}


def _tier_config(asp_id="run_command_lean"):
    args = {asp_id: {"t1": {"exe_args": ["x"], "cwd": "/tmp"}}}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": asp_id, "ASP_TARG_ID": "t1",
                         "ASP_ARGS": args[asp_id]["t1"]}}},
        _APPR]}
    session = {"Session_Plc": "P0", "Session_Context": {
        "ASP_Types": {asp_id: {"FWD": {}, "ATTRS": []}},
        "ASP_Comps": {asp_id: f"{asp_id}_appr"}}}
    manifest = {"ASPS": [asp_id, f"{asp_id}_appr"], "ASP_FS_MAP": {}, "POLICY": []}
    return args, term, session, manifest


def test_lean_artifacts_resolve_from_the_package_pin():
    fps = lean_artifacts(LEAN_ROOT)
    assert len(fps) == 6
    for fp in fps:
        assert Path(fp).is_file(), fp
    # the pin in lean-toolchain resolves to the elan toolchain dir
    assert any("leanprover--lean4---v4.31.0" in fp for fp in fps)
    assert any(fp.endswith("libleanshared.dylib") for fp in fps)


def test_tool_targets_dedupe_mark_and_attribute():
    register_tool("stub_a", ["/tmp/stub_tool"], used_by=[])
    register_tool("stub_b", ["/tmp/stub_tool"], used_by=[])
    targets = tool_targets(["stub_a", "stub_b"])
    assert len(targets) == 1  # shared artifact measured once
    args = next(iter(targets.values()))
    assert args["measure_in_place"] is True
    assert args["metadata"] == "tool::stub_a"


def test_weave_measures_before_use_and_signs():
    args, term, session, manifest = _tier_config()
    w_args, w_term, w_session, w_manifest = weave_tool_measurements(
        args, term, session, manifest)

    # asp_args gained the lean tool targets
    assert set(w_args) == {"hashfile", "run_command_lean"}
    assert len(w_args["hashfile"]) == 6
    assert all(a["measure_in_place"] for a in w_args["hashfile"].values())

    # DFS order of events: every hashfile measurement precedes the use
    order = [b["ASP_ID"] for b in iter_aspc_bodies(w_term)]
    assert order.index("run_command_lean") == len(w_args["hashfile"])
    assert set(order[:len(w_args["hashfile"])]) == {"hashfile"}

    # the term is signed and appraised
    dumped = json.dumps(w_term)
    assert '"SIG"' in dumped and '"APPR"' in dumped

    # session and manifest know the new ASPs
    comps = w_session["Session_Context"]["ASP_Comps"]
    assert comps["hashfile"] == "goldenbytes_appr"
    assert comps["sig"] == "sig_appr"
    for asp in ("hashfile", "goldenbytes_appr", "sig", "sig_appr"):
        assert asp in w_manifest["ASPS"]
    # originals untouched
    assert "hashfile" not in session["Session_Context"]["ASP_Comps"]


def test_weave_noop_without_registered_tools():
    args, term, session, manifest = _tier_config(asp_id="readfile_range")
    out = weave_tool_measurements(args, term, session, manifest)
    assert out == (args, term, session, manifest)


def test_weave_refuses_double_weaving():
    args, term, session, manifest = _tier_config()
    w = weave_tool_measurements(args, term, session, manifest)
    with pytest.raises(ValueError, match="twice"):
        weave_tool_measurements(w[0], w[1], w[2], w[3])


def test_tools_for_term_maps_asps():
    assert tools_for_term({"run_command_cargo_verus": {}}) == ["cargo-verus"]
    assert tools_for_term({"hashfile": {}}) == []


def test_standalone_tools_protocol_dir(tmp_path):
    build_tools_protocol_dir(tmp_path / "p", "isl", ["cargo-verus"],
                             "verus toolchain identity")
    args = json.loads((tmp_path / "p" / "asp_args.json").read_text())
    assert len(args["hashfile"]) == len(cargo_verus_artifacts())
    term = json.loads((tmp_path / "p" / "term.json").read_text())
    ids = [b["ASP_ID"] for b in iter_aspc_bodies(term)]
    assert set(ids) == {"hashfile"}
    assert '"SIG"' in json.dumps(term)


# ── measure-in-place provisioning + live detection (real CVM) ─────────────────

from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

needs_cvm = pytest.mark.skipif(
    not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
    reason="requires local CVM binary and asp-libs binaries")


@needs_cvm
def test_stub_tool_provisioned_in_place_verified_and_tamper_detected(tmp_path):
    from pybb import BlackboardController
    from pybb.attestation import (CvmSubprocessClient, ProtocolDir,
                                  attestation_request,
                                  make_attestation_predicate,
                                  make_provision_predicate, request_provision,
                                  verify_bundle)

    stub = tmp_path / "stub_tool_bin"
    stub.write_bytes(b"#!/bin/sh\necho tool v1\n")
    register_tool("stub_jit", [str(stub)], used_by=[])
    proto_dir = tmp_path / "stub_tools"
    build_tools_protocol_dir(proto_dir, "stub", ["stub_jit"],
                             "stub toolchain for the measure-in-place test")
    golden_root = tmp_path / "golden"
    protocol = ProtocolDir.load(str(proto_dir))
    protocols = {"stub_tools": protocol}
    client = CvmSubprocessClient()

    # provision: live artifact hashed in place, bundle signed
    ctl = BlackboardController()
    ctl.register_predicate("provision",
                           make_provision_predicate(client, protocols, golden_root))
    request_provision(ctl.blackboard, "stub_tools")
    bb = ctl.run()
    assert not bb.get_escalate(), bb.get_escalate()
    targ, args = next(iter(protocol.asp_args["hashfile"].items()))
    assert args["golden_b64"]  # hash golden installed
    # the tool was NOT copied into the golden tree (measure-in-place)
    assert not any(golden_root.rglob(stub.name))

    # signed baseline verifies and anchors the tool hash
    report = verify_bundle(client, protocol, golden_root)
    assert report, report.problems
    assert report.anchored == [targ]

    # live attestation: clean tool passes; a swapped tool binary fails,
    # attributed to the tool target
    predicate = make_attestation_predicate(client, protocols)
    assert predicate(attestation_request("stub_tools")).passed
    stub.write_bytes(b"#!/bin/sh\necho EVIL v2\n")
    verdict = make_attestation_predicate(client, protocols)(
        attestation_request("stub_tools"))
    assert not verdict.passed
    assert {c.targ_id for c in verdict.failing()} == {targ}
    assert args["metadata"] == "tool::stub_jit"


@needs_cvm
def test_promotion_tool_gate_refuses_codegen_on_drift(tmp_path):
    """The just-before-use gate: the codegen toolchain is measured at
    promotion time; drift from the blessed hashes refuses codegen — and
    codegen_fn is never invoked."""
    from pybb import BlackboardController
    from pybb.attestation import (CvmSubprocessClient, ProtocolDir,
                                  make_promotion_predicate,
                                  make_provision_predicate, request_provision)
    from pybb.attestation.promotion import promotion_request
    from pybb.attestation.tools import make_tool_gate

    stub = tmp_path / "stub_codegen_tool"
    stub.write_bytes(b"codegen v1")
    register_tool("stub_gate", [str(stub)], used_by=[])
    proto_dir = tmp_path / "gate_tools"
    build_tools_protocol_dir(proto_dir, "stub", ["stub_gate"], "gate stub")
    protocol = ProtocolDir.load(str(proto_dir))
    client = CvmSubprocessClient()

    ctl = BlackboardController()
    ctl.register_predicate("provision", make_provision_predicate(
        client, {"gate_tools": protocol}, tmp_path / "golden"))
    request_provision(ctl.blackboard, "gate_tools")
    assert not ctl.run().get_escalate()

    ran = []

    def fake_codegen():
        ran.append(1)
        return "ran"

    def predicate():
        return make_promotion_predicate(
            {}, tmp_path / "golden", targets_fn=lambda: {},
            codegen_fn=fake_codegen,
            tool_gate=make_tool_gate(client, protocol))

    # clean toolchain: the gate admits codegen
    predicate()(promotion_request("m"))
    assert ran == [1]

    # drifted toolchain: promotion refused, codegen never invoked
    stub.write_bytes(b"codegen v2 EVIL")
    out = predicate()(promotion_request("m"))
    assert "toolchain gate refused codegen" in out.error
    assert "stub" in out.error  # names the drifted artifact's target
    assert ran == [1]
