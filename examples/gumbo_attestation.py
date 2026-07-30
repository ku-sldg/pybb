"""
Attestation-driven blackboard demo: GUMBO contract integrity for the
temp-control-jvm HAMR project, on the outcome-routed blackboard.

Two always-run trust questions, each entry spending its one dispatch on
its own branch point:

    gumbo:files      starts at gumbo_l1a — whole-file hashes of the
                     baseline-immutable artifacts (AADL models + GumboX
                     oracles, ~1s)
                       pass -> on_pass: gumbo_validation (--validate)
                       fail -> on_fail: gumbo_l2 (22 contract-range
                               slices) refines the drift — pass = benign
                               drift (tolerated; re-provision to bless),
                               fail = contract violation -> escalate

    gumbo:contracts  starts at gumbo_l1b — the codegen-managed BEGIN/END
                     contract blocks inside the developer-owned component
                     files (~1s). Already block-granular: no deeper dive;
                     a failure escalates with the violated blocks.

The episode opens with a protocol-readiness verdict: "gumbo:ready" checks
every protocol in both trees (ids resolve, goldens provisioned, CVM and
ASP binaries present); its on_pass starter writes both attestation
entries. A readiness failure escalates as a configuration failure and no
attestation runs (--misconfigure demonstrates this).

Usage:
    python examples/gumbo_attestation.py [--protocols-root DIR]
        [--tamper] [--tamper-block] [--repair] [--validate] [--misconfigure]

--repair appends the repair rungs (whole-file restore after l2 refinement
on gumbo:files; block splice on gumbo:contracts) and runs a SECOND
episode: repair cannot mint trust, so episode 1 ends "repaired from
golden — verification pending", and episode 2 (fresh predicates, fresh
measurements) provides the verifying evidence.

--tamper corrupts one GUMBO contract line in a live AADL model: the
gumbo:files tree walks l1a -> l2 -> escalate with per-contract
attribution, while gumbo:contracts stays clean.

--tamper-block corrupts a line inside a component file's contract block —
undetectable by the old single-tree design (whole-file hashing cannot
watch safe-to-edit files): gumbo:files passes while gumbo:contracts
escalates with the violated block.

Either way the golden directory (provisioned out-of-band by
examples/capture_golden.py) restores the live targets after the run.

--validate adds the semantic confirmation tier to BOTH entries' pass
branches (one shared Sireum run, ~min: memoized across the entries).
"""

import argparse
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    SliceRestoreKS,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    make_attestation_predicate,
    make_readiness_predicate,
    readiness_request,
    trust_summary,
)

TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")
DEFAULT_PROTOCOLS_ROOT = Path(__file__).parent.parent / "tests" / "fixtures"
GOLDEN_ROOT = Path(__file__).parent.parent / "golden"


def tamper_live() -> None:
    """Corrupt one GUMBO contract line in a live AADL model."""
    aadl = TC_ROOT / "aadl/packages/TempControlSystem.aadl"
    lines = aadl.read_text().splitlines(keepends=True)
    lines[305] = "-- TAMPERED: invariant weakened\n"
    aadl.write_text("".join(lines))
    print(f"Tampered live file: {aadl} (line 306)")


def tamper_block() -> None:
    """Corrupt a line inside a component file's contract block."""
    comp = (TC_ROOT / "slang/src/main/component/tc/TempControlSystem"
                     / "TempControl_i_tcproc_tempControl.scala")
    lines = comp.read_text().splitlines(keepends=True)
    begin = next(i for i, l in enumerate(lines)
                 if "BEGIN COMPUTE ENSURES timeTriggered" in l)
    lines[begin + 1] = "        // TAMPERED: ensures clause weakened\n"
    comp.write_text("".join(lines))
    print(f"Tampered live contract block: {comp.name} (line {begin + 2})")


def print_report(controller: BlackboardController, semantic: list[str]) -> None:
    blackboard = controller.blackboard
    print("\n=== blackboard history (audit trail) ===")
    seen = set()
    for key, entry in blackboard.get_history():
        if entry.result is None:
            continue
        subject = (entry.measurement.get("protocol")
                   or "+".join(entry.measurement.get("protocols", [])))
        line = f"  {key}: {subject} passed={bool(entry.result)}"
        if line not in seen:  # bookkeeping snapshots repeat states
            seen.add(line)
            print(line)

    if blackboard.get_escalate():
        print("\n=== escalate segment ===")
        for key, entry in blackboard.get_escalate().items():
            print(f"  {key}: attempts={entry.ks_history}")

    print("\n=== trust summary ===\n  "
          + trust_summary(blackboard, semantic=semantic).replace("\n", "\n  "))
    print(f"\n(cycles: {controller.cycle_count})")


def build_controller(protocols: dict, cli) -> BlackboardController:
    """One episode's controller: fresh predicates, fresh memo caches."""
    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate(
        "attestation",
        make_attestation_predicate(client, protocols),
    )
    controller.register_predicate(
        "protocol_check", make_readiness_predicate(
            protocols, baseline_root=GOLDEN_ROOT, client=client)
    )

    # the two decision trees, pre-registered (their entries are written by
    # the readiness chain's starter rung)
    files_fail = [TierKS(protocol_id="gumbo_l2")]
    contracts_fail = []
    if cli.repair:
        files_fail.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT))
        contracts_fail.append(SliceRestoreKS(golden_root=GOLDEN_ROOT))
    confirm = [TierKS(protocol_id="gumbo_validation")] if cli.validate else []
    starter = StartAttestationKS(episodes={
        "gumbo:files": "gumbo_l1a",
        "gumbo:contracts": "gumbo_l1b",
    })
    for ks in [*confirm, *files_fail, *contracts_fail, starter]:
        controller.add_ks(ks)
    controller.route("gumbo:files", on_pass=confirm, on_fail=files_fail)
    controller.route("gumbo:contracts", on_pass=confirm, on_fail=contracts_fail)

    # the first verdict: does every protocol in both trees exist and run?
    checked = list(protocols)
    if cli.misconfigure:
        checked.append("gumbo_l9")
    controller.blackboard.write_entry(
        key="gumbo:ready", predicate="protocol_check",
        measurement=readiness_request(checked),
    )
    controller.route("gumbo:ready", on_pass=[starter], on_fail=[])
    return controller


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocols-root", default=str(DEFAULT_PROTOCOLS_ROOT))
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--tamper-block", action="store_true")
    parser.add_argument("--repair", action="store_true",
                        help="append repair rungs and run a verifying "
                             "second episode")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--misconfigure", action="store_true",
                        help="check a nonexistent protocol id: readiness "
                             "escalates, attestation never starts")
    cli = parser.parse_args()

    protocol_ids = ["gumbo_l1a", "gumbo_l1b", "gumbo_l2"]
    if cli.validate:
        protocol_ids.append("gumbo_validation")
    protocols = {
        pid: ProtocolDir.load(str(Path(cli.protocols_root) / pid))
        for pid in protocol_ids
    }
    # golden copies of the live targets, provisioned out-of-band; the
    # finally below reverts any tampering repair did not already revert
    try:
        golden = TargetSnapshot.load(protocols, GOLDEN_ROOT)
    except FileNotFoundError as e:
        raise SystemExit(
            f"{e}\nProvision it with: python examples/capture_golden.py"
        )
    print(f"Golden targets: {len(golden.files)} files under {golden.root}")
    if cli.tamper:
        tamper_live()
    if cli.tamper_block:
        tamper_block()

    try:
        controller = build_controller(protocols, cli)
        controller.run()
        print_report(controller, semantic=["gumbo_validation"])

        if cli.repair:
            print("\n=== episode 2: verification (fresh run, fresh caches) ===")
            episode2 = build_controller(protocols, cli)
            episode2.run()
            print_report(episode2, semantic=["gumbo_validation"])
    finally:
        restored = golden.restore()
        if restored:
            print(f"\nRestored {len(restored)} live target(s) from golden")


if __name__ == "__main__":
    main()
