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
    lean_exec  `lake exe temp-control <vector>` per GUMBO case (hot/cold/
               hold); stdout must equal the expected command. Main imports
               only TempControl.Impl, so a broken proof cannot fail this
               build: provability and behavior are independent measurements.

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
             implementation AND re-provision over the tampered tree — the
             laundered change passes every hash, and is refuted twice:
             the proofs no longer check (lean_check) and the binary's
             behavior no longer matches its expected vectors (lean_exec,
             whose expectations are config, not provisioned goldens).
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
from pybb.attestation.props import write_props_protocol_dir
from pybb.attestation.targetmap import build_term, derive_targets_from_lean

REPO = Path(__file__).parent.parent
LEAN_ROOT = REPO / "targets" / "temp-control-lean"
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
PROTOCOL_IDS = ("lean_l1a", "lean_l2")
PROPS_ID = "lean_props"
TIER_IDS = ("lean_check", "lean_exec")
TEMPLATES = {"lean_l1a": "gumbo_l1a", "lean_l2": "gumbo_l2"}
SPEC_FILE = LEAN_ROOT / "TempControl" / "Spec.lean"


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
        for pid in TIER_IDS:
            protocols[pid] = ProtocolDir.load(str(FIXTURES / pid))
    return protocols


def provision_flow(protocols: dict) -> None:
    """Capture golden and provision the scan-derived goldens on the
    blackboard (the lean_props bundle is the administrator's blessing of
    the spec file)."""
    measured = {pid: protocols[pid] for pid in (*PROTOCOL_IDS, PROPS_ID)}
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
        "attestation", make_attestation_predicate(client, protocols))
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
