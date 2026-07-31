"""
Attestation-driven blackboard demo for the Lean pipeline: the temp-control
model ported to Lean 4 (targets/temp-control-lean) — a specification
(TempControl/Spec.lean, the GUMBO compute contracts as theorems) over a
proof-free implementation (TempControl/Impl.lean) that the executable
(Main.lean) is built from. Measurement targets derive from a syntax scan
of the package (derive_targets_from_lean); l2 slices are named by
declaration, so attribution names the tampered theorem.

Protocols:

    lean_l1a   whole-file hashes: every .lean source + lakefile.toml +
               lean-toolchain (build config and toolchain pin are inside
               the trust boundary)
    lean_l2    readfile_range per top-level declaration (attribution)
    lean_check `lake lean TempControl/Spec.lean -- --json`: every theorem
               must still PROVE (fails on error diagnostics and hasSorry —
               a sorry exits 0, so exit codes alone would bless it)
    lean_exec  hash-then-run of the PINNED built binary: its hash must
               match the build-anchored golden, then it is executed
               directly (lake env <binary>, never rebuilt) per GUMBO case;
               stdout must equal the expected command. Main imports only
               TempControl.Impl, so provability and behavior stay
               independent measurements.
    lean_build the build event, run at provisioning: toolchain -> input
               sources -> lake build -> output binary, one signature. The
               exec tier's binary golden is born from this bundle; baseline
               verification cross-links inputs to lean_l1a, tools to the
               blessed toolchain, and the output to lean_exec.

Three independent trust questions, three always-run entries:

    lean:files     eval lean_l1a: fail -> lean_l2 refines (which
                   declaration) -> [--repair] WholeFileRestoreKS
    lean:proofs    [--validate] eval lean_check: fail escalates directly
    lean:behavior  [--validate] eval lean_exec: fail escalates directly

Usage:
    python examples/lean_attestation.py [--provision] [--tamper]
        [--tamper-semantic] [--repair] [--validate]

--provision  (re)generate lean_l1a/lean_l2 protocol dirs from the syntax
             scan, capture golden, and provision via the blackboard
             (lean_check/lean_exec are static AM-owned config)
--tamper     corrupt a line inside a theorem slice; detection/attribution
             (and --repair)
--tamper-semantic  flip computeFanCmd's hot branch (.On -> .Off) in the
             implementation AND re-provision over the tampered tree —
             laundering that now includes RE-RUNNING THE BUILD EVENT, so
             the flipped binary is consistently re-anchored and every
             baseline verifies. Refuted twice anyway: the proofs no longer
             check (lean_check), and the rebuilt binary fails the hot
             vector (lean_exec's expected outputs are AM config, not
             provisioned goldens — laundering cannot reach them).
             Implies --validate; restores and re-provisions clean after.
"""

import argparse
import json
import shutil
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    make_attestation_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    readiness_request,
    request_provision,
    trust_summary,
)
from pybb.attestation.build import install_build_outputs, write_build_protocol_dir
from pybb.attestation.copland import with_asp_targids
from pybb.attestation.props import write_props_protocol_dir
from pybb.attestation.targetmap import build_term, derive_targets_from_lean
from pybb.attestation.tools import (
    lean_artifacts,
    register_tool,
    weave_tool_measurements,
)

REPO = Path(__file__).parent.parent
LEAN_ROOT = REPO / "targets" / "temp-control-lean"
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
EVIDENCE_DIR = REPO / "evidence"  # per-episode archived responses (gzipped)
PROTOCOL_IDS = ("lean_l1a", "lean_l2")
PROPS_ID = "lean_props"
TIER_IDS = ("lean_check", "lean_exec")
TEMPLATES = {"lean_l1a": "gumbo_l1a", "lean_l2": "gumbo_l2"}
SPEC_FILE = LEAN_ROOT / "TempControl" / "Spec.lean"

# Just-in-time tool measurement: the lean toolchain (wrapper -> elan shim
# -> pinned binaries -> elaborator library) is hashed IN THE SAME TERM as
# each tier's tool invocation, sequenced before the use. Cadence is the
# optimization parameter (~123 ms per woven term): "per_use" (default),
# "per_episode" (standalone tools entry), "provision_only" (blessed
# hashes, no live re-measurement).
TOOL_CADENCE = "per_use"
register_tool("lean", lambda: lean_artifacts(LEAN_ROOT))

# The built executable is a measured artifact: lean_build runs the build
# as a signed Copland term at provisioning (tools -> inputs -> lake build
# -> output binary, one signature), and the binary golden the exec tier
# enforces is cross-installed from that bundle. Episodes never rebuild:
# lean_exec hashes the PINNED artifact and executes it directly.
BUILD_ID = "lean_build"
BIN = LEAN_ROOT / ".lake" / "build" / "bin" / "temp-control"

_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}
TIER_SESSION = {
    "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
    "Session_Context": {
        "ASP_Types": {
            "run_command_lean": {
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
            "run_command_lean_appr": {
                # EXTEND: the appraiser retains the evidence it judged, so
                # the tool's output survives into the episode response and
                # the verified appraisal summary lifts it per entry
                # (ComponentResult.measured_b64) — the per-contract join
                # material
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
        },
        "ASP_Comps": {"run_command_lean": "run_command_lean_appr"},
    },
}
TIER_MANIFEST = {"ASPS": ["run_command_lean", "run_command_lean_appr"],
                 "ASP_FS_MAP": {}, "POLICY": []}
TIER_TARGETS = {
    "lean_check": {
        "lean_spec_check_targ": {
            "exe_args": ["lean", "TempControl/Spec.lean", "--", "--json"],
            "cwd": str(LEAN_ROOT)},
    },
    "lean_exec": {
        "lean_exec_hot_targ": {
            "exe_args": ["env", str(BIN), "101", "70", "90", "Off"],
            "cwd": str(LEAN_ROOT), "expected": "fanCmd=On"},
        "lean_exec_cold_targ": {
            "exe_args": ["env", str(BIN), "60", "70", "90", "On"],
            "cwd": str(LEAN_ROOT), "expected": "fanCmd=Off"},
        "lean_exec_hold_targ": {
            "exe_args": ["env", str(BIN), "80", "70", "90", "On"],
            "cwd": str(LEAN_ROOT), "expected": "fanCmd=On"},
    },
}
TIER_META = {
    "lean_check": {
        "name": "Lean Proof Check (semantic tier)",
        "description": "Runs `lake lean TempControl/Spec.lean -- --json`: "
                       "every theorem must still PROVE. The appraiser fails "
                       "on any error diagnostic or hasSorry warning. The "
                       "lean toolchain is hashed in the same term, before "
                       "the invocation (measure-then-use).",
    },
    "lean_exec": {
        "name": "Lean Executable Behavior (exec tier)",
        "description": "Hashes the PINNED built binary against its "
                       "build-anchored golden, then executes it directly "
                       "(lake env <binary>, no rebuild) on one input vector "
                       "per GUMBO case; the appraiser compares stdout to the "
                       "expected command. The lean toolchain is hashed in "
                       "the same term, before the invocations.",
    },
}


def _tier_term(asp_id: str, targets: dict) -> dict:
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": asp_id, "ASP_TARG_ID": targ,
                         "ASP_ARGS": args}}}
        for targ, args in targets.items()
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    return {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [acc, _APPR]}


def build_tier_protocol_dirs() -> None:
    """(Re)generate the semantic-tier dirs from the base config, with tool
    measurements woven in per TOOL_CADENCE. lean_exec additionally hashes
    the pinned binary against its build-anchored golden BEFORE running it
    (hash-then-run, same term)."""
    for pid, targets in TIER_TARGETS.items():
        targets = with_asp_targids(targets)
        asp_args = {"run_command_lean": dict(targets)}
        term = _tier_term("run_command_lean", targets)
        if pid == "lean_exec":
            bin_targs = with_asp_targids({"lean_bin_temp_control_targ": {
                "filepath": str(BIN), "env_var": "",
                "measure_in_place": True,
                "metadata": "binary::temp-control"}})
            asp_args = {"hashfile": bin_targs, **asp_args}
            body = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
                {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
                    "ASP_CONSTRUCTOR": "ASPC",
                    "ASP_BODY": {"ASP_ID": "hashfile",
                                 "ASP_TARG_ID": "lean_bin_temp_control_targ"}}},
                term["TERM_BODY"][0]]}
            term = {"TERM_CONSTRUCTOR": "lseq",
                    "TERM_BODY": [body, _APPR]}
        session, manifest = TIER_SESSION, TIER_MANIFEST
        if TOOL_CADENCE == "per_use":
            asp_args, term, session, manifest = weave_tool_measurements(
                asp_args, term, session, manifest)
        d = FIXTURES / pid
        d.mkdir(exist_ok=True)
        (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
        (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
        (d / "meta.json").write_text(json.dumps(TIER_META[pid], indent=2) + "\n")
        n_tools = len(asp_args.get("hashfile", {}))
        print(f"  {pid}: {len(targets)} targets"
              + (f" + {n_tools} woven tool measurements" if n_tools else ""))


def build_protocol_dirs() -> dict:
    """(Re)generate the measurement protocol dirs from the syntax scan."""
    derived = derive_targets_from_lean(LEAN_ROOT)
    protocols = {}
    for pid, template in TEMPLATES.items():
        d = FIXTURES / pid
        d.mkdir(exist_ok=True)
        for f in ("session.json", "manifest.json"):
            shutil.copy2(FIXTURES / template / f, d / f)
        (d / "asp_args.json").write_text(json.dumps(derived[pid], indent=2) + "\n")
        (d / "term.json").write_text(json.dumps(build_term(derived[pid])) + "\n")
        protocols[pid] = ProtocolDir.load(str(d))
        print(f"  {pid}: {sum(len(t) for t in derived[pid].values())} targets from scan")
    write_props_protocol_dir(
        FIXTURES / PROPS_ID, "lean", [str(SPEC_FILE)],
        "The administrator-blessed golden spec: whole-file signed evidence "
        "of TempControl/Spec.lean (the GUMBO-mirror theorems). Baseline "
        "verification checks that the spec's hash and declaration-slice "
        "goldens are derivable from the blessed content.")
    protocols[PROPS_ID] = ProtocolDir.load(str(FIXTURES / PROPS_ID))
    print(f"  {PROPS_ID}: 1 blessed spec file")
    build_tier_protocol_dirs()
    for pid in TIER_IDS:
        protocols[pid] = ProtocolDir.load(str(FIXTURES / pid))
    inputs = [a["filepath"]
              for a in derived["lean_l1a"]["hashfile"].values()]
    write_build_protocol_dir(
        FIXTURES / BUILD_ID, "lean", ["lean"], inputs, [str(BIN)],
        "run_command_lean", "run_command_lean_appr",
        {"exe_args": ["build"], "cwd": str(LEAN_ROOT)},
        "The build event: lake build as a signed term — toolchain, input "
        "sources, the build, and the output binary under one signature. "
        "The exec tier's binary golden is cross-installed from this "
        "bundle's output evidence.")
    protocols[BUILD_ID] = ProtocolDir.load(str(FIXTURES / BUILD_ID))
    print(f"  {BUILD_ID}: {len(inputs)} inputs -> 1 output, "
          "toolchain-measured build event")
    return protocols


def load_protocols(validate: bool = False) -> dict:
    if not all((FIXTURES / pid / "asp_args.json").is_file()
               for pid in (*PROTOCOL_IDS, PROPS_ID)):
        print("lean protocol dirs missing — generating from the syntax scan")
        protocols = build_protocol_dirs()
    else:
        protocols = {pid: ProtocolDir.load(str(FIXTURES / pid))
                     for pid in (*PROTOCOL_IDS, PROPS_ID)}
    if validate:
        for pid in (*TIER_IDS, BUILD_ID):
            protocols[pid] = ProtocolDir.load(str(FIXTURES / pid))
    return protocols


def provision_flow(protocols: dict) -> None:
    """Capture golden and provision on the blackboard: measurement
    protocols, the spec blessing (lean_props), and — with woven tool
    measurements — the tier protocols, whose tool hash goldens land
    measure-in-place (live artifacts, no golden copies)."""
    measured = {pid: protocols[pid] for pid in (*PROTOCOL_IDS, PROPS_ID)}
    if BUILD_ID in protocols:
        measured[BUILD_ID] = protocols[BUILD_ID]  # build runs before tiers
    for pid in TIER_IDS:
        if pid in protocols and "hashfile" in protocols[pid].asp_args:
            measured[pid] = protocols[pid]
    snapshot = TargetSnapshot.capture(measured, dest=GOLDEN_ROOT)
    print(f"golden captured: {len(snapshot.files)} files")
    client = CvmSubprocessClient()
    ctl = BlackboardController()
    ctl.register_predicate("provision",
                           make_provision_predicate(client, measured, GOLDEN_ROOT))
    for pid in measured:
        request_provision(ctl.blackboard, pid)
    bb = ctl.run()
    for key, entry in bb.get_provision().items():
        print(f"  {key}: {len(entry.result.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: FAILED - {entry.result.error}")
    if BUILD_ID in protocols:
        installed = install_build_outputs(
            protocols[BUILD_ID],
            {pid: protocols[pid] for pid in TIER_IDS if pid in protocols})
        for entry in installed:
            print(f"  build output golden -> {entry}")


def tamper(protocols: dict) -> None:
    """Corrupt the proof line of a named theorem slice."""
    args = protocols["lean_l2"].asp_args["readfile_range"][
        "lean_spec_fanOn_when_hot_targ"]
    spec = Path(args["filepath"])
    lines = spec.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  -- TAMPERED: proof body removed\n"
    spec.write_text("".join(lines))
    print(f"Tampered theorem slice: {spec.name} line {args['end_index']} "
          f"({args['metadata']})")


def tamper_semantic() -> None:
    """Flip the hot branch of the implementation: fan Off when too hot."""
    impl = LEAN_ROOT / "TempControl" / "Impl.lean"
    text = impl.read_text()
    hot = "if temp > sp.high then .On"
    assert hot in text, "implementation shape changed — update tamper_semantic"
    impl.write_text(text.replace(hot, "if temp > sp.high then .Off"))
    print("Tampered implementation: computeFanCmd hot branch .On -> .Off "
          "(TempControl/Impl.lean)")


def attest_episode(protocols: dict, repair: bool,
                   validate: bool = False) -> BlackboardController:
    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate(
        "attestation", make_attestation_predicate(client, protocols,
                                                  archive_dir=EVIDENCE_DIR))
    controller.register_predicate("protocol_check",
                                  make_readiness_predicate(
                                      protocols, baseline_root=GOLDEN_ROOT,
                                      client=client))
    fail_chain = [TierKS(protocol_id="lean_l2")]
    if repair:
        fail_chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                             refined_by="lean_l2"))
    episodes = {"lean:files": "lean_l1a"}
    if validate:
        episodes["lean:proofs"] = "lean_check"
        episodes["lean:behavior"] = "lean_exec"
    starter = StartAttestationKS(episodes=episodes)
    for ks in (*fail_chain, starter):
        controller.add_ks(ks)
    controller.route("lean:files", on_pass=[], on_fail=fail_chain)
    if validate:
        controller.route("lean:proofs", on_pass=[], on_fail=[])
        controller.route("lean:behavior", on_pass=[], on_fail=[])
    controller.blackboard.write_entry(
        key="lean:ready", predicate="protocol_check",
        measurement=readiness_request(list(protocols)))
    controller.route("lean:ready", on_pass=[starter], on_fail=[])
    controller.run()
    print(trust_summary(controller.blackboard, semantic=list(TIER_IDS)))
    return controller


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--tamper-semantic", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--validate", action="store_true")
    cli = parser.parse_args()

    if cli.provision:
        protocols = build_protocol_dirs()
        provision_flow(protocols)
        return

    if cli.tamper_semantic:
        cli.validate = True  # undetected without the semantic tiers
    protocols = load_protocols(validate=cli.validate)

    if cli.tamper_semantic:
        # Snapshot the CLEAN live bytes in memory before laundering: the
        # golden/ tree is re-captured over the tampered sources below, so
        # it cannot serve as the restore source afterward.
        clean = {p: Path(p).read_bytes() for p in (
            str(LEAN_ROOT / "TempControl" / "Impl.lean"),)}
        tamper_semantic()
        print("\n=== laundering: re-provisioning over the tampered tree ===")
        provision_flow(protocols)
        try:
            print("\n=== attestation episode (hashes bless the laundered change) ===")
            attest_episode(protocols, repair=False, validate=True)
        finally:
            for path, data in clean.items():
                Path(path).write_bytes(data)
            print("\nRestored implementation; re-provisioning clean baseline")
            provision_flow(protocols)
        return

    golden = TargetSnapshot.load(
        {pid: protocols[pid] for pid in PROTOCOL_IDS}, GOLDEN_ROOT)
    if cli.tamper:
        tamper(protocols)
    try:
        attest_episode(protocols, repair=cli.repair, validate=cli.validate)
        if cli.repair:
            print("\n=== episode 2: verification (fresh run, fresh caches) ===")
            attest_episode(protocols, repair=cli.repair, validate=cli.validate)
    finally:
        restored = golden.restore()
        if restored:
            print(f"\nRestored {len(restored)} live target(s) from golden")


if __name__ == "__main__":
    main()
