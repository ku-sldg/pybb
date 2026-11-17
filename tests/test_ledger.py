"""Ledger core: record schema, package inspection, FileLedger hash chain.

Synthetic packages only — the generate_nonce ASP does not exist yet (plan
section C); these tests pin down what pybb reads out of a package once it
does, following the EXTEND/REPLACE layout the CVM uses today.
"""

import base64
import hashlib
import json
import secrets

import pytest
from pydantic import ValidationError

from pybb.attestation.ledger import (
    AppraisalRecord,
    Binding,
    BundleRecord,
    DuplicateNonceError,
    EvidenceLayoutError,
    EvidenceRecord,
    FileLedger,
    Interpreter,
    LedgerIntegrityError,
    LedgerRecord,
    Locator,
    LocatorRecord,
    NonceRecord,
    RestoreRecord,
    SignatureInfo,
    SlotRef,
    VerdictRecord,
    assurance_at_least,
    canonical_json,
    derive_nid,
    describe_package,
    key_for,
    load_appraiser_id,
    parse_record,
    sha256_hex,
    slot_layout,
)

# ── synthetic Copland evidence ───────────────────────────────────────────────


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _asp_evt(asp_id, args=None, sub=None, plc="P0"):
    return {"EvidenceT_CONSTRUCTOR": "asp_evt",
            "EvidenceT_BODY": [plc, {"ASP_ID": asp_id, "ASP_ARGS": args or {}},
                               sub or {"EvidenceT_CONSTRUCTOR": "mt_evt"}]}


def _split(l, r):
    return {"EvidenceT_CONSTRUCTOR": "split_evt", "EvidenceT_BODY": [l, r]}


def _types(**kw):
    """ASP_Types in the session.json shape: name -> ('EXTEND'|'REPLACE', size)."""
    out = {}
    for name, (fwd, n) in kw.items():
        body = {"FWD": fwd, "_BODY": n}
        if fwd == "EXTEND":
            body["EvInSig"] = "ALL" if name.startswith("sig") else "NONE"
        out[name] = {"FWD": body, "ATTRS": []}
    return out


SESSION = {
    "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
    "Session_Context": {
        "ASP_Types": _types(generate_nonce=("EXTEND", 1), hashfile=("EXTEND", 1),
                            sig=("EXTEND", 1), nonce_appr=("REPLACE", 1),
                            goldenbytes_appr=("REPLACE", 1), sig_appr=("REPLACE", 1)),
        "ASP_Comps": {"generate_nonce": "nonce_appr", "hashfile": "goldenbytes_appr",
                      "sig": "sig_appr"},
    },
}

NONCE = secrets.token_bytes(32)
HASH_A = hashlib.sha256(b"file a").digest()
HASH_B = hashlib.sha256(b"file b").digest()
SIG = b"\x01" * 256


def raw_package(with_sig=True, with_nonce=True):
    """lseq (generate_nonce) (lseq (bseq hashfile hashfile) sig), APPR stripped.

    EXTEND prepends: RawEv = [sig, hash_a, hash_b, nonce] (newest first).
    """
    base = _asp_evt("generate_nonce", {"asp_targid": "nonce_targ", "bytes": 32}) \
        if with_nonce else {"EvidenceT_CONSTRUCTOR": "mt_evt"}
    meas = _split(_asp_evt("hashfile", {"asp_targid": "a_targ", "filepath": "/a"}, base),
                  _asp_evt("hashfile", {"asp_targid": "b_targ", "filepath": "/b"}, base))
    raw = [HASH_A] + ([NONCE] if with_nonce else []) + [HASH_B] + ([NONCE] if with_nonce else [])
    et = meas
    if with_sig:
        et = _asp_evt("sig", {}, meas)
        raw = [SIG] + raw
    return [{"RawEv": [_b64(b) for b in raw]}, et]


def linear_package():
    """lseq (generate_nonce) (lseq hashfile sig): RawEv = [sig, hash_a, nonce]."""
    et = _asp_evt("sig", {}, _asp_evt("hashfile", {"asp_targid": "a_targ"},
                                      _asp_evt("generate_nonce", {"asp_targid": "nonce_targ"})))
    return [{"RawEv": [_b64(SIG), _b64(HASH_A), _b64(NONCE)]}, et]


# ── canonical form and envelope ──────────────────────────────────────────────


def test_canonical_json_is_order_independent_and_compact():
    a = canonical_json({"b": 1, "a": [1, 2], "c": {"y": "ü", "x": None}})
    b = canonical_json({"c": {"x": None, "y": "ü"}, "a": [1, 2], "b": 1})
    assert a == b == '{"a":[1,2],"b":1,"c":{"x":null,"y":"ü"}}'.encode("utf-8")


def test_envelope_uses_schema_alias_and_preserves_unknown_fields():
    rec = parse_record({"schema": "pybb-ledger/v1", "kind": "evidence", "nid": "00",
                        "protocol_id": "p", "response_sha256": "r", "blob_sha256": "b",
                        "blob_bytes": 1, "rawev_count": 1, "rawev_sha256": "h",
                        "signature": {"present": False}, "nonce": {"slot": 0, "asp": "generate_nonce"},
                        "assurance": "nonce", "future_field": {"kept": True}})
    assert isinstance(rec, EvidenceRecord)
    d = rec.to_dict()
    assert d["schema"] == "pybb-ledger/v1" and "schema_version" not in d
    assert d["future_field"] == {"kept": True}
    assert rec.content_sha256() == sha256_hex(canonical_json(d))


def test_unknown_kind_parses_as_generic_record():
    rec = parse_record({"schema": "pybb-ledger/v1", "kind": "mystery", "x": 1})
    assert type(rec) is LedgerRecord and rec.kind == "mystery"


# ── nonce record validation ──────────────────────────────────────────────────


def _nonce_record(nonce=NONCE, **kw):
    fields = dict(nid=sha256_hex(nonce), nonce_b64=_b64(nonce), nonce_bytes=len(nonce),
                  protocol_id="proto")
    fields.update(kw)
    return NonceRecord(**fields)


def test_nonce_record_checks_nid_against_bytes():
    assert _nonce_record().nid == sha256_hex(NONCE)
    with pytest.raises(ValidationError, match="sha256"):
        _nonce_record(nid="00" * 32)
    with pytest.raises(ValidationError, match="nonce_bytes"):
        _nonce_record(nonce_bytes=31)
    with pytest.raises(ValidationError, match="for_nid"):
        _nonce_record(role="appraisal")


# ── package inspection ───────────────────────────────────────────────────────


def test_slot_layout_follows_extend_prepend_and_split_order():
    pkg = linear_package()
    spans = slot_layout(pkg[1], SESSION)
    assert [(s.asp, s.start, s.count) for s in spans] == [
        ("sig", 0, 1), ("hashfile", 1, 1), ("generate_nonce", 2, 1)]


def test_describe_package_derives_nid_from_last_slot_and_labels_assurance():
    pkg = linear_package()
    desc = describe_package(pkg, SESSION)
    assert desc.rawev_count == 3
    assert desc.nonce == SlotRef(slot=2, asp="generate_nonce", asp_targid="nonce_targ")
    assert desc.nid == sha256_hex(NONCE) == derive_nid(pkg, SESSION)
    assert desc.signature.present and desc.signature.slot == 0 and desc.signature.asp == "sig"
    assert desc.assurance == "signed+nonce"
    assert desc.rawev_sha256 == sha256_hex(SIG + HASH_A + NONCE)  # == hashevidence
    assert desc.response_sha256 == sha256_hex(canonical_json(pkg))


def test_assurance_levels_from_what_is_present():
    # no nonce event: innermost is mt_evt
    et = _asp_evt("sig", {}, _asp_evt("hashfile", {"asp_targid": "a"}))
    pkg = [{"RawEv": [_b64(SIG), _b64(HASH_A)]}, et]
    d = describe_package(pkg, SESSION)
    assert d.assurance == "signed" and d.nid is None and d.nonce is None
    et = _asp_evt("hashfile", {"asp_targid": "a"}, _asp_evt("generate_nonce", {"asp_targid": "nonce_targ"}))
    d = describe_package([{"RawEv": [_b64(HASH_A), _b64(NONCE)]}, et], SESSION)
    assert d.assurance == "nonce" and d.nid == sha256_hex(NONCE)
    d = describe_package([{"RawEv": [_b64(HASH_A)]}, _asp_evt("hashfile", {"asp_targid": "a"})], SESSION)
    assert d.assurance == "none"
    with pytest.raises(EvidenceLayoutError, match="no generate_nonce"):
        derive_nid([{"RawEv": [_b64(HASH_A)]}, _asp_evt("hashfile", {})], SESSION)
    assert assurance_at_least("signed+nonce", "signed") and not assurance_at_least("nonce", "signed")


def test_split_duplicates_nonce_under_both_branches_is_flagged():
    """Spike finding (plan C): `lseq generate_nonce (bseq both_paths ...)`
    copies the nonce into every branch — the real CVM produced four nonce
    events for the l1a fixture. The measurement term therefore uses
    `bseq left_path generate_nonce M` (one copy); a package with several
    nonce events is rejected, never silently picked from."""
    with pytest.raises(EvidenceLayoutError, match="2 nonce events"):
        describe_package(raw_package(), SESSION)


def test_layout_must_account_for_every_slot():
    pkg = linear_package()
    pkg[0]["RawEv"].append(_b64(b"extra"))
    with pytest.raises(EvidenceLayoutError, match="accounts for 3 slots, RawEv has 4"):
        describe_package(pkg, SESSION)


def test_replace_events_consume_their_subtree():
    """A post-appraisal package (today's archives): REPLACE verdict slots stand
    in for the measurements, so the layout has no measurement or nonce bytes —
    exactly why plan B.0 splits measurement from appraisal."""
    appraised = _split(
        _asp_evt("sig_appr", {}, _asp_evt("sig", {}, _asp_evt("hashfile", {}))),
        _asp_evt("goldenbytes_appr", {"asp_targid": "a_targ"}, _asp_evt("hashfile", {})))
    pkg = [{"RawEv": [_b64(b""), _b64(b"")]}, appraised]
    d = describe_package(pkg, SESSION)
    assert [s.asp for s in d.spans] == ["sig_appr", "goldenbytes_appr"]
    assert d.assurance == "none" and d.nid is None


def test_unknown_asp_type_is_a_layout_error():
    et = _asp_evt("mystery_asp", {})
    with pytest.raises(EvidenceLayoutError, match="not in the session"):
        slot_layout(et, SESSION)


# ── records for a run ────────────────────────────────────────────────────────


def _run_records(nonce=NONCE, anonce=None, protocol="proto"):
    anonce = anonce or secrets.token_bytes(32)
    nid, anid = sha256_hex(nonce), sha256_hex(anonce)
    n = _nonce_record(nonce, protocol_id=protocol)
    an = NonceRecord(nid=anid, nonce_b64=_b64(anonce), nonce_bytes=32, role="appraisal",
                     for_nid=nid, protocol_id=protocol)
    ev = EvidenceRecord(nid=nid, protocol_id=protocol, response_sha256="r" * 64,
                        blob_sha256="b" * 64, blob_bytes=10, rawev_count=3, rawev_sha256="h" * 64,
                        signature=SignatureInfo(present=True, slot=0, asp="sig"),
                        nonce=SlotRef(slot=2, asp="generate_nonce", asp_targid="nonce_targ"),
                        assurance="signed+nonce",
                        locators=[Locator(kind="local", path="evidence/x/p.response.json.gz",
                                          appraiser_id="ap-1")])
    ap = AppraisalRecord(nid=nid, seq=1, mode="live", anid=anid, response_sha256="q" * 64,
                         blob_sha256="c" * 64, blob_bytes=5, rawev_sha256="g" * 64,
                         binding=Binding(slot=2, evidence_hash="h" * 64),
                         signature=SignatureInfo(present=True, slot=0, asp="sig"),
                         nonce=SlotRef(slot=1, asp="generate_nonce"), assurance="signed+nonce",
                         passed=True, interpreter=Interpreter(kind="verified-summary",
                                                              tool="copland-evidence-tools"))
    vd = VerdictRecord(nid=nid, protocol_id=protocol, passed=True, components_total=2,
                       evidence_assurance="signed+nonce", appraisal_assurance="signed+nonce",
                       interpreter=Interpreter(kind="verified-summary"))
    return n, an, ev, ap, vd


def test_keys_follow_the_plan():
    n, an, ev, ap, vd = _run_records()
    assert key_for(n) == f"nonce/{n.nid}" and key_for(an) == f"nonce/{an.nid}"
    assert key_for(ev) == f"evidence/{n.nid}" and key_for(vd) == f"verdict/{n.nid}"
    assert key_for(ap) == f"appraisal/{n.nid}/1"
    loc = LocatorRecord(nid=n.nid, seq=1, target="evidence", blob_sha256="b" * 64,
                        locator=Locator(kind="github", path="blobs/x", repo="o/r", commit="c"))
    assert key_for(loc) == f"locator/{n.nid}/1"
    bundle = BundleRecord(nid=None, protocol_id="p", response_sha256="r", blob_sha256="s" * 64,
                          blob_bytes=1, rawev_count=1, signature=SignatureInfo(present=True),
                          assurance="signed")
    assert key_for(bundle) == f"bundle/sha256:{'s' * 64}"
    bundle2 = bundle.model_copy(update={"nid": "n" * 64})
    assert key_for(bundle2) == f"bundle/{'n' * 64}"


# ── FileLedger ───────────────────────────────────────────────────────────────


def test_commit_run_round_trip_and_duplicate_refusal(tmp_path):
    led = FileLedger(tmp_path / "ledger.jsonl")
    n, an, ev, ap, vd = _run_records()
    receipt = led.commit_run(n, an, ev, ap, vd)
    assert receipt.tx == 1 and receipt.verified
    assert set(receipt.keys) == {key_for(r) for r in (n, an, ev, ap, vd)}
    run = led.get(n.nid)
    assert run.evidence == ev and run.verdict == vd and run.nonce == n
    assert run.appraisals == [ap] and run.appraiser_nonces == [an]
    # the same package again: refused before anything is written
    with pytest.raises(DuplicateNonceError):
        led.commit_run(n, an, ev, ap, vd)
    assert len(led) == 1
    # a fresh run nonce but a reused appraiser nonce: also refused
    n2, _, ev2, ap2, vd2 = _run_records(nonce=secrets.token_bytes(32))
    ap2 = ap2.model_copy(update={"anid": an.nid})
    an2 = an.model_copy(update={"for_nid": n2.nid})
    with pytest.raises(DuplicateNonceError):
        led.commit_run(n2, an2, ev2, ap2, vd2)


def test_commit_run_rejects_inconsistent_batches(tmp_path):
    led = FileLedger(tmp_path / "l.jsonl")
    n, an, ev, ap, vd = _run_records()
    other = _nonce_record(secrets.token_bytes(32))
    with pytest.raises(Exception, match="disagree on nid"):
        led.commit_run(n, an, ev.model_copy(update={"nid": other.nid}), ap, vd)
    with pytest.raises(Exception, match="role 'appraisal'"):
        led.commit_run(n, other, ev, ap, vd)
    with pytest.raises(Exception, match="live seq-1"):
        led.commit_run(n, an, ev, ap.model_copy(update={"seq": 2}), vd)
    assert len(led) == 0


def test_chain_persists_reloads_and_detects_tampering(tmp_path):
    path = tmp_path / "l.jsonl"
    led = FileLedger(path)
    n, an, ev, ap, vd = _run_records()
    led.commit_run(n, an, ev, ap, vd)
    led.append_locator(LocatorRecord(nid=n.nid, seq=1, target="evidence", blob_sha256=ev.blob_sha256,
                                     locator=Locator(kind="github", path="blobs/x", repo="o/r",
                                                     commit="c", git_blob_sha="g"), verified=True))
    assert led.verify_chain() == 2

    reloaded = FileLedger(path)
    assert len(reloaded) == 2 and reloaded.get(n.nid).locators[0].locator.repo == "o/r"
    assert reloaded.tx_of(f"evidence/{n.nid}") == 1 and reloaded.tx_of(f"locator/{n.nid}/1") == 2

    # flip the verdict inside the stored value: content hash and chain both break
    lines = path.read_text().splitlines()
    tampered = lines[0].replace('\\"passed\\":true', '\\"passed\\":false')
    assert tampered != lines[0]
    path.write_text("\n".join([tampered] + lines[1:]) + "\n")
    with pytest.raises(LedgerIntegrityError):
        FileLedger(path)

    # drop a transaction from the middle: numbering/chain gap
    path.write_text(lines[1] + "\n")
    with pytest.raises(LedgerIntegrityError):
        FileLedger(path)


def test_audit_appraisal_appends_with_new_appraiser_nonce(tmp_path):
    led = FileLedger(tmp_path / "l.jsonl")
    n, an, ev, ap, vd = _run_records()
    led.commit_run(n, an, ev, ap, vd)
    audit_nonce = secrets.token_bytes(32)
    an2 = NonceRecord(nid=sha256_hex(audit_nonce), nonce_b64=_b64(audit_nonce), nonce_bytes=32,
                      role="appraisal", for_nid=n.nid, protocol_id="proto")
    ap2 = ap.model_copy(update={"seq": 2, "mode": "audit", "anid": an2.nid,
                                "agrees_with_recorded_verdict": True,
                                "checks": {"ledger_verified": True, "bytes_match": True, "nid_ok": True}})
    led.append_appraisal(ap2, an2)
    run = led.get(n.nid)
    assert [a.seq for a in run.appraisals] == [1, 2]
    assert run.appraisals[1].agrees_with_recorded_verdict is True
    with pytest.raises(Exception, match="already recorded"):
        led.append_appraisal(ap2, an2.model_copy(update={"nid": an2.nid}))
    with pytest.raises(Exception, match="audit"):
        led.append_appraisal(ap.model_copy(update={"seq": 3}), an2)


def test_bundle_and_restore_records(tmp_path):
    led = FileLedger(tmp_path / "l.jsonl")
    legacy = BundleRecord(protocol_id="p", response_sha256="r" * 64, blob_sha256="s" * 64,
                          blob_bytes=100, rawev_count=5, signature=SignatureInfo(present=True, slot=0, asp="sig"),
                          assurance="signed",
                          locators=[Locator(kind="local", path="golden/_bundles/p/provision_bundle.json")])
    led.commit_bundle(legacy)
    with pytest.raises(Exception, match="already recorded"):
        led.commit_bundle(legacy)
    nonced = legacy.model_copy(update={"nid": "n" * 64, "assurance": "signed+nonce",
                                       "nonce": SlotRef(slot=4, asp="generate_nonce")})
    led.commit_bundle(nonced)
    with pytest.raises(DuplicateNonceError):
        led.commit_bundle(nonced)
    led.commit_restore(RestoreRecord(mode="exact", source_repo="o/r", source_commit="c",
                                     source_last_state_tx=3, tx_count=3))
    kinds = [r.kind for r in led.records()]
    assert kinds == ["bundle", "bundle", "restore"]
    assert [r.kind for r in led.records(kind="bundle", protocol_id="p")] == ["bundle", "bundle"]
    assert led.exists(f"bundle/{'n' * 64}") and led.exists(f"bundle/sha256:{'s' * 64}")


def test_appraiser_id_is_created_once_and_opaque(tmp_path):
    a = load_appraiser_id(str(tmp_path / "state"))
    b = load_appraiser_id(str(tmp_path / "state"))
    assert a == b and a.startswith("ap-") and len(a) == 11
    assert a not in json.dumps({"host": "adams-mbp"})  # nothing host-derived
