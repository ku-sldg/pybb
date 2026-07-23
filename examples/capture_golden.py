"""
Provision the golden directory: clean copies of the watched target files,
captured from the live tree into <repo>/golden.

Running this is the deliberate, out-of-band act of declaring the current
live targets known-good — do it only when the tree is verified clean (e.g.
after a passing validation run) and in step with the protocol fixtures,
whose golden values were provisioned against these same files. Nothing in
the attestation or restore flow writes golden state.

Usage:
    python examples/capture_golden.py [--protocols-root DIR]
"""

import argparse
from pathlib import Path

from pybb.attestation import ProtocolDir, TargetSnapshot

GOLDEN_ROOT = Path(__file__).parent.parent / "golden"
DEFAULT_PROTOCOLS_ROOT = Path(__file__).parent.parent / "tests" / "fixtures"
PROTOCOL_IDS = ["gumbo_l1a", "gumbo_l1b", "gumbo_l2", "gumbo_validation"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocols-root", default=str(DEFAULT_PROTOCOLS_ROOT))
    cli = parser.parse_args()

    protocols = {
        pid: ProtocolDir.load(str(Path(cli.protocols_root) / pid))
        for pid in PROTOCOL_IDS
    }
    snapshot = TargetSnapshot.capture(protocols, dest=GOLDEN_ROOT)
    print(f"Golden directory provisioned at {snapshot.root}:")
    for live, copy in snapshot.files.items():
        print(f"  {live}\n    -> {copy}")


if __name__ == "__main__":
    main()
