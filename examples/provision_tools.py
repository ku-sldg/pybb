"""
Bless the attestation stack (docs/ledger_plan.md B.8): build the
`attestation_tools` protocol over the CVM binary, the verified summarizer,
every ASP the configured protocols use, and the verifying key; provision it
(the CVM hashes the live binaries and signs); record the bundle in the
ledger. Under the default cadence this is the only time the tools are
measured — repeat it after rebuilding asp-libs or the CVM.

    python examples/provision_tools.py [--ledger FILE] [--force] [--golden-root DIR]
"""

import argparse
import sys
from pathlib import Path

from pybb.attestation import CvmSubprocessClient, FileLedger, ProtocolDir
from pybb.attestation.client import CvmConfig
from pybb.attestation.ledger import LedgerConfig
from pybb.attestation.ledger_tooling import TOOLING_PROTOCOL_ID, bless_tools, build_attestation_tools_protocol

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", help="FileLedger path (default: immudb from the environment)")
    ap.add_argument("--no-ledger", action="store_true", help="provision only; record nothing")
    ap.add_argument("--force", action="store_true", help="fresh bundle even if the tools are unchanged")
    ap.add_argument("--golden-root", default=str(REPO / "golden"))
    args = ap.parse_args()

    config = LedgerConfig(golden_root=args.golden_root)
    protocols = {p.name: ProtocolDir.load(str(p)) for p in sorted(FIXTURES.iterdir())
                 if (p / "session.json").is_file() and p.name != TOOLING_PROTOCOL_ID}
    tp = build_attestation_tools_protocol(FIXTURES / TOOLING_PROTOCOL_ID, CvmConfig(), protocols, config)
    print(f"{TOOLING_PROTOCOL_ID}: {len(tp.asp_args['hashfile'])} artifacts")
    for a in tp.asp_args["hashfile"].values():
        print("  ", a["filepath"])

    ledger = None
    if not args.no_ledger:
        if args.ledger:
            ledger = FileLedger(args.ledger)
        else:
            from pybb.attestation import ImmudbLedger
            ledger = ImmudbLedger(config)
    b = bless_tools(CvmSubprocessClient(), tp, args.golden_root, ledger, config, force=args.force)
    if b.error:
        print("ERROR:", b.error)
        return 1
    print(f"blessed: bundle {b.bundle_path}\n  sha256 {b.bundle_sha256}\n  {len(b.provisioned)} goldens"
          f"{'  ledger ' + b.ledger_key if b.ledger_key else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
