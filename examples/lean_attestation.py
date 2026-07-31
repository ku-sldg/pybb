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

Two artifacts are owned by the out-of-band attestation manager and change
ONLY through --promote (the administrator's sanctioning act):

    lean_props      the blessing of TempControl/Spec.lean. Ordinary
                    provisioning (--provision, laundering) never re-signs
                    it, so a spec change without promotion leaves a stale
                    blessing that baseline verification refutes.
    exec expecteds  the behavior vectors' expected outputs (AM config,
                    never provisioned goldens). --promote re-runs the
                    vectors against the sanctioned build and REFUSES if
                    they diverge from the sanctioned expecteds; a
                    deliberate behavior change is sanctioned via --expect.

Usage:
    python examples/lean_attestation.py [--check] [--provision]
        [--promote [--expect KEY=VALUE ...]] [--tamper]
        [--tamper-semantic] [--repair] [--validate]

--check      attestation-manager detection: declaration-level diff of the
             live spec against the provisioned golden slices, matched by
             declaration NAME (moved is not changed); reports whether
             promotion is needed
--promote    the sanctioned pipeline: behavior gate (lake build + the
             vectors must match the sanctioned expecteds) -> proof gate
             (lean_check must prove, toolchain measured in the same term)
             -> syntax-scan target regeneration -> gold moves -> full
             provisioning INCLUDING the lean_props re-blessing -> a
             verification episode against the new baseline
--expect     (with --promote) sanction a behavior change: override an
             exec vector's expected output, e.g. --expect hot=fanCmd=Off
--provision  (re)generate lean_l1a/lean_l2 protocol dirs from the syntax
             scan, capture golden, and provision via the blackboard —
             WITHOUT re-blessing lean_props (that is --promote's act;
             the existing blessing is kept, and exec expecteds carry
             over from the installed protocol)
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
import copy
import json
import shutil
import subprocess
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    changed_decls,
    make_attestation_predicate,
    make_promotion_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    promotion_request,
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


LAKE = Path.home() / "Claude_workspace" / "bin" / "lake"
EXEC_KEYS = ("hot", "cold", "hold")


def _exec_targ(key: str) -> str:
    return f"lean_exec_{key}_targ"


def resolved_exec_targets(overrides: dict | None = None) -> dict:
    """
    The sanctioned behavior expectation: TIER_TARGETS defaults, then the
    currently installed (previously sanctioned) expecteds, then explicit
    --expect overrides — the promote-time sanctioning of a behavior
    change. Expecteds are AM config: laundering re-provisions goldens,
    never these.
    """
    targets = copy.deepcopy(TIER_TARGETS["lean_exec"])
    installed = FIXTURES / "lean_exec" / "asp_args.json"
    if installed.is_file():
        current = json.loads(installed.read_text()).get("run_command_lean", {})
        for targ, args in targets.items():
            if "expected" in current.get(targ, {}):
                args["expected"] = current[targ]["expected"]
    for key, value in (overrides or {}).items():
        if _exec_targ(key) not in targets:
            raise SystemExit(f"--expect: unknown vector '{key}' "
                             f"(choose from {', '.join(EXEC_KEYS)})")
        targets[_exec_targ(key)]["expected"] = value
    return targets


def _run_vector(args: dict) -> str:
    out = subprocess.run([str(LAKE), *args["exe_args"]], cwd=args["cwd"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def vector_failures(exec_targets: dict, run_vector=_run_vector) -> list:
    """Behavior vectors vs the sanctioned expecteds; [] iff conformant."""
    failures = []
    for targ, args in exec_targets.items():
        got = run_vector(args)
        if got != args["expected"]:
            failures.append(
                f"{targ}: expected '{args['expected']}', got '{got}'")
    return failures


def make_codegen_fn(exec_targets: dict, run_vector=_run_vector):
    """
    The promotion pipeline's 'codegen' for Lean: there is no model->code
    step, so the sanctioned build IS the regeneration — lake build, then
    the behavior gate: every exec vector must match the sanctioned
    expecteds. A behavior change that was not sanctioned via --expect
    refuses the promotion before anything is blessed.
    """
    def build_and_check() -> str:
        subprocess.run([str(LAKE), "build"], cwd=LEAN_ROOT, check=True,
                       capture_output=True)
        failures = vector_failures(exec_targets, run_vector)
        if failures:
            raise RuntimeError(
                "behavior gate refused: " + "; ".join(failures)
                + " — if this behavior change is sanctioned, "
                  "re-run with --expect KEY=VALUE")
        return ("lake build ok; behavior vectors match the sanctioned "
                "expecteds")
    return build_and_check


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


def build_tier_protocol_dirs(exec_targets: dict | None = None) -> None:
    """(Re)generate the semantic-tier dirs from the base config, with tool
    measurements woven in per TOOL_CADENCE. lean_exec additionally hashes
    the pinned binary against its build-anchored golden BEFORE running it
    (hash-then-run, same term). Exec expecteds are AM-owned: unless a
    sanctioned set is passed in (--promote --expect), the installed
    expecteds carry over (resolved_exec_targets)."""
    for pid, targets in TIER_TARGETS.items():
        if pid == "lean_exec":
            targets = (exec_targets if exec_targets is not None
                       else resolved_exec_targets())
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


def build_protocol_dirs(bless_props: bool = False,
                        exec_targets: dict | None = None) -> dict:
    """(Re)generate the measurement protocol dirs from the syntax scan.
    The lean_props definition is AM-owned: it is rewritten only under
    --promote (bless_props) or when missing entirely (bootstrap) — an
    ordinary --provision keeps the existing blessing untouched."""
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
    props_dir = FIXTURES / PROPS_ID
    if bless_props or not (props_dir / "asp_args.json").is_file():
        write_props_protocol_dir(
            props_dir, "lean", [str(SPEC_FILE)],
            "The administrator-blessed golden spec: whole-file signed evidence "
            "of TempControl/Spec.lean (the GUMBO-mirror theorems). Baseline "
            "verification checks that the spec's hash and declaration-slice "
            "goldens are derivable from the blessed content.")
        print(f"  {PROPS_ID}: 1 blessed spec file")
    else:
        print(f"  {PROPS_ID}: existing blessing kept "
              "(only --promote re-blesses the spec)")
    protocols[PROPS_ID] = ProtocolDir.load(str(props_dir))
    build_tier_protocol_dirs(exec_targets)
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


def provision_flow(protocols: dict, bless_props: bool = False) -> None:
    """Capture golden and provision on the blackboard: measurement
    protocols and — with woven tool measurements — the tier protocols,
    whose tool hash goldens land measure-in-place (live artifacts, no
    golden copies). The lean_props blessing is provisioned ONLY under
    --promote (bless_props) or when it has never been blessed (bootstrap):
    re-signing the spec is the administrator's sanctioning act, so
    ordinary re-provisioning — including a laundering pass — cannot
    refresh it."""
    props = protocols.get(PROPS_ID)
    props_unblessed = props is not None and not any(
        a.get("golden_b64")
        for a in props.asp_args.get("readfile", {}).values())
    pids = list(PROTOCOL_IDS)
    if props is not None and (bless_props or props_unblessed):
        pids.append(PROPS_ID)
    measured = {pid: protocols[pid] for pid in pids}
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


def check_flow(protocols: dict) -> None:
    """AM detection: the declaration-level diff, matched by name. The
    blessed spec bytes (lean_props) are the authoritative baseline for
    Spec.lean — l2 goldens are launderable, the blessing is not."""
    diff = changed_decls(protocols["lean_l2"], LEAN_ROOT,
                         props_protocol=protocols.get(PROPS_ID))
    if not diff:
        print("No declaration changes since last blessing; "
              "promotion not needed.")
        return
    print("Promotion needed — declarations changed since last blessing:")
    for label, bucket in (("added", diff.added), ("removed", diff.removed),
                          ("modified", diff.modified), ("moved", diff.moved)):
        for meta in bucket:
            print(f"  {label:<9}{meta}")
    print("Run --promote to make the sanctioned change the new baseline"
          " (an unsanctioned change should be investigated instead).")


def promote_flow(protocols: dict, expect_overrides: dict) -> None:
    """
    The sanctioning act, in pipeline order:

      1. detection report (informational — what is being sanctioned)
      2. promotion request on the blackboard; its predicate runs the gates
         and moves gold: behavior gate (lake build + vectors vs the
         sanctioned expecteds), proof gate (lean_check must prove, lean
         toolchain measured in the same term), syntax-scan target
         regeneration, golden capture
      3. only after the promote outcome is good: regenerate the AM-owned
         config (tier dirs with the sanctioned expecteds, the props
         blessing definition, the build event) and provision EVERYTHING,
         lean_props included — the re-blessing
      4. verification episode against the new baseline

    Steps 2 and 3 are deliberately two blackboard runs: a refused gate
    must leave the old baseline fully in place, so no provision request
    exists until the promotion outcome is known good.
    """
    print("=== sanction review (declaration diff) ===")
    check_flow(protocols)
    exec_targets = resolved_exec_targets(expect_overrides)
    for key in expect_overrides or {}:
        print(f"  sanctioned expected: {key} -> "
              f"{exec_targets[_exec_targ(key)]['expected']}")

    print("\n=== promotion episode (gates, then gold moves) ===")
    client = CvmSubprocessClient()
    gated = {pid: protocols[pid] for pid in (*PROTOCOL_IDS, PROPS_ID)}
    gated["lean_check"] = protocols["lean_check"]
    ctl = BlackboardController()
    ctl.register_predicate("promotion", make_promotion_predicate(
        gated, GOLDEN_ROOT,
        targets_fn=lambda: derive_targets_from_lean(LEAN_ROOT),
        codegen_fn=make_codegen_fn(exec_targets),
        client=client,
        validate_with="lean_check",
    ))
    ctl.blackboard.write_entry(
        key="promote:lean", predicate="promotion",
        measurement=promotion_request("lean"), partition="provision")
    bb = ctl.run()
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: REFUSED - {entry.result.error}")
    outcome = bb.provision["promote:lean"].result
    print(f"  promote:lean: {outcome.codegen}; proofs validated; "
          f"targets regenerated={outcome.targets}; "
          f"{outcome.captured} files -> golden")

    print("\n=== provisioning the new baseline (props re-blessed) ===")
    fresh = build_protocol_dirs(bless_props=True, exec_targets=exec_targets)
    protocols.update(fresh)
    provision_flow(protocols, bless_props=True)

    print("\n=== verification episode (new baseline) ===")
    attest_episode(protocols, repair=False, validate=True)


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
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--expect", action="append", default=[],
                        metavar="KEY=VALUE")
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--tamper-semantic", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--validate", action="store_true")
    cli = parser.parse_args()

    if cli.expect and not cli.promote:
        parser.error("--expect is the promote-time sanctioning knob; "
                     "use it with --promote")
    if cli.check:
        check_flow(load_protocols())
        return
    if cli.promote:
        overrides = {}
        for item in cli.expect:
            key, sep, value = item.partition("=")
            if not sep:
                parser.error(f"--expect wants KEY=VALUE, got '{item}'")
            overrides[key] = value
        promote_flow(load_protocols(validate=True), overrides)
        return
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
