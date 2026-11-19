"""
Walk a ledger-held bundle and appraise it again (docs/ledger_plan.md,
sections B.5, B.6, E, K.4).

    python examples/appraise_from_ledger.py <bid>
    python examples/appraise_from_ledger.py --latest <protocol_id>
    python examples/appraise_from_ledger.py <bid> --kind slices-only --session PATH

Prints the bundle graph — the bundle, every appraisal recorded over it
(`judged_by/`), and the appraisals of those — then runs a fresh signed
appraisal of the bundle through the CVM and records it as one more
appraisal bundle. A measurement bundle is judged by the protocol's
companions (or by --session, a different policy); an appraisal bundle is
judged inside the CVM (its signature, appraiser nonce and binding).

Backend: --ledger FILE for a FileLedger, otherwise immudb from the
environment (PYBB_IMMUDB_USER / PYBB_IMMUDB_PASSWORD, host 127.0.0.1:3322,
db PYBB_IMMUDB_DB, default pybb2). Protocol dirs are looked up under
tests/fixtures/<protocol_id>.
"""

import argparse
import json
import sys
from pathlib import Path

from pybb.attestation import CvmSubprocessClient, FileLedger, ProtocolDir
from pybb.attestation.ledger import LedgerConfig
from pybb.attestation.ledger_runs import appraise_bundle

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def open_ledger(args, config):
    if args.ledger:
        return FileLedger(args.ledger)
    from pybb.attestation import ImmudbLedger

    return ImmudbLedger(config)


def latest_bid(ledger, protocol_id: str) -> str:
    bid, latest = "", ""
    for rec in ledger.bundles(protocol_id=protocol_id, role="measurement"):
        if rec.created_at >= latest:
            latest, bid = rec.created_at, rec.key_id
    if not bid:
        sys.exit(f"no measurement bundles for protocol {protocol_id}")
    return bid


def tx(ledger, key: str) -> str:
    fn = getattr(ledger, "tx_of", None)
    t = fn(key) if fn else None
    return f"  [tx {t}]" if t is not None else ""


def show_bundle(ledger, bid: str, indent: str = "") -> None:
    b = ledger.get(bid)
    key = f"bundle/{b.key_id}"
    print(f"{indent}{key}{tx(ledger, key)}")
    print(f"{indent}  role={b.role} protocol={b.protocol_id} assurance={b.assurance} freshness={b.freshness} at {b.created_at}")
    print(f"{indent}  rawev_count={b.rawev_count} sig_slot={b.signature.slot} nonce_slot={b.nonce.slot if b.nonce else None}")
    print(f"{indent}  blob_sha256={b.blob.blob_sha256}  rawev_sha256={b.rawev_sha256}")
    for loc in b.blob.locations:
        print(f"{indent}  location {loc.store}: {loc.path}")
    for i in b.inputs or []:
        print(f"{indent}  input {i.bid[:16]}…  binding slot {i.binding_slot} = {(i.binding_hash or '')[:16]}…")
    if b.verdict is not None:
        v = b.verdict
        print(f"{indent}  verdict[{b.appraisal_kind}]: passed={v.passed} components={v.components_total} "
              f"failed={v.components_failed} interpreter={v.interpreter.kind} checks={v.checks} "
              f"agrees_with_live={v.agrees_with_live}")
        for f in v.failing:
            print(f"{indent}    FAIL {f.targ_id} ({f.appr_asp}): {f.reason}")
    for a in ledger.appraisals_of(b.key_id):
        show_bundle(ledger, a.key_id, indent + "    ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bid", nargs="?", help="bundle id (sha256 of its nonce)")
    ap.add_argument("--latest", metavar="PROTOCOL_ID", help="most recent measurement bundle of this protocol")
    ap.add_argument("--kind", default="audit", help="appraisal_kind label for the new appraisal bundle")
    ap.add_argument("--session", help="session JSON overriding the protocol's (a different appraisal policy)")
    ap.add_argument("--ledger", help="FileLedger path (default: immudb from the environment)")
    ap.add_argument("--no-run", action="store_true", help="show the graph only; run nothing")
    args = ap.parse_args()

    config = LedgerConfig()
    ledger = open_ledger(args, config)
    bid = args.bid or (latest_bid(ledger, args.latest) if args.latest else None)
    if not bid:
        ap.error("give a bid or --latest PROTOCOL_ID")
    show_bundle(ledger, bid)
    if args.no_run:
        return 0

    target = ledger.get(bid)
    proto_dir = FIXTURES / target.protocol_id
    if not (proto_dir / "session.json").is_file():
        sys.exit(f"no protocol dir at {proto_dir}")
    protocol = ProtocolDir.load(str(proto_dir))
    session = json.loads(Path(args.session).read_text()) if args.session else None
    print(f"\n== signed appraisal of {target.role} bundle {bid[:16]}… ({args.kind}) ==")
    rep = appraise_bundle(CvmSubprocessClient(), protocol, ledger, config, bid,
                          session_override=session, appraisal_kind=args.kind)
    if rep.error:
        print("ERROR:", rep.error)
        return 1
    print(f"recorded as {rep.ledger_ref}: passed={rep.passed} signature_ok={rep.signature_ok} "
          f"nonce_wellformed={rep.nonce_wellformed} binding_ok={rep.binding_ok} "
          f"agrees_with_live={rep.agrees_with_live} assurance={rep.assurance}")
    for c in rep.components:
        print(f"  {c.appr_asp:18s} over {c.target_asp:16s} targ={c.targ_id!s:40s} {'pass' if c.passed else 'FAIL ' + c.reason}")
    return 0 if rep else 1


if __name__ == "__main__":
    sys.exit(main())
