"""
Reconcile the ledger against the evidence repo (docs/ledger_plan.md H.2 step 3).

    python examples/ledger_reconcile.py [--verify-all] [--ledger FILE]

Lists blobs that are not yet durable (no github locator), optionally re-reads
every committed blob and checks its hash, and compares the live ledger head
with the latest mirrored state. Exit 1 when anything is off.
"""
import argparse
import sys

from pybb.attestation import FileLedger
from pybb.attestation.ledger import LedgerConfig
from pybb.attestation.ledger_repo import EvidenceRepo, reconcile


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify-all", action="store_true")
    ap.add_argument("--ledger", help="FileLedger path (default: immudb from the environment)")
    args = ap.parse_args()
    config = LedgerConfig()
    if not config.evidence_repo:
        sys.exit("set PYBB_EVIDENCE_REPO to the path of your evidence repo clone")
    if args.ledger:
        ledger = FileLedger(args.ledger)
    else:
        from pybb.attestation import ImmudbLedger
        ledger = ImmudbLedger(config)
    rep = reconcile(ledger, EvidenceRepo(config.evidence_repo), verify_all=args.verify_all)
    print(f"pending blobs: {len(rep.pending)}")
    for pb in rep.pending:
        print(f"  {pb.target:10s} {pb.blob_sha256[:12]}… nid={(pb.nid or '')[:12]} {pb.local.path}")
    if args.verify_all:
        print(f"remote blobs verified: {rep.verified_remote}, mismatches: {len(rep.remote_mismatches)}")
        for m in rep.remote_mismatches:
            print("  MISMATCH:", m)
    print(f"live state: tx {rep.live_state.get('tx_id')}  mirrored: tx {rep.mirrored_state.get('tx_id', '-')}  ok={rep.state_ok}")
    for p in rep.problems:
        print("PROBLEM:", p)
    return 0 if rep else 1


if __name__ == "__main__":
    sys.exit(main())
