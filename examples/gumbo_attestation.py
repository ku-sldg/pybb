"""
Attestation-driven blackboard demo: GUMBO contract integrity for the
temp-control-jvm HAMR project, on the outcome-routed blackboard.

One entry ("gumbo") whose predicate attests the protocol named in its
measurement; the route encodes the decision tree:

    eval gumbo_l1 (whole-file hashes, ~1s)
      pass -> on_pass:  gumbo_validation (sireum tipe/logika/test, ~min,
              with --validate) confirms the passing hashes semantically;
              without --validate a pass is final
      fail -> on_fail:  gumbo_l2 (per-contract slices, ~1s) attributes
              the failure to specific GUMBO contracts

    the chosen tier's pass ends the run in good standing; its failure
    moves the entry to the escalate segment carrying that tier's verdict
    (the failure report) and the attempt history.

Usage:
    python examples/gumbo_attestation.py [--protocols-root DIR] [--tamper] [--validate]

--tamper copies the watched files to a temp tree, corrupts one GUMBO
contract line, and attests the copy — the provisioned originals are never
modified. The tampered run walks l1 -> l2 -> escalate.

--validate adds the confirmation tier on the pass branch. It runs the live
Sireum tools against the real project (takes minutes), so a clean run is
no longer instant: a passing l1 is provisional until validation concurs.
"""

import argparse
import shutil
import tempfile
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    TierKS,
    attestation_request,
    make_attestation_predicate,
    trust_summary,
)

TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")
DEFAULT_PROTOCOLS_ROOT = Path(__file__).parent.parent / "tests" / "fixtures"


def make_tampered_copy(protocols: dict) -> dict:
    """Copy watched files to a temp root, corrupt one contract line."""
    root = Path(tempfile.mkdtemp(prefix="pybb_tamper_")) / TC_ROOT.name
    files = {
        Path(args["filepath"])
        for proto in protocols.values()
        for targets in proto.asp_args.values()
        for args in targets.values()
        if args.get("filepath")
    }
    for f in files:
        dest = root / f.relative_to(TC_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    aadl = root / "aadl/packages/TempControlSystem.aadl"
    lines = aadl.read_text().splitlines(keepends=True)
    lines[305] = "-- TAMPERED: invariant weakened\n"
    aadl.write_text("".join(lines))
    print(f"Tampered copy at {root} (line 306 of TempControlSystem.aadl)")
    return {str(TC_ROOT): str(root)}


def print_report(controller: BlackboardController, semantic: list[str]) -> None:
    blackboard = controller.blackboard
    print("\n=== blackboard history (audit trail) ===")
    seen = set()
    for key, entry in blackboard.get_history():
        if entry.result is None:
            continue
        line = (f"  {key}: {entry.measurement.get('protocol')} "
                f"passed={bool(entry.result)}")
        if line not in seen:  # bookkeeping snapshots repeat states
            seen.add(line)
            print(line)

    if blackboard.get_escalate():
        print("\n=== escalate segment (user intervention required) ===")
        for key, entry in blackboard.get_escalate().items():
            print(f"  {key}: attempts={entry.ks_history}")

    print("\n=== trust summary ===\n  "
          + trust_summary(blackboard, semantic=semantic).replace("\n", "\n  "))
    print(f"\n(cycles: {controller.cycle_count})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocols-root", default=str(DEFAULT_PROTOCOLS_ROOT))
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--validate", action="store_true")
    cli = parser.parse_args()

    protocol_ids = ["gumbo_l1", "gumbo_l2"]
    if cli.validate:
        protocol_ids.append("gumbo_validation")
    protocols = {
        pid: ProtocolDir.load(str(Path(cli.protocols_root) / pid))
        for pid in protocol_ids
    }
    path_map = make_tampered_copy(protocols) if cli.tamper else None

    controller = BlackboardController()
    controller.register_predicate(
        "attestation",
        make_attestation_predicate(CvmSubprocessClient(), protocols),
    )
    on_fail = [TierKS(protocol_id="gumbo_l2")]
    on_pass = []
    if cli.validate:
        # confirmation runs against the real project (no path_map): the
        # watched-file copy is not a runnable Sireum project
        on_pass = [TierKS(protocol_id="gumbo_validation", carry_path_map=False)]
    for ks in [*on_pass, *on_fail]:
        controller.add_ks(ks)

    controller.blackboard.write_entry(
        key="gumbo", predicate="attestation",
        measurement=attestation_request("gumbo_l1", path_map=path_map),
    )
    controller.route("gumbo", on_pass=on_pass, on_fail=on_fail)
    controller.run()

    print_report(controller, semantic=["gumbo_validation"])


if __name__ == "__main__":
    main()
