"""
Walk a ledger-held bundle and appraise it again (docs/ledger_plan.md,
sections B.5, B.6, E, K.4).

    python examples/appraise_from_ledger.py <bid>
    python examples/appraise_from_ledger.py --latest <protocol_id>
    python examples/appraise_from_ledger.py <bid> --session PATH

Prints the bundle graph — the bundle, every appraisal recorded over it
(`judged_by/`), and the appraisals of those — then runs a fresh signed
appraisal of the bundle through the CVM and records it as one more
appraisal bundle. There are no kinds of appraisal: live, first-later and
audit are positions in the chain, and each appraisal's `golden_provenance`
says where its goldens came from. A measurement bundle is judged by the
protocol's companions (or by --session, a different policy); an appraisal bundle is
judged inside the CVM (its signature, appraiser nonce and binding); a
`stack` or `config` bundle is judged against a blessing's goldens or the
hashes of its archived files (--against picks the blessing). Beside every
run bundle the graph shows the stack and configuration in force, derived
from the same writer's earlier records (docs/ledger_plan.md O.7).

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
from pybb.attestation.ledger_context import derive_context, verify_claim
from pybb.attestation.ledger_runs import appraise_bundle, archiver

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
    print(f"{indent}  rawev_count={b.rawev_count} signed_by={b.signature.asp} nonce_asp={b.nonce.asp if b.nonce else None}")
    print(f"{indent}  blob_sha256={b.blob.blob_sha256}  rawev_sha256={b.rawev_sha256}")
    for loc in b.blob.locations:
        print(f"{indent}  location {loc.store}: {loc.path}")
    for i in b.inputs or []:
        print(f"{indent}  input {i.bid[:16]}…  binding_hash {(i.binding_hash or '')[:16]}…")
    if b.role in ("stack", "config"):
        info = b.stack or b.config
        extra = f" executables={b.stack.executables} plc={b.stack.plc}" if b.stack else \
            f" constructors={len(b.config.constructors)} files={len(b.config.files)}"
        blessing = ledger.blessing_of(b.key_id) if b.role == "stack" else None
        print(f"{indent}  {b.role}:{extra}{'  blessed: ' + blessing.created_at if blessing else ''}")
    else:
        d = derive_context(ledger, b)
        print(f"{indent}  context: stack={d.stack_bid[:16] + '…' if d.stack_bid else '-'} ({d.stack_status}) "
              f"config={d.config_bid[:16] + '…' if d.config_bid else '-'} inputs={d.status}"
              f"{' via ' + d.constructor if d.constructor else ''}"
              f"{' pins=' + str(d.pins) if d.status == 'stale' else ''}")
        if b.claim is not None and (b.claim.stack_bid or b.claim.config_bid):
            v = verify_claim(ledger, b)
            print(f"{indent}  claim: stack={b.claim.stack_bid[:16]}… config={b.claim.config_bid[:16]}… "
                  f"fresh={b.claim.fresh} policy={b.claim.policy} check={'consistent' if v else 'PROBLEMS ' + '; '.join(v.problems)}")
    if b.verdict is not None:
        v = b.verdict
        print(f"{indent}  verdict: passed={v.passed} components={v.components_total} "
              f"failed={v.components_failed} interpreter={v.interpreter.kind}")
        for g in b.golden_provenance or []:
            print(f"{indent}  goldens from {g.source}{' ' + g.ref if g.ref else ''}"
                  f"{' for ' + ', '.join(g.targets) if g.targets else ''}{' (' + g.asp + ')' if g.asp else ''}")
        for f in v.failing:
            print(f"{indent}    FAIL {f.targ_id} ({f.appr_asp}): {f.reason}")
    for a in ledger.appraisals_of(b.key_id):
        show_bundle(ledger, a.key_id, indent + "    ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bid", nargs="?", help="bundle id (sha256 of its nonce)")
    ap.add_argument("--latest", metavar="PROTOCOL_ID", help="most recent measurement bundle of this protocol")
    ap.add_argument("--session", help="session JSON overriding the protocol's (a different appraisal policy)")
    ap.add_argument("--ledger", help="FileLedger path (default: immudb from the environment)")
    ap.add_argument("--archive-dir", default=str(REPO / "evidence"),
                    help="where the new appraisal package is archived (default: evidence/)")
    ap.add_argument("--against", help="stack audits: the blessing key (or stack bid) whose goldens to judge against")
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
    protocol = None
    if target.role not in ("stack", "config"):  # context bundles bring their own protocol
        proto_dir = FIXTURES / target.protocol_id
        if not (proto_dir / "session.json").is_file():
            sys.exit(f"no protocol dir at {proto_dir}")
        protocol = ProtocolDir.load(str(proto_dir))
    session = json.loads(Path(args.session).read_text()) if args.session else None
    print(f"\n== signed appraisal of {target.role} bundle {bid[:16]}… ==")
    rep = appraise_bundle(CvmSubprocessClient(), protocol, ledger, config, bid,
                          session_override=session, archive=archiver(args.archive_dir), against=args.against)
    if rep.error:
        print("ERROR:", rep.error)
        return 1
    print(f"recorded as {rep.ledger_ref}: passed={rep.passed} signature_ok={rep.signature_ok} "
          f"nonce_wellformed={rep.nonce_wellformed} binding_ok={rep.binding_ok} assurance={rep.assurance}")
    for g in rep.golden_provenance:
        print(f"  goldens from {g.source}{' ' + g.ref if g.ref else ''}")
    for c in rep.components:
        print(f"  {c.appr_asp:18s} over {c.target_asp:16s} targ={c.targ_id!s:40s} {'pass' if c.passed else 'FAIL ' + c.reason}")
    return 0 if rep else 1


if __name__ == "__main__":
    sys.exit(main())
