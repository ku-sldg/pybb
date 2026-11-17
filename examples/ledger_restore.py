"""
Restore tooling for the ledger mirror (docs/ledger_plan.md H.4).

    python examples/ledger_restore.py verify  CLONE
    python examples/ledger_restore.py replay  CLONE --into FILE | --into-immudb
    python examples/ledger_restore.py exact   CLONE --db pybb --out restore.bkp

verify: record files re-hash to the journal, the journal is contiguous, and
every present blob hashes to its name (H.4 step 1).
replay: content restore, one batch per journal line, into a fresh FileLedger
or the configured immudb database (H.4 step 3); appends a restore record.
exact:  concatenates ledger/backups/* and prints the `immuadmin hot-restore`
command for an identical-tx-id restore (H.4 step 2; needs an immuadmin login).
"""
import argparse
import sys
from pathlib import Path

from pybb.attestation import FileLedger
from pybb.attestation.ledger import LedgerConfig
from pybb.attestation.ledger_repo import EvidenceRepo, exact_restore_command, record_restore, replay, verify_mirror


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["verify", "replay", "exact"])
    ap.add_argument("clone", help="path of the evidence repo clone at the commit to restore from")
    ap.add_argument("--into", help="replay target: a FileLedger path")
    ap.add_argument("--into-immudb", action="store_true", help="replay target: immudb from the environment")
    ap.add_argument("--db", default="pybb")
    ap.add_argument("--out", default="restore.bkp")
    args = ap.parse_args()
    clone = Path(args.clone)
    if args.action == "verify":
        rep = verify_mirror(clone)
        print(f"txs={rep.txs} records={rep.records} blobs_checked={rep.blobs_checked} problems={len(rep.problems)}")
        for p in rep.problems:
            print("PROBLEM:", p)
        return 0 if rep else 1
    if args.action == "replay":
        config = LedgerConfig()
        if args.into:
            ledger = FileLedger(args.into)
        elif args.into_immudb:
            from pybb.attestation import ImmudbLedger
            ledger = ImmudbLedger(config)
        else:
            ap.error("replay needs --into FILE or --into-immudb")
        n = replay(clone, ledger)
        last_state = max((int(p.stem) for p in (clone / "ledger/state").glob("*.json")), default=0)
        rec = record_restore(ledger, EvidenceRepo(clone), "replay", last_state, n, config)
        print(f"replayed {n} txs; restore record {rec.created_at}")
        return 0
    segs = sorted((clone / "ledger/backups").glob("*")) if (clone / "ledger/backups").is_dir() else []
    if not segs:
        sys.exit("no backup segments under ledger/backups/; use replay")
    cmd = exact_restore_command(args.db, segs, Path(args.out))
    print("run (after `immuadmin login immudb`):", " ".join(cmd))
    print("then: python examples/ledger_restore.py verify", clone, "and check every key with verifiedGet using the old client state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
