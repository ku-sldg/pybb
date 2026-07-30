"""
Audit the signed golden baselines: for every provisioned protocol, verify
the stored provision bundle via an appraisal-only CVM run (the CVM's own
appraisal semantics check the RSA signature over the evidence and anchor
each installed golden_b64 to the signed bytes) and print the evidence
chain.

Usage:
    python examples/verify_baseline.py [protocol_id ...]

With no arguments, audits every protocol that has a bundle under
golden/_bundles/ and a protocol dir under tests/fixtures/. Exit status 1
if any baseline fails.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from pybb.attestation import CvmSubprocessClient, ProtocolDir, verify_bundle

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
PUBKEY = Path.home() / "Claude_workspace/asp-libs/common_files/unsecure_pub_key_dont_use.pem"


def key_identity() -> str:
    """Fingerprint of the verifying public key (the copy baked into the
    sig/sig_appr ASP binaries at build time). The demo pair's name says it
    all — key custody is the trust root and is tracked as a follow-up."""
    if not PUBKEY.is_file():
        return "public key file not found (verification uses the copy baked into sig_appr)"
    fp = hashlib.sha256(PUBKEY.read_bytes()).hexdigest()[:16]
    return f"sha256:{fp} ({PUBKEY.name} — DEMO key, custody follow-up pending)"


def discover() -> list[str]:
    bundles = GOLDEN_ROOT / "_bundles"
    if not bundles.is_dir():
        return []
    return sorted(p.name for p in bundles.iterdir()
                  if (p / "provision_bundle.json").is_file()
                  and (FIXTURES / p.name / "session.json").is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocols", nargs="*", help="protocol ids (default: all with bundles)")
    cli = parser.parse_args()
    pids = cli.protocols or discover()
    if not pids:
        print("no signed baselines found")
        return 1

    print(f"verifying key: {key_identity()}\n")
    client = CvmSubprocessClient()
    # every auditable protocol serves as an anchor source: blessed
    # whole-file (props) baselines are checked against the hash and slice
    # goldens the other protocols install for the same files
    anchors = {pid: ProtocolDir.load(str(FIXTURES / pid)) for pid in pids
               if (FIXTURES / pid / "session.json").is_file()}
    failures = 0
    for pid in pids:
        proto_dir = FIXTURES / pid
        if not (proto_dir / "session.json").is_file():
            print(f"{pid}: FAILED\n  no protocol dir at {proto_dir}")
            failures += 1
            continue
        protocol = anchors[pid]
        report = verify_bundle(client, protocol, GOLDEN_ROOT,
                               anchor_protocols=anchors)
        total = sum(
            len(targets) for asp_id, targets in protocol.asp_args.items()
            if asp_id in {
                a for a, c in protocol.session.get("Session_Context", {})
                .get("ASP_Comps", {}).items()
                if c in ("goldenbytes_appr", "goldenevidence_appr")})
        stamps = sorted({args.get("golden_ts", "")
                         for targets in protocol.asp_args.values()
                         for args in targets.values()
                         if args.get("golden_ts")})
        if report:
            print(f"{pid}: VERIFIED")
            print(f"  bundle:  {Path(report.bundle_path).relative_to(REPO)}")
            print(f"  goldens: {len(report.anchored)}/{total} anchored to signed evidence"
                  + (f" (provisioned {stamps[-1]})" if stamps else ""))
        else:
            failures += 1
            print(f"{pid}: FAILED")
            for p in report.problems:
                print(f"  ! {p}")
    print(f"\n{len(pids) - failures}/{len(pids)} baselines verified")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
