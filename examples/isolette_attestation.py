"""
HAMR attestation-report demo: attest the isolette contract slices on the
blackboard via the rodeo transport.

Prerequisite: the attestation root must be provisioned (hamr_maestro_term.json
and golden evidence present) — see pybb/attestation/rodeo.py docstring or
pybb/attestation/README.md for the one-time provisioning command.

Usage:
    python examples/isolette_attestation.py [--attestation-root DIR]
"""

import argparse
import json
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    RodeoProtocol,
    RodeoSubprocessClient,
    TrustDecisionKS,
    request_key,
)

DEFAULT_ROOT = Path.home() / (
    "Claude_workspace/INSPECTA-models/isolette/hamr/microkit/attestation"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation-root", default=str(DEFAULT_ROOT))
    cli = parser.parse_args()

    protocols = {
        "isolette": RodeoProtocol.load(cli.attestation_root, protocol_id="isolette")
    }
    controller = BlackboardController()
    controller.add_ks(AttestationKS(client=RodeoSubprocessClient(), protocols=protocols))
    controller.add_ks(AppraisalKS(protocols=protocols))
    controller.add_ks(TrustDecisionKS())
    controller.blackboard.write(
        key=request_key("isolette"),
        value={"protocol": "isolette"},
        source="main",
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
