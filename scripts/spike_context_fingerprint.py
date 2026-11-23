"""Spike (plan P): a CVM-computed stack fingerprint.

Term:  lseq (bseq left_path nonce
                  (bseq both_paths (lseq M_bin hashevidence[EXTEND]) M_settings))
            SIG
M_bin      = hashfile chain over the binaries + key, sorted by target id
M_settings = hashfile over the run's own term/session/manifest files and cvm_config.json
RawEv (expected): [sig, nonce, H_bin, h_1..h_n, h_term, h_session, h_manifest, h_invocation]

Checks: (A) layout + H_bin == sha256(h_1‖…‖h_n) [SPIKE-ONLY python hashing, to
confirm the CVM semantics]; (B) repeat → same H_bin; (C) relocate asp_bin →
same H_bin, different h_term; (D) add / rename a file → different H_bin;
(E) CVM audit: appraise term with goldens injected (per target + H_bin) →
all pass; perturb one target golden → fails by name; perturb H golden → the
hashevidence component fails; (F) the real full stack once.
"""
import base64, copy, hashlib, json, os, shutil, sys, tempfile
from pathlib import Path

from pybb.attestation import CvmSubprocessClient, ProtocolDir
from pybb.attestation.client import CvmConfig
from pybb.attestation.ledger import APPRAISER_NONCE_TARGID, canonical_json, describe_package, sha256_hex, slot_layout
from pybb.attestation.ledger_context import context_manifest, context_session, hashfile_targets
from pybb.attestation.ledger_runs import (
    HASHEVIDENCE_KEEP, _SIG, _asp, _bseq, _lseq, _request, _run, appraisal_term, inject_goldens,
    interpret_appraisal, ledger_protocol, measurement_request)
from pybb.attestation.tools import _hashfile_chain

client = CvmSubprocessClient()
real = CvmConfig()
work = Path(tempfile.mkdtemp(prefix="spike_fp_"))
ASPS = ("hashfile", "sig", "sig_appr", "goldenbytes_appr", "generate_nonce", "nonce_appr", "hashevidence", "magic_appr")


def ext_session():
    s = context_session()
    s["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
    return s


def build(asp_bin: Path, run_dir: Path, pubkey: str):
    """The stack protocol over `asp_bin`; writes the settings files (term fixed point) into run_dir."""
    run_dir.mkdir(parents=True, exist_ok=True)
    files = {"stack:cvm": Path(real.cvm_binary).resolve(), "stack:pubkey": Path(pubkey).resolve()}
    for p in sorted(asp_bin.iterdir()):
        if p.is_file() and os.access(p, os.X_OK):
            files[f"stack:asp:{p.name}"] = p.resolve()
    settings = {"stack:term": run_dir / "term.json", "stack:session": run_dir / "session.json",
                "stack:manifest": run_dir / "manifest.json", "stack:invocation": run_dir / "cvm_config.json"}
    (run_dir / "cvm_config.json").write_bytes(canonical_json(real.model_dump(mode="json")))
    t_bin = hashfile_targets(dict(sorted(files.items())), "stack::bin")
    t_set = hashfile_targets(settings, "stack::settings")
    m = _bseq("both_paths", _lseq(_hashfile_chain(t_bin), _asp("hashevidence", {})), _hashfile_chain(t_set))
    term = _lseq(m, _SIG)
    proto = ProtocolDir(protocol_id="attestation_stack", path="", term=term, session=context_session(),
                        manifest=context_manifest(), asp_args={"hashfile": {**t_bin, **t_set}})
    lp = ledger_protocol(proto)
    # EXTEND typing must be applied AFTER ledger_protocol (which re-applies the ledger's REPLACE default),
    # exactly as combined_session does; otherwise the CVM runs REPLACE and erases the digests beneath H
    sess = copy.deepcopy(lp.session)
    sess["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
    lp = lp.model_copy(update={"session": sess})
    req = measurement_request(lp)
    # fixed point: the files the term names hold exactly the request's TERM / SESSION and the manifest
    (run_dir / "term.json").write_bytes(canonical_json(req["TERM"]))
    (run_dir / "session.json").write_bytes(canonical_json(req["ATTESTATION_SESSION"]))
    (run_dir / "manifest.json").write_bytes(canonical_json(lp.manifest))
    return lp, req, files, settings


def measure(lp, req):
    resp = _run(client, lp, req)
    assert resp.get("SUCCESS"), resp
    return resp["PAYLOAD"]


def read(payload, session):
    """pybb-style reading: slots by layout, no hashing."""
    desc = describe_package(payload, session)
    raw = payload[0]["RawEv"]
    spans = slot_layout(payload[1], session)
    H = next(s for s in spans if s.asp == "hashevidence" and not s.input)
    beneath = [s for s in spans if s.input and s.asp == "hashfile"]  # digests beneath H, in order
    settings = {s.asp_targid: raw[s.start] for s in spans if s.asp == "hashfile" and not s.input}
    return desc, raw[H.start], [raw[s.start] for s in beneath], {s.asp_targid: raw[s.start] for s in beneath}, settings


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        global failures
        failures += 1


failures = 0
pub = str(Path(os.path.expanduser("~/Claude_workspace/asp-libs/common_files/unsecure_pub_key_dont_use.pem")))
asps1 = work / "asps1"; asps1.mkdir()
for n in ASPS:
    shutil.copy2(Path(real.asp_bin) / n, asps1 / n)

print("A. one measurement: layout and semantics")
lp1, req1, files1, set1 = build(asps1, work / "run1", pub)
p1 = measure(lp1, req1)
d1, H1, digests1, bybin1, bysettings1 = read(p1, lp1.session)
n = len(files1)
check(d1.bid is not None and d1.signature.present and d1.assurance == "signed+nonce", f"describable, signed+nonce, {d1.rawev_count} slots")
check(d1.rawev_count == 2 + 1 + n + 4, f"slot count = sig+nonce+H+{n} digests+4 settings")
check(len(digests1) == n, f"{n} digests beneath H in term order")
spike_only = hashlib.sha256(b"".join(base64.b64decode(x) for x in digests1)).digest()
check(base64.b64decode(H1) == spike_only, "H_bin == sha256(h_1‖…‖h_n) — CVM hashevidence semantics confirmed (spike-only check)")
check(sorted(bybin1) == list(bybin1), "digests beneath H are in sorted target-id order (the term's order)")
check(set(bysettings1) == {"stack:term", "stack:session", "stack:manifest", "stack:invocation"}, "settings lane holds term/session/manifest/invocation digests")
h_term_expected = hashlib.sha256((work / "run1" / "term.json").read_bytes()).digest()
check(base64.b64decode(bysettings1["stack:term"]) == h_term_expected, "h_term is the digest of the canonical term file the run used (fixed point holds; spike-only check)")
check(sha256_hex(canonical_json(req1["TERM"])) == h_term_expected.hex(), "term_sha256 pin == measured h_term")

print("B. repeat: same stack → same H_bin, fresh nonce and signature")
p2 = measure(lp1, req1)
d2, H2, _, _, s2 = read(p2, lp1.session)
check(H2 == H1, "H_bin equal")
check(d2.bid != d1.bid and p2[0]["RawEv"][0] != p1[0]["RawEv"][0], "nonce and signature differ")
check(s2 == bysettings1, "settings digests equal (same files)")

print("C. relocate: same binaries under another directory → same H_bin, different term digest")
asps2 = work / "elsewhere" / "asps2"; asps2.parent.mkdir(); shutil.copytree(asps1, asps2)
lp3, req3, _, _ = build(asps2, work / "run3", pub)
_, H3, _, _, s3 = read(measure(lp3, req3), lp3.session)
check(H3 == H1, "H_bin equal across directories (paths are not in H)")
check(s3["stack:term"] != bysettings1["stack:term"], "h_term differs (the term carries absolute paths)")
check(s3["stack:invocation"] == bysettings1["stack:invocation"], "h_invocation equal (same CvmConfig)")

print("D. perturb membership and names → different H_bin")
asps3 = work / "asps3"; shutil.copytree(asps1, asps3)
extra = asps3 / "zz_extra"; extra.write_bytes(b"#!/bin/sh\n"); extra.chmod(0o755)
lp4, req4, _, _ = build(asps3, work / "run4", pub)
_, H4, dig4, _, _ = read(measure(lp4, req4), lp4.session)
check(H4 != H1 and len(dig4) == n + 1, "an added executable changes H_bin")
asps4 = work / "asps4"; shutil.copytree(asps1, asps4)
(asps4 / "magic_appr").rename(asps4 / "aaa_magic_appr")
lp5, req5, _, _ = build(asps4, work / "run5", pub)
_, H5, dig5, _, _ = read(measure(lp5, req5), lp5.session)
check(H5 != H1 and sorted(dig5) == sorted(digests1), "a renamed file reorders the chain: same digests, different H_bin")

print("E. CVM audit of the stack package against injected goldens (the blessing's values)")
def audit(payload, session, goldens_hashfile, golden_H):
    et = inject_goldens(payload[1], goldens_hashfile, "hashfile")
    et = inject_goldens(et, {"": golden_H}, "hashevidence")  # the inner hashevidence has no targ id
    ap = ProtocolDir(protocol_id="attestation_stack", path="", term={}, session=session, manifest=context_manifest())
    resp = _run(client, ap, _request(ap, appraisal_term(), [payload[0], et]))
    assert resp.get("SUCCESS"), resp
    ad = describe_package(resp["PAYLOAD"], session, nonce_targid=APPRAISER_NONCE_TARGID)
    comps = interpret_appraisal(resp["PAYLOAD"], ap)
    return ad, comps
goldens = {**bybin1, **bysettings1}
ad, comps = audit(p1, lp1.session, goldens, H1)
check(not isinstance(comps, str), f"audit interpretable by the verified summarizer: {comps if isinstance(comps, str) else len(comps)} components")
if not isinstance(comps, str):
    check(all(c.passed for c in comps), "all components pass against the true goldens")
    kinds = {c.appr_asp for c in comps}
    check({"goldenbytes_appr", "sig_appr", "nonce_appr"} <= kinds, f"appraisers present: {sorted(kinds)}")
    hv = [c for c in comps if c.target_asp == "hashevidence"]
    check(len(hv) == 1 and hv[0].passed, "the CVM judged H_bin against the injected golden (one hashevidence component)")
    bad = dict(goldens); bad["stack:asp:hashfile"] = base64.b64encode(bytes(32)).decode()
    _, c2 = audit(p1, lp1.session, bad, H1)
    failing = {c.targ_id for c in c2 if not c.passed} if not isinstance(c2, str) else c2
    check(failing == {"stack:asp:hashfile"}, f"a wrong target golden fails exactly that target: {failing}")
    _, c3 = audit(p1, lp1.session, goldens, base64.b64encode(bytes(32)).decode())
    failing3 = [(c.target_asp, c.passed) for c in c3 if not c.passed] if not isinstance(c3, str) else c3
    check(failing3 == [("hashevidence", False)], f"a wrong H golden fails only the fingerprint component: {failing3}")

print("F. the real installation once")
lpR, reqR, filesR, _ = build(Path(real.asp_bin), work / "runR", pub)
dR, HR, digR, _, sR = read(measure(lpR, reqR), lpR.session)
check(len(digR) == len(filesR) and dR.assurance == "signed+nonce", f"real stack: {len(digR)} digests beneath H_bin, {dR.rawev_count} slots")
print(f"  H_bin(real) = {base64.b64decode(HR).hex()}")

print(f"\n{'ALL CHECKS PASSED' if not failures else str(failures) + ' CHECK(S) FAILED'}; work dir {work}")
sys.exit(1 if failures else 0)
