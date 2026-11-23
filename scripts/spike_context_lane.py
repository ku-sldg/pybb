"""Spike (plan P.2): the measured claim lane as the left-most `bseq right_path` branch."""
import copy, json, tempfile
from pathlib import Path
from pybb.attestation import CvmSubprocessClient, ProtocolDir
from pybb.attestation.ledger import APPRAISER_NONCE_TARGID, canonical_json, describe_package, slot_layout
from pybb.attestation.ledger_runs import (
    HASHEVIDENCE_KEEP, _APPR, _SIG, _asp, _bseq, _lseq, _request, _run, appraisal_term, combined_session,
    combined_term, interpret_appraisal, ledger_protocol, measurement_term, NONCE_ASP, NONCE_ARGS, APPRAISER_NONCE_ARGS)
from pybb.attestation.ledger_context import hashfile_targets
from pybb.attestation.tools import _hashfile_chain, _HASHFILE_TYPES
from pybb.attestation.provision import _measurement_term
from pybb.attestation.copland import inject_asp_args, normalize_term

client = CvmSubprocessClient()
proto = ProtocolDir.load("tests/fixtures/temp_control_aadl_slang_l1a")
work = Path(tempfile.mkdtemp(prefix="spike_lane_"))
files = {}
for n in ("term", "session", "manifest", "invocation", "claim"):
    p = work / f"{n}.json"; p.write_bytes(canonical_json({"file": n})); files[f"claim:{n}"] = p
lane_targets = hashfile_targets(files, "claim::lane")
LANE = normalize_term(inject_asp_args(_hashfile_chain(lane_targets), {"hashfile": lane_targets}))  # args injected like a protocol's
fails = 0
def check(c, msg):
    global fails
    print(("  ok   " if c else "  FAIL ") + msg); fails += 0 if c else 1

lp = ledger_protocol(proto)
sess = copy.deepcopy(lp.session)
sess["Session_Context"]["ASP_Types"].update({k: v for k, v in _HASHFILE_TYPES.items() if k in ("hashfile", "goldenbytes_appr")})
sess["Session_Context"]["ASP_Comps"].setdefault("hashfile", "goldenbytes_appr")
man = {**lp.manifest, "ASPS": sorted(set(lp.manifest["ASPS"]) | {"hashfile", "goldenbytes_appr"})}
lp = lp.model_copy(update={"session": sess, "manifest": man})

print("A. measure with lane: lseq (bseq left_path nonce (bseq right_path LANE M)) SIG")
stripped = _measurement_term(normalize_term(inject_asp_args(proto.term, proto.asp_args)))
M = stripped["TERM_BODY"][0]  # lseq M SIG -> M
term = _lseq(_bseq("left_path", _asp(NONCE_ASP, dict(NONCE_ARGS)), _bseq("right_path", LANE, M)), _SIG)
resp = _run(client, lp, _request(lp, term, [{"RawEv": []}, {"EvidenceT_CONSTRUCTOR": "mt_evt"}]))
assert resp.get("SUCCESS"), resp
raw_pkg = resp["PAYLOAD"]
d = describe_package(raw_pkg, lp.session)
spans = slot_layout(raw_pkg[1], lp.session)
lane_spans = [s for s in spans if (s.asp_targid or "").startswith("claim:")]
m_spans = [s for s in spans if s.asp == "hashfile" and not (s.asp_targid or "").startswith("claim:")]
check(d.bid is not None and d.signature.present, f"describable: {d.rawev_count} slots, {len(lane_spans)} lane slots, {len(m_spans)} measurement slots")
check([s.start for s in lane_spans] == [2, 3, 4, 5, 6], f"lane is the fixed prefix after sig,nonce: starts {[s.start for s in lane_spans]}")
check(d.rawev_count == 2 + 5 + len(m_spans), "right_path gave the lane empty evidence (no retained copy of M)")

print("B. appraise with lane over the stored package: lseq (bseq right_path LANE (bseq both_paths hashevidence APPR)) (lseq nonce SIG)")
# goldens for the lane's hashfile events in the stored package (pybb supplies, the CVM compares)
import hashlib, base64
from pybb.attestation.ledger_runs import inject_goldens
goldens = {t: base64.b64encode(hashlib.sha256(p.read_bytes()).digest()).decode() for t, p in files.items()}
et_in = inject_goldens(raw_pkg[1], goldens)  # the measurement's own hashfile targets already carry golden_b64 from provisioning
aterm = _lseq(_bseq("right_path", LANE, _bseq("both_paths", _asp("hashevidence", {}), _APPR)),
              _lseq(_asp(NONCE_ASP, dict(APPRAISER_NONCE_ARGS)), _SIG))
resp2 = _run(client, lp, _request(lp, aterm, [raw_pkg[0], et_in]))
assert resp2.get("SUCCESS"), resp2
apkg = resp2["PAYLOAD"]
da = describe_package(apkg, lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
sp2 = slot_layout(apkg[1], lp.session)
lane2 = [s for s in sp2 if (s.asp_targid or "").startswith("claim:") and not s.companion]
hs = [s for s in sp2 if s.asp == "hashevidence" and not s.input]
check(da.bid is not None, f"appraisal describable: {da.rawev_count} slots")
check([s.start for s in lane2] == [2, 3, 4, 5, 6], f"lane prefix at {[s.start for s in lane2]}; binding H at {hs[0].start if hs else None}")
check(len(hs) == 1 and hs[0].start == 7, "H follows the lane; REPLACE typing (one slot)")
comps = [s for s in sp2 if s.companion]
check(len(comps) == len(m_spans) + 5 + 2, f"APPR judged M ({len(m_spans)}), the lane (5) and sig/nonce (2): {len(comps)} companions")
# the summarizer over the APPR branch, once hash_lane learns to skip the lane — here by hand
from pybb.attestation.ledger_runs import hash_lane
try:
    left, right, offset = hash_lane(apkg, lp.session)
    print("  note hash_lane without lane-awareness returned offset", offset)
except Exception as e:
    print("  note hash_lane without lane-awareness:", str(e)[:90])

print("C. combined with lane: lseq M (lseq (bseq right_path LANE (bseq both_paths SIGN_LANE APPR)) (lseq nonce SIG))")
csess = copy.deepcopy(lp.session); csess["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
cp = lp.model_copy(update={"session": csess})
sign_lane = _lseq(_lseq(_asp(NONCE_ASP, dict(NONCE_ARGS)), _SIG), _asp("hashevidence", {}))
cterm = _lseq(M, _lseq(_bseq("right_path", LANE, _bseq("both_paths", sign_lane, _APPR)),
                       _lseq(_asp(NONCE_ASP, dict(APPRAISER_NONCE_ARGS)), _SIG)))
resp3 = _run(client, cp, _request(cp, cterm, [{"RawEv": []}, {"EvidenceT_CONSTRUCTOR": "mt_evt"}]))
assert resp3.get("SUCCESS"), resp3
cpkg = resp3["PAYLOAD"]
dc = describe_package(cpkg, cp.session, nonce_targid=APPRAISER_NONCE_TARGID)
sp3 = slot_layout(cpkg[1], cp.session)
lane3 = [s for s in sp3 if (s.asp_targid or "").startswith("claim:") and not s.companion and not s.input]
hs3 = [s for s in sp3 if s.asp == "hashevidence" and not s.input]
check(dc.bid is not None, f"combined describable: {dc.rawev_count} slots")
check([s.start for s in lane3] == [2, 3, 4, 5, 6], f"lane prefix at {[s.start for s in lane3]}; H at {hs3[0].start if hs3 else None}")
beneath = sum(s.count for s in sp3 if s.input)
check(beneath == 2 + len(m_spans), f"P retained beneath H: {beneath} slots (nonce, sig, {len(m_spans)} measurements)")
check(dc.rawev_count == 2 + 5 + 1 + beneath + len(m_spans), "APPR lane judged M only (no lane/sig verdicts in the combined run)")
print("\n" + ("ALL CHECKS PASSED" if not fails else f"{fails} CHECK(S) FAILED"))
