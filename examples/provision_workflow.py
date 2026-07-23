"""
Provision-partition demo: an external event adds files to the golden
directory and requests provisioning on the blackboard; the same controller
run provisions golden evidence bundles and then attests the live tree
against the fresh goldens.

The scratch setup copies the protocol fixtures and golden/ to a temp
directory, so the committed repo state is never modified — a real
deployment would run against the repo's golden/ and protocol dirs
directly.

Usage:
    python examples/provision_workflow.py [--tamper-golden]

--tamper-golden corrupts one GUMBO contract line in the *golden copy*
before provisioning. Provisioning still succeeds (gold is the authority;
there is nothing to compare against), but attestation then fails: the live
tree no longer matches the newly declared gold, l2 attributes the drift to
the exact contract, and the entry escalates. This is the "gold moved ahead
of live" scenario — the mirror image of live-tree tampering.
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
    make_provision_predicate,
    request_provision,
    trust_summary,
)
from pybb.attestation.snapshot import mirror_path

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
GOLDEN_ROOT = Path(__file__).parent.parent / "golden"
TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")
PROTOCOL_IDS = ("gumbo_l1", "gumbo_l2")


def tamper_golden(golden_root: Path) -> None:
    """Corrupt one GUMBO contract line in the golden copy of the AADL model."""
    aadl = mirror_path(golden_root, TC_ROOT / "aadl/packages/TempControlSystem.aadl")
    lines = aadl.read_text().splitlines(keepends=True)
    lines[305] = "-- GOLD MOVED: invariant revised\n"
    aadl.write_text("".join(lines))
    print(f"Tampered golden copy: {aadl} (line 306)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tamper-golden", action="store_true")
    cli = parser.parse_args()

    # scratch copies of golden/ and the protocol dirs (provisioning writes both)
    scratch = Path(tempfile.mkdtemp(prefix="pybb_provision_"))
    golden_root = scratch / "golden"
    shutil.copytree(GOLDEN_ROOT, golden_root)
    protocols = {}
    for pid in PROTOCOL_IDS:
        shutil.copytree(FIXTURES / pid, scratch / pid)
        protocols[pid] = ProtocolDir.load(str(scratch / pid))
    print(f"Scratch working set at {scratch}")

    # the external event: golden files change (optionally), and requests land
    if cli.tamper_golden:
        tamper_golden(golden_root)

    client = CvmSubprocessClient()
    controller = BlackboardController()
    controller.register_predicate(
        "provision", make_provision_predicate(client, protocols, golden_root)
    )
    controller.register_predicate(
        "attestation", make_attestation_predicate(client, protocols)
    )
    for pid in PROTOCOL_IDS:
        request_provision(controller.blackboard, pid)

    on_fail = [TierKS(protocol_id="gumbo_l2")]
    for ks in on_fail:
        controller.add_ks(ks)
    controller.blackboard.write_entry(
        key="gumbo", predicate="attestation",
        measurement=attestation_request("gumbo_l1"),
    )
    controller.route("gumbo", on_fail=on_fail)
    controller.run()
    blackboard = controller.blackboard

    print("\n=== provision partition (provisioned state) ===")
    for key, entry in blackboard.get_provision().items():
        outcome = entry.result
        print(f"  {key}: {len(outcome.provisioned)} targets provisioned "
              f"from golden (bundle: {Path(outcome.bundle_path).name})")
    for key, entry in blackboard.get_escalate().items():
        if key.startswith("provision:"):
            print(f"  {key}: FAILED - {entry.result.error}")

    print("\n=== trust summary ===\n  "
          + trust_summary(blackboard).replace("\n", "\n  "))
    print(f"\n(cycles: {controller.cycle_count})")


if __name__ == "__main__":
    main()
