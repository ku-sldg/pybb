"""
Operator commands for the run context (docs/ledger_plan.md, section O):
Copland evidence of the CVM/asp-libs installation (`stack`) and of each
protocol's exact inputs (`config`), and the operator's blessing of a stack.

    python examples/ledger_context.py measure stack [--bless] [--note "..."]
    python examples/ledger_context.py measure config <protocol_id>... | --all
    python examples/ledger_context.py bless <stack bid> [--note "..."]
    python examples/ledger_context.py audit <bid> [--against <blessing key>] [--kind LABEL]
    python examples/ledger_context.py show [<bid> | --latest <protocol_id>]
    python examples/ledger_context.py list

`measure` runs the CVM once over the live files and COMMITS UNCONDITIONALLY:
you asked for a fresh signed statement of the state at this moment. When to
run it is your process — after rebuilding asp-libs or the CVM, after editing
a protocol, from cron or CI. pybb never measures the stack or the inputs on
its own and reads nothing from the ledger at run time; runs carry no pointer
to any of this. `show` prints what a reader derives for a run bundle: the
same writer's latest stack and config bundles at a lower transaction, and
whether the run's term/session/manifest hashes match that config.

Backend: --ledger FILE for a FileLedger, otherwise immudb from the
environment (db PYBB_IMMUDB_DB, default pybb2). Protocol dirs are looked up
under tests/fixtures/<protocol_id>.
"""

import argparse
import sys
from pathlib import Path

from pybb.attestation import CvmSubprocessClient, FileLedger, ProtocolDir
from pybb.attestation.ledger import LedgerConfig
from pybb.attestation.ledger_context import bless, blessings, derive_context, measure_config, measure_stack
from pybb.attestation.ledger_runs import appraise_bundle, archiver

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def open_ledger(args, config):
    if args.ledger:
        return FileLedger(args.ledger)
    from pybb.attestation import ImmudbLedger

    return ImmudbLedger(config)


def all_protocol_ids() -> list:
    return sorted(p.name for p in FIXTURES.iterdir()
                  if (p / "session.json").is_file() and not p.name.startswith("attestation_"))


def short(bid: str) -> str:
    return bid[:16] + "…" if bid else "-"


def cmd_measure(args, ledger, config) -> int:
    client = CvmSubprocessClient()
    archive = archiver(args.archive_dir)
    if args.what == "stack":
        m = measure_stack(client, ledger, config, archive=archive)
        if not m:
            print("ERROR:", m.error)
            return 1
        print(f"stack bundle {m.ledger_ref}  targets={m.targets}  archived {m.evidence_ref}")
        if args.bless:
            rec = bless(ledger, config, m.bid, note=args.note or "")
            print(f"blessed: blessing/{rec.stack_bid}  goldens={len(rec.goldens)}")
        return 0
    pids = all_protocol_ids() if args.all else args.protocol_ids
    if not pids:
        print("measure config: give protocol ids or --all")
        return 2
    rc = 0
    for pid in pids:
        proto_dir = FIXTURES / pid
        if not (proto_dir / "session.json").is_file():
            print(f"{pid}: no protocol dir at {proto_dir}")
            rc = 1
            continue
        m = measure_config(client, ProtocolDir.load(str(proto_dir)), ledger, config, archive=archive)
        if m:
            print(f"config bundle {m.ledger_ref}  protocol={pid}  files={m.targets}")
        else:
            print(f"{pid}: ERROR {m.error}")
            rc = 1
    return rc


def cmd_bless(args, ledger, config) -> int:
    rec = bless(ledger, config, args.bid, note=args.note or "")
    print(f"blessing/{rec.stack_bid}  goldens={len(rec.goldens)}  by {rec.appraiser_id} at {rec.created_at}")
    return 0


def cmd_audit(args, ledger, config) -> int:
    target = ledger.get(args.bid)
    if target.role not in ("stack", "config"):
        print(f"{args.bid[:16]}… is a {target.role} bundle; use examples/appraise_from_ledger.py")
        return 2
    rep = appraise_bundle(CvmSubprocessClient(), None, ledger, config, args.bid, appraisal_kind=args.kind,
                          archive=archiver(args.archive_dir), baseline=args.against)
    if rep.error:
        print("ERROR:", rep.error)
        return 1
    print(f"recorded as {rep.ledger_ref}: passed={rep.passed} signature_ok={rep.signature_ok} "
          f"nonce_wellformed={rep.nonce_wellformed}{' baseline=' + rep.baseline if rep.baseline else ''}")
    for c in rep.components:
        print(f"  {c.appr_asp:18s} targ={c.targ_id!s:44s} {'pass' if c.passed else 'FAIL ' + c.reason}")
    return 0 if rep else 1


def cmd_show(args, ledger, config) -> int:
    if args.latest:
        cands = ledger.bundles(protocol_id=args.latest, role="measurement")
        if not cands:
            print(f"no measurement bundles for {args.latest}")
            return 1
        bid = cands[-1].key_id
    elif args.bid:
        bid = args.bid
    else:
        print("show: give a bid or --latest PROTOCOL_ID")
        return 2
    b = ledger.get(bid)
    d = derive_context(ledger, b)
    print(f"bundle/{b.key_id}  role={b.role} protocol={b.protocol_id} shape={b.shape} writer={b.appraiser_id}"
          f"{'  tx ' + str(d.tx) if d.tx is not None else ''}")
    print(f"  stack in force : {short(d.stack_bid)}  {d.stack_status}"
          f"{'  (' + d.blessing_key + ')' if d.blessing_key else ''}")
    print(f"  config in force: {short(d.config_bid)}  inputs {d.status}"
          f"{'  via constructor ' + d.constructor if d.constructor else ''}")
    if d.pins:
        print(f"  pins           : {d.pins}")
    return 0


def cmd_list(args, ledger, config) -> int:
    for role in ("stack", "config"):
        for b in ledger.bundles(role=role):
            extra = f"executables={b.stack.executables}" if b.stack else \
                f"protocol={b.protocol_id} files={len(b.config.files) if b.config else 0}"
            bl = ledger.blessing_of(b.key_id) if role == "stack" else None
            print(f"{role:6s} bundle/{b.key_id}  {b.created_at}  by {b.appraiser_id}  {extra}"
                  f"{'  BLESSED ' + bl.created_at if bl else ''}")
    for _tx, key, rec in blessings(ledger):
        print(f"bless  {key}  {rec.created_at}  by {rec.appraiser_id}  goldens={len(rec.goldens)}"
              f"{'  ' + rec.note if rec.note else ''}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", help="FileLedger path (default: immudb from the environment)")
    ap.add_argument("--archive-dir", default=str(REPO / "evidence"), help="where packages are archived")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure", help="measure the stack or protocol configurations (always commits)")
    m.add_argument("what", choices=["stack", "config"])
    m.add_argument("protocol_ids", nargs="*")
    m.add_argument("--all", action="store_true", help="config: every protocol under tests/fixtures")
    m.add_argument("--bless", action="store_true", help="stack: bless the new bundle in the same step")
    m.add_argument("--note", help="blessing note")
    b = sub.add_parser("bless", help="approve a stack bundle")
    b.add_argument("bid")
    b.add_argument("--note")
    a = sub.add_parser("audit", help="appraise a stack or config bundle inside the CVM")
    a.add_argument("bid")
    a.add_argument("--against", help="blessing key (or stack bid) for a stack audit; default the latest")
    a.add_argument("--kind", default=None, help="appraisal_kind label (default deferred/audit)")
    s = sub.add_parser("show", help="what a reader derives for a run bundle")
    s.add_argument("bid", nargs="?")
    s.add_argument("--latest", metavar="PROTOCOL_ID")
    sub.add_parser("list", help="stack and config bundles and blessings")
    args = ap.parse_args()

    config = LedgerConfig()
    ledger = open_ledger(args, config)
    return {"measure": cmd_measure, "bless": cmd_bless, "audit": cmd_audit,
            "show": cmd_show, "list": cmd_list}[args.cmd](args, ledger, config)


if __name__ == "__main__":
    sys.exit(main())
