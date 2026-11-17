"""
Walk a ledger-held attestation run and re-appraise it (docs/ledger_plan.md,
sections B.5, B.6, E).

    python examples/appraise_from_ledger.py <nid>
    python examples/appraise_from_ledger.py --latest <protocol_id>
    python examples/appraise_from_ledger.py --audit-appraisal <nid> [--seq N]

Prints the chain nonce -> evidence -> live appraisal -> verdict (with
ledger tx ids where the backend exposes them), then runs a fresh signed
appraisal of the raw package through the CVM, or — with
--audit-appraisal — a CVM-native audit of a recorded appraisal package,
and appends the result to the ledger.

Backend: --ledger FILE for a FileLedger, otherwise immudb from the
environment (PYBB_IMMUDB_USER / PYBB_IMMUDB_PASSWORD, host 127.0.0.1:3322,
db pybb). Protocol dirs are looked up under tests/fixtures/<protocol_id>.
"""

import argparse
import sys
from pathlib import Path

from pybb.attestation import CvmSubprocessClient, FileLedger, ProtocolDir
from pybb.attestation.ledger import LedgerConfig
from pybb.attestation.ledger_runs import appraise_record, audit_appraisal_package

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"


def open_ledger(args, config):
    if args.ledger:
        return FileLedger(args.ledger)
    from pybb.attestation import ImmudbLedger

    return ImmudbLedger(config)


def latest_nid(ledger, protocol_id: str) -> str:
    nid, latest = "", ""
    for rec in ledger.records(kind="evidence", protocol_id=protocol_id):
        if rec.created_at >= latest:
            latest, nid = rec.created_at, rec.nid
    if not nid:
        sys.exit(f"no evidence records for protocol {protocol_id}")
    return nid


def tx(ledger, key: str) -> str:
    fn = getattr(ledger, "tx_of", None)
    t = fn(key) if fn else None
    return f"  [tx {t}]" if t is not None else ""


def show_chain(ledger, nid: str) -> None:
    run = ledger.get(nid)
    n, ev, vd = run.nonce, run.evidence, run.verdict
    print(f"nonce/{nid}{tx(ledger, f'nonce/{nid}')}")
    print(f"  role={n.role} state={n.state} freshness={n.freshness} protocol={n.protocol_id} at {n.created_at}")
    print(f"evidence/{nid}{tx(ledger, f'evidence/{nid}')}")
    print(f"  assurance={ev.assurance} rawev_count={ev.rawev_count} sig_slot={ev.signature.slot} nonce_slot={ev.nonce.slot}")
    print(f"  blob_sha256={ev.blob_sha256}  rawev_sha256={ev.rawev_sha256}")
    for loc in ev.locators:
        print(f"  locator {loc.kind}: {loc.path}")
    for a in run.appraisals:
        tag = f"audit of seq {a.audits_seq}" if a.audits_seq else a.mode
        print(f"appraisal/{nid}/{a.seq}{tx(ledger, f'appraisal/{nid}/{a.seq}')}  {tag}")
        print(f"  anid={a.anid[:16]}… passed={a.passed} assurance={a.assurance} interpreter={a.interpreter.kind}")
        print(f"  binding slot {a.binding.slot} = {a.binding.evidence_hash[:16]}…"
              f"  matches_evidence={a.binding.matches_evidence}  agrees={a.agrees_with_recorded_verdict}")
    print(f"verdict/{nid}{tx(ledger, f'verdict/{nid}')}")
    print(f"  passed={vd.passed} components={vd.components_total} failed={vd.components_failed}"
          f" evidence_assurance={vd.evidence_assurance} appraisal_assurance={vd.appraisal_assurance}")
    for f in vd.failing:
        print(f"    FAIL {f.targ_id} ({f.appr_asp}): {f.reason}")
    for l in run.locators:
        print(f"locator/{nid}/{l.seq}  {l.target} {l.locator.kind}: {l.locator.path} verified={l.verified}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nid", nargs="?", help="nonce id of the run")
    ap.add_argument("--latest", metavar="PROTOCOL_ID", help="most recent run of this protocol")
    ap.add_argument("--audit-appraisal", action="store_true",
                    help="audit the recorded appraisal package (B.6) instead of re-appraising the raw package")
    ap.add_argument("--seq", type=int, default=1, help="appraisal seq to audit (with --audit-appraisal)")
    ap.add_argument("--ledger", help="FileLedger path (default: immudb from the environment)")
    ap.add_argument("--no-run", action="store_true", help="show the chain only; run nothing")
    args = ap.parse_args()

    config = LedgerConfig()
    ledger = open_ledger(args, config)
    nid = args.nid or (latest_nid(ledger, args.latest) if args.latest else None)
    if not nid:
        ap.error("give a nid or --latest PROTOCOL_ID")
    show_chain(ledger, nid)
    if args.no_run:
        return 0

    protocol_id = ledger.get(nid).evidence.protocol_id
    proto_dir = FIXTURES / protocol_id
    if not (proto_dir / "session.json").is_file():
        sys.exit(f"no protocol dir at {proto_dir}")
    protocol = ProtocolDir.load(str(proto_dir))
    client = CvmSubprocessClient()
    if args.audit_appraisal:
        print(f"\n== CVM-native audit of appraisal seq {args.seq} ==")
        rep = audit_appraisal_package(client, protocol, ledger, config, nid, seq=args.seq)
    else:
        print("\n== fresh signed appraisal of the raw package ==")
        rep = appraise_record(client, protocol, ledger, config, nid)
    if rep.error:
        print("ERROR:", rep.error)
        return 1
    print(f"recorded as {rep.ledger_ref}: passed={rep.passed} signature_ok={rep.signature_ok} "
          f"nonce_wellformed={rep.nonce_wellformed} binding_ok={rep.binding_ok} "
          f"agrees_with_recorded_verdict={rep.agrees_with_recorded_verdict} assurance={rep.assurance}")
    for c in rep.components:
        print(f"  {c.appr_asp:18s} over {c.target_asp:16s} targ={c.targ_id!s:40s} {'pass' if c.passed else 'FAIL ' + c.reason}")
    return 0 if rep else 1


if __name__ == "__main__":
    sys.exit(main())
