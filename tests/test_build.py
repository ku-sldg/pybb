"""
Build-event protocols: the build as a signed Copland term whose evidence
order witnesses tools -> inputs -> build -> outputs, provisioned at
blessing time, with output goldens cross-installed into the runtime
protocol that enforces them.

Structural tests need nothing; the end-to-end test drives a stub build
(`lake env cp in out` — a real command through the measured lake wrapper)
through the real CVM and is gated like the other lean-toolchain tests.
"""

import json
import os
from pathlib import Path

import pytest

from pybb.attestation.build import (
    build_output_targets,
    install_build_outputs,
    write_build_protocol_dir,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.copland import iter_aspc_bodies
from pybb.attestation.tools import lean_artifacts, register_tool

REPO = Path(__file__).parent.parent
LEAN_ROOT = REPO / "targets" / "temp-control-lean"
LAKE_WRAPPER = Path.home() / "Claude_workspace/bin/lake"

register_tool("lean", lambda: lean_artifacts(LEAN_ROOT))

needs_cvm = pytest.mark.skipif(
    not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
    reason="requires local CVM binary and asp-libs binaries")
needs_lean = pytest.mark.skipif(
    os.environ.get("RUN_LEAN") != "1" or not LAKE_WRAPPER.is_file(),
    reason="set RUN_LEAN=1 (and install the workspace lake wrapper)")


def test_build_term_witnesses_tools_inputs_build_outputs(tmp_path):
    (tmp_path / "src").write_text("source")
    write_build_protocol_dir(
        tmp_path / "b", "x", ["lean"],
        [str(tmp_path / "src")], [str(tmp_path / "out")],
        "run_command_lean", "run_command_lean_appr",
        {"exe_args": ["build"], "cwd": str(LEAN_ROOT)}, "structural test")

    term = json.loads((tmp_path / "b" / "term.json").read_text())
    order = [b["ASP_ID"] for b in iter_aspc_bodies(term)]
    # DFS event order: 6 tool hashes, 1 input hash, the build, 1 output hash
    assert order == ["hashfile"] * 7 + ["run_command_lean", "hashfile"]
    assert '"SIG"' in json.dumps(term) and '"APPR"' in json.dumps(term)

    args = json.loads((tmp_path / "b" / "asp_args.json").read_text())
    roles = [a.get("metadata", "") for a in args["hashfile"].values()]
    assert sum(1 for r in roles if r.startswith("tool::lean")) == 6
    assert sum(1 for r in roles if r.startswith("build_in::")) == 1
    assert sum(1 for r in roles if r.startswith("build_out::")) == 1
    assert all(a["measure_in_place"] for a in args["hashfile"].values())

    session = json.loads((tmp_path / "b" / "session.json").read_text())
    comps = session["Session_Context"]["ASP_Comps"]
    assert comps["run_command_lean"] == "run_command_lean_appr"
    assert comps["hashfile"] == "goldenbytes_appr"
    assert comps["sig"] == "sig_appr"


@needs_cvm
@needs_lean
def test_stub_build_provisions_signs_cross_installs_and_links(tmp_path):
    """End to end: the output does not exist before provisioning; the build
    event produces it; its hash golden is extracted from the SIGNED build
    bundle, cross-installed into the runtime protocol, and the bundle's
    cross-links verify — inputs against the source baseline, outputs
    against the runtime enforcer."""
    from pybb import BlackboardController
    from pybb.attestation import (CvmSubprocessClient, ProtocolDir,
                                  attestation_request,
                                  make_attestation_predicate,
                                  make_provision_predicate, request_provision,
                                  verify_bundle)

    src = tmp_path / "artifact_src"
    src.write_bytes(b"the built payload v1")
    out = tmp_path / "artifact_bin"
    assert not out.exists()  # the build must create it

    write_build_protocol_dir(
        tmp_path / "stub_build", "stub", [],
        [str(src)], [str(out)],
        "run_command_lean", "run_command_lean_appr",
        {"exe_args": ["env", "cp", str(src), str(out)], "cwd": str(LEAN_ROOT)},
        "stub build: cp through the measured lake wrapper")
    build = ProtocolDir.load(str(tmp_path / "stub_build"))

    def hashfile_protocol(name, targ, filepath):
        d = tmp_path / name
        d.mkdir()
        for f in ("session.json", "manifest.json"):
            (d / f).write_text((tmp_path / "stub_build" / f).read_text())
        (d / "asp_args.json").write_text(json.dumps({"hashfile": {
            targ: {"filepath": str(filepath), "env_var": "",
                   "measure_in_place": True}}}, indent=2))
        (d / "term.json").write_text(json.dumps(
            {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
                {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
                    {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
                        "ASP_CONSTRUCTOR": "ASPC",
                        "ASP_BODY": {"ASP_ID": "hashfile",
                                     "ASP_TARG_ID": targ}}},
                    {"TERM_CONSTRUCTOR": "asp",
                     "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}]},
                {"TERM_CONSTRUCTOR": "asp",
                 "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}]}))
        return ProtocolDir.load(str(d))

    runtime = hashfile_protocol("stub_runtime", "stub_bin_targ", out)
    srcp = hashfile_protocol("stub_src", "stub_src_targ", src)
    client = CvmSubprocessClient()
    golden_root = tmp_path / "golden"

    def provision(pids, protos):
        ctl = BlackboardController()
        ctl.register_predicate("provision", make_provision_predicate(
            client, protos, golden_root))
        for pid in pids:
            request_provision(ctl.blackboard, pid)
        bb = ctl.run()
        assert not bb.get_escalate(), bb.get_escalate()

    # bless the source baseline, then run the build event
    provision(["stub_src"], {"stub_src": srcp})
    provision(["stub_build"], {"stub_build": build})

    # the build ran during provisioning and produced the output
    assert out.read_bytes() == src.read_bytes()
    outputs = build_output_targets(build)
    (out_targ, out_args), = outputs.items()
    assert out_args["golden_b64"]

    # cross-install: the runtime protocol's binary golden IS the build's
    installed = install_build_outputs(build, {"stub_runtime": runtime})
    assert installed == ["stub_runtime:stub_bin_targ"]
    assert runtime.asp_args["hashfile"]["stub_bin_targ"]["golden_b64"] == \
        out_args["golden_b64"]

    # cross-link verification: inputs anchored to the source baseline,
    # outputs to the runtime enforcer, under the build bundle's signature
    protocols = {"stub_build": build, "stub_runtime": runtime,
                 "stub_src": srcp}
    report = verify_bundle(client, build, golden_root,
                           anchor_protocols=protocols)
    assert report, report.problems
    in_targ = next(targ for targ, a in build.asp_args["hashfile"].items()
                   if a["metadata"].startswith("build_in"))
    assert report.linked[in_targ] == "stub_src"
    assert report.linked[out_targ] == "stub_runtime"

    # negative: output not enforced by any runtime protocol
    r = verify_bundle(client, build, golden_root,
                      anchor_protocols={"stub_build": build, "stub_src": srcp})
    assert not r
    assert any("not enforced by any runtime protocol" in p for p in r.problems)

    # negative: the runtime enforcer's golden edited away from the build's
    saved = runtime.asp_args["hashfile"]["stub_bin_targ"]["golden_b64"]
    runtime.asp_args["hashfile"]["stub_bin_targ"]["golden_b64"] = "Zm9yZ2Vk"
    r = verify_bundle(client, build, golden_root, anchor_protocols=protocols)
    assert not r
    assert any("disagree" in p and "stub_runtime" in p for p in r.problems)
    runtime.asp_args["hashfile"]["stub_bin_targ"]["golden_b64"] = saved

    # negative: sources re-blessed AFTER the build — the bundle's input
    # evidence no longer matches the source baseline (stale build)
    src.write_bytes(b"the built payload v2")
    provision(["stub_src"], {"stub_src": srcp})
    r = verify_bundle(client, build, golden_root, anchor_protocols=protocols)
    assert not r
    assert any(in_targ in p and "disagree" in p for p in r.problems)

    # a swapped artifact fails live attestation against the build-anchored
    # golden, attributed
    out.write_bytes(b"EVIL replacement binary")
    verdict = make_attestation_predicate(client, {"stub_runtime": runtime})(
        attestation_request("stub_runtime"))
    assert not verdict.passed
    assert "stub_bin_targ" in {c.targ_id for c in verdict.failing()}
