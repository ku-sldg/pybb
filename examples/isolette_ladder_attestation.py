"""
Isolette attestation via the report-guided cvm-mcp provisioning workflow:
isolette_l1 (whole-file hashes of the 13 report-named files) escalating to
isolette_l2 (85 per-contract slices) on failure — the same ladder + repair
machinery as the gumbo demos, on a model-driven third-party system.

The protocol dirs are generated from the HAMR attestation report by
cvm-mcp/hamr_report_protocols.py and provisioned by the dashboard flow.

Usage:
    python examples/isolette_ladder_attestation.py [--protocols-root DIR]
                                                   [--tamper] [--repair]

--tamper copies the watched files to a temp tree and corrupts a guarantee
clause in Regulate.aadl (inside a measured slice); the provisioned originals
are never modified. --repair adds RepairKS with golden restore.
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    CvmSubprocessClient,
    EscalationKS,
    GoldenRestoreRepairer,
    ProtocolDir,
    RepairKS,
    TrustDecisionKS,
    request_key,
)

ISOLETTE_ROOT = Path.home() / "Claude_workspace/INSPECTA-models/isolette"
DEFAULT_PROTOCOLS_ROOT = Path.home() / "Claude_workspace/cvm-mcp/protocol_dirs"


def make_tampered_copy(protocols: dict) -> dict:
    root = Path(tempfile.mkdtemp(prefix="pybb_isolette_tamper_")) / "isolette"
    files = {
        Path(args["filepath"])
        for proto in protocols.values()
        for targets in proto.asp_args.values()
        for args in targets.values()
        if args.get("filepath")
    }
    for f in files:
        dest = root / f.relative_to(ISOLETTE_ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    aadl = root / "aadl/aadl/packages/Regulate.aadl"
    lines = aadl.read_text().splitlines(keepends=True)
    # inside the RegulatorStatusIsInitiallyInit slice (lines 217-218)
    lines[217] = lines[217].replace("Init_Status", "On_Status")
    aadl.write_text("".join(lines))
    print(f"Tampered copy at {root} (Regulate.aadl guarantee clause, line 218)")
    return {str(ISOLETTE_ROOT): str(root)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocols-root", default=str(DEFAULT_PROTOCOLS_ROOT))
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--repair", action="store_true")
    cli = parser.parse_args()

    protocols = {
        pid: ProtocolDir.load(str(Path(cli.protocols_root) / pid))
        for pid in ("isolette_l1", "isolette_l2")
    }
    path_map = make_tampered_copy(protocols) if cli.tamper else None

    controller = BlackboardController()
    controller.add_ks(AttestationKS(client=CvmSubprocessClient(), protocols=protocols))
    controller.add_ks(AppraisalKS(protocols=protocols))
    controller.add_ks(EscalationKS(
        on_fail="isolette_l1", escalate_to="isolette_l2", path_map=path_map,
    ))
    if cli.repair:
        controller.add_ks(RepairKS(
            repairers=[GoldenRestoreRepairer(protocols)],
            watch=["isolette_l2"],
            reattest=["isolette_l1", "isolette_l2"],
        ))
    controller.add_ks(TrustDecisionKS())

    request = {"protocol": "isolette_l1"}
    if path_map:
        request["path_map"] = path_map
    controller.blackboard.write(
        key=request_key("isolette_l1"), value=request, source="main",
        tags=["attestation", "request"],
    )

    blackboard = controller.run()

    print("\n=== blackboard history (audit trail) ===")
    for entry in blackboard.history:
        stamp = entry.timestamp.strftime("%H:%M:%S")
        print(f"  {stamp}  conf={entry.confidence:>3.1f}  {entry.source:<16} {entry.key}")

    print("\n=== verdicts (failing components only) ===")
    for key in sorted(blackboard.keys()):
        if key.startswith("attestation.verdict/"):
            v = blackboard.read(key)
            failing = {c: ok for c, ok in v.get("components", {}).items() if not ok}
            print(f"  {key}: passed={v['passed']}"
                  + (f", failing={json.dumps(failing)}" if failing else ""))

    print(f"\n=== hypothesis ===\n  {blackboard.hypothesis}")
    print(f"\n(cycles: {controller.cycle_count})")


if __name__ == "__main__":
    main()
