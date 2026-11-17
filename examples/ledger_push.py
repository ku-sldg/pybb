"""
Push the ledger's local artifacts to the evidence repo (docs/ledger_plan.md H.2).

    python examples/ledger_push.py [--archive-dir DIR] [--no-push] [--backup-segment FILE]
                                   [--bundles GOLDEN_ROOT] [--ledger FILE]

Copies pending blobs and every record into the clone named by
PYBB_EVIDENCE_REPO (or LedgerConfig.evidence_repo), appends the journal and
a state snapshot, commits once, pushes, and appends `github` locator
records. With --bundles, first backfills `bundle` records for the provision
bundles under GOLDEN_ROOT/_bundles whose protocol dirs exist under
tests/fixtures.
"""
import argparse
import sys
from pathlib import Path

from pybb.attestation import FileLedger, ProtocolDir
from pybb.attestation.ledger import LedgerConfig
from pybb.attestation.ledger_repo import EvidenceRepo, commit_bundles, push_archive

REPO = Path(__file__).parent.parent


def open_ledger(args, config):
    if args.ledger:
        return FileLedger(args.ledger)
    from pybb.attestation import ImmudbLedger
    return ImmudbLedger(config)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive-dir", help="only blobs under this directory")
    ap.add_argument("--no-push", action="store_true", help="commit locally, do not push")
    ap.add_argument("--backup-segment", help="immuadmin hot-backup segment to add under ledger/backups/")
    ap.add_argument("--bundles", metavar="GOLDEN_ROOT", help="backfill bundle records first")
    ap.add_argument("--ledger", help="FileLedger path (default: immudb from the environment)")
    args = ap.parse_args()
    config = LedgerConfig()
    if not config.evidence_repo:
        sys.exit("set PYBB_EVIDENCE_REPO to the path of your evidence repo clone")
    ledger = open_ledger(args, config)
    repo = EvidenceRepo(config.evidence_repo)
    if args.bundles:
        fixtures = REPO / "tests" / "fixtures"
        protocols = {p.name: ProtocolDir.load(str(p)) for p in sorted(fixtures.iterdir())
                     if (p / "session.json").is_file()}
        keys = commit_bundles(ledger, args.bundles, protocols, config)
        print(f"bundle records committed: {len(keys)}")
    rep = push_archive(ledger, repo, config,
                       archive_dir=Path(args.archive_dir) if args.archive_dir else None,
                       push=not args.no_push,
                       backup_segment=Path(args.backup_segment) if args.backup_segment else None)
    print(f"commit {rep.commit[:12]} committed={rep.committed} pushed={rep.pushed} "
          f"blobs={len(rep.blobs)} skipped={len(rep.skipped)} journal txs {rep.journal_from_tx}-{rep.journal_to_tx} "
          f"state tx {rep.state_tx} locators appended={rep.locators_appended}")
    for p in rep.problems:
        print("PROBLEM:", p)
    return 1 if rep.problems else 0


if __name__ == "__main__":
    sys.exit(main())
