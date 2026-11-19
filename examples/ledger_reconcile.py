"""
Reconcile the ledger against the evidence repo (docs/ledger_plan.md H.2 step 3).

    python examples/ledger_reconcile.py [--verify-all] [--ledger FILE]

Lists blobs stated for the repo's store but not yet in it, optionally re-reads
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
    print(f"store {rep.store}: pending blobs: {len(rep.pending)}")
    for sb in rep.pending:
        print(f"  {sb.part:10s} {sb.blob_sha256[:12]}… bid={sb.bid[:12]} {sb.local_path or '(no local copy)'}")
    if rep.last_mirror is not None:
        m = rep.last_mirror
        print(f"last mirror: commit {m.commit[:12]} state tx {m.state_tx} journal {m.journal_from_tx}-{m.journal_to_tx} blobs={m.blobs}")
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
