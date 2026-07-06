"""
Attestation-driven blackboard demo: GUMBO contract integrity for the
temp-control-jvm HAMR project.

Seeds a gumbo_l1 (whole-file hash) attestation request; if it fails, an
EscalationKS posts gumbo_l2 (per-contract ranges) for attribution, and the
TrustDecisionKS summarizes the outcome as the blackboard hypothesis.

Usage:
    python examples/gumbo_attestation.py [--protocols-root DIR] [--tamper] [--validate]

--tamper copies the watched files to a temp tree, corrupts one GUMBO
contract line, and attests the copy — the provisioned originals are never
modified.

--validate adds the third tier: on a gumbo_l2 failure, gumbo_validation
runs the live Sireum tools (proyek tipe / logika / test — takes minutes)
against the real project. In a --tamper run the tampering lives only in the
temp copy, so validation passes and the hypothesis reads "modified yet
system still verifies".
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
    ProtocolDir,
    TrustDecisionKS,
    request_key,
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
    controller.add_ks(AttestationKS(client=CvmSubprocessClient(), protocols=protocols))
    controller.add_ks(AppraisalKS(protocols=protocols))
    controller.add_ks(
        EscalationKS(
            name="EscalationKS_l1_l2",
            on_fail="gumbo_l1", escalate_to="gumbo_l2", path_map=path_map,
        )
    )
    if cli.validate:
        # semantic tier runs against the real project (no path_map): the
        # watched-file copy is not a runnable Sireum project
        controller.add_ks(
            EscalationKS(
                name="EscalationKS_l2_validation",
                on_fail="gumbo_l2", escalate_to="gumbo_validation",
            )
        )
    controller.add_ks(TrustDecisionKS(semantic=["gumbo_validation"]))

    request = {"protocol": "gumbo_l1"}
    if path_map:
        request["path_map"] = path_map
    controller.blackboard.write(
        key=request_key("gumbo_l1"), value=request, source="main",
        tags=["attestation", "request"],
    )

    blackboard = controller.run()

    print("\n=== blackboard history (audit trail) ===")
    for entry in blackboard.history:
        stamp = entry.timestamp.strftime("%H:%M:%S")
        print(f"  {stamp}  conf={entry.confidence:>3.1f}  {entry.source:<16} {entry.key}")

    print("\n=== verdicts ===")
    for key in sorted(blackboard.keys()):
        if key.startswith("attestation.verdict/"):
            print(f"  {key}: {json.dumps(blackboard.read(key), indent=2)}")

    print(f"\n=== hypothesis ===\n  {blackboard.hypothesis}")
    print(f"\n(cycles: {controller.cycle_count})")


if __name__ == "__main__":
    main()
