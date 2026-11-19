"""Ledger core (schema v2): bundle records, package inspection, FileLedger
hash chain.

Synthetic packages, following the EXTEND/REPLACE layout the CVM uses today;
the real packages are exercised in test_ledger_runs.py.
"""

import base64
import hashlib
import json
import secrets

import pytest
from pydantic import ValidationError

from pybb.attestation.ledger import (
    BlobRef,
    BundleRecord,
    DuplicateNonceError,
    EvidenceLayoutError,
    FileLedger,
    InputRef,
    Interpreter,
    JudgedByRecord,
    LedgerError,
    LedgerIntegrityError,
    LedgerRecord,
    Location,
    MirrorRecord,
    NonceInfo,
    ProvisionInfo,
    RestoreRecord,
    SignatureInfo,
    SlotRef,
    Verdict,
    assurance_at_least,
    canonical_json,
    derive_bid,
    describe_package,
    key_for,
    load_appraiser_id,
    parse_record,
    sha256_hex,
    slot_layout,
)
from pybb.attestation.ledger_v1 import EvidenceRecord as EvidenceRecordV1

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


def test_envelope_uses_schema_alias_omits_none_and_preserves_unknown_fields():
    m = _measurement_bundle()
    d = m.to_dict()
    assert d["schema"] == "pybb-ledger/v2" and "schema_version" not in d
    assert "verdict" not in d and "inputs" not in d and "appraisal_kind" not in d  # None omitted
    rec = parse_record({**d, "future_field": {"kept": True}})
    assert isinstance(rec, BundleRecord) and rec.to_dict()["future_field"] == {"kept": True}
    assert rec.content_sha256() == sha256_hex(canonical_json(rec.to_dict()))


def test_v1_records_still_parse_through_their_schema_tag():
    rec = parse_record({"schema": "pybb-ledger/v1", "kind": "evidence", "nid": "00",
                        "protocol_id": "p", "response_sha256": "r", "blob_sha256": "b",
                        "blob_bytes": 1, "rawev_count": 1, "rawev_sha256": "h",
                        "signature": {"present": False}, "nonce": {"slot": 0, "asp": "generate_nonce"},
                        "assurance": "nonce"})
    assert isinstance(rec, EvidenceRecordV1) and key_for(rec) == "evidence/00"


def test_unknown_kind_parses_as_generic_record():
    rec = parse_record({"schema": "pybb-ledger/v2", "kind": "mystery", "x": 1})
    assert type(rec) is LedgerRecord and rec.kind == "mystery"


# ── bundle records ───────────────────────────────────────────────────────────


def _nonce_info(nonce: bytes, slot: int = 2) -> NonceInfo:
    return NonceInfo(slot=slot, asp="generate_nonce", asp_targid="nonce_targ", b64=_b64(nonce), bytes=len(nonce))


def _blob(sha: str = "b" * 64, local: str = "evidence/x/p.response.json.gz", store: str = "github:o/r") -> BlobRef:
    return BlobRef(blob_sha256=sha, blob_bytes=10,
                   locations=[Location(store="local", path=local), Location(store=store, path=f"blobs/{sha}.json.gz")])


def _measurement_bundle(nonce_bytes: bytes = NONCE, protocol: str = "proto", **kw) -> BundleRecord:
    fields = dict(bid=sha256_hex(nonce_bytes), role="measurement", protocol_id=protocol, response_sha256="r" * 64,
                  blob=_blob(), rawev_count=3, rawev_sha256="h" * 64, nonce=_nonce_info(nonce_bytes),
                  signature=SignatureInfo(present=True, slot=0, asp="sig"), assurance="signed+nonce",
                  appraiser_id="ap-1")
    fields.update(kw)
    return BundleRecord(**fields)


def _appraisal_bundle(of: BundleRecord, nonce_bytes: bytes = None, passed: bool = True, kind: str = "live",
                      **kw) -> BundleRecord:
    nonce = nonce_bytes or secrets.token_bytes(32)
    fields = dict(bid=sha256_hex(nonce), role="appraisal", protocol_id=of.protocol_id, response_sha256="q" * 64,
                  blob=_blob("c" * 64, "evidence/x/p.appraisal.json.gz"), rawev_count=5, rawev_sha256="g" * 64,
                  nonce=_nonce_info(nonce, slot=1), signature=SignatureInfo(present=True, slot=0, asp="sig"),
                  assurance="signed+nonce",
                  inputs=[InputRef(bid=of.key_id, binding_slot=2, binding_hash=of.rawev_sha256)],
                  verdict=Verdict(passed=passed, components_total=2, components_failed=0 if passed else 1,
                                  interpreter=Interpreter(kind="verified-summary", tool="copland-evidence-tools")),
                  appraisal_kind=kind, appraiser_id="ap-1")
    fields.update(kw)
    return BundleRecord(**fields)


def test_bundle_id_is_the_sha256_of_its_nonce():
    m = _measurement_bundle()
    assert m.bid == sha256_hex(NONCE) and m.key_id == m.bid
    with pytest.raises(ValidationError, match="sha256 of the nonce"):
        _measurement_bundle(bid="00" * 32)
    with pytest.raises(ValidationError, match="nonce.bytes"):
        _measurement_bundle(nonce=_nonce_info(NONCE).model_copy(update={"bytes": 31}))
    # a legacy nonce-less bundle has no bid and keys by blob hash
    legacy = _measurement_bundle(bid=None, nonce=None, role="provision", assurance="signed")
    assert legacy.key_id == f"sha256:{'b' * 64}"
    with pytest.raises(ValidationError, match="has no bid"):
        _measurement_bundle(nonce=None)


def test_role_invariants():
    m = _measurement_bundle()
    with pytest.raises(ValidationError, match="needs inputs and a verdict"):
        _appraisal_bundle(m, inputs=None)
    with pytest.raises(ValidationError, match="needs inputs and a verdict"):
        _appraisal_bundle(m, verdict=None)
    with pytest.raises(ValidationError, match="carries no verdict"):
        _measurement_bundle(verdict=_appraisal_bundle(m).verdict)
    with pytest.raises(ValidationError, match="carries no verdict"):
        _measurement_bundle(appraisal_kind="live")
    with pytest.raises(ValidationError, match="takes no inputs"):
        _measurement_bundle(role="provision", inputs=[InputRef(bid="x" * 64)])
    with pytest.raises(ValidationError, match="needs a state"):
        _measurement_bundle(role="challenge")
    with pytest.raises(ValidationError, match="no challenge state"):
        _measurement_bundle(state="issued")
    # a challenged measurement names exactly one challenge (section G)
    assert _measurement_bundle(inputs=[InputRef(bid="c" * 64)]).inputs[0].bid == "c" * 64
    with pytest.raises(ValidationError, match="exactly one challenge"):
        _measurement_bundle(inputs=[InputRef(bid="c" * 64), InputRef(bid="d" * 64)])


def test_keys_follow_the_plan():
    m = _measurement_bundle()
    a = _appraisal_bundle(m)
    assert key_for(m) == f"bundle/{m.bid}" and key_for(a) == f"bundle/{a.bid}"
    assert key_for(JudgedByRecord(bid=m.bid, appraisal_bid=a.bid)) == f"judged_by/{m.bid}/{a.bid}"
    legacy = _measurement_bundle(bid=None, nonce=None, role="provision", assurance="signed")
    assert key_for(legacy) == f"bundle/sha256:{'b' * 64}"
    mir = MirrorRecord(store="github:ku-sldg/pybb-ledger", repo="ku-sldg/pybb-ledger", commit="c", state_tx=42)
    assert key_for(mir) == "mirror/github-ku-sldg-pybb-ledger/000000000042"
    rr = RestoreRecord(mode="exact", source_repo="o/r", source_commit="c", source_last_state_tx=3, tx_count=3)
    assert key_for(rr) == f"restore/{rr.created_at}"


# ── package inspection ───────────────────────────────────────────────────────


def test_slot_layout_follows_extend_prepend_and_split_order():
    pkg = linear_package()
    spans = slot_layout(pkg[1], SESSION)
    assert [(s.asp, s.start, s.count) for s in spans] == [
        ("sig", 0, 1), ("hashfile", 1, 1), ("generate_nonce", 2, 1)]


def test_describe_package_derives_bid_from_the_nonce_slot_and_labels_assurance():
    pkg = linear_package()
    desc = describe_package(pkg, SESSION)
    assert desc.rawev_count == 3
    assert desc.nonce == SlotRef(slot=2, asp="generate_nonce", asp_targid="nonce_targ")
    assert desc.bid == sha256_hex(NONCE) == derive_bid(pkg, SESSION)
    assert desc.nonce_b64 == _b64(NONCE)
    assert desc.signature.present and desc.signature.slot == 0 and desc.signature.asp == "sig"
    assert desc.assurance == "signed+nonce"
    assert desc.rawev_sha256 == sha256_hex(SIG + HASH_A + NONCE)  # == hashevidence
    assert desc.response_sha256 == sha256_hex(canonical_json(pkg))


def test_assurance_levels_from_what_is_present():
    # no nonce event: innermost is mt_evt
    et = _asp_evt("sig", {}, _asp_evt("hashfile", {"asp_targid": "a"}))
    pkg = [{"RawEv": [_b64(SIG), _b64(HASH_A)]}, et]
    d = describe_package(pkg, SESSION)
    assert d.assurance == "signed" and d.bid is None and d.nonce is None
    et = _asp_evt("hashfile", {"asp_targid": "a"}, _asp_evt("generate_nonce", {"asp_targid": "nonce_targ"}))
    d = describe_package([{"RawEv": [_b64(HASH_A), _b64(NONCE)]}, et], SESSION)
    assert d.assurance == "nonce" and d.bid == sha256_hex(NONCE)
    d = describe_package([{"RawEv": [_b64(HASH_A)]}, _asp_evt("hashfile", {"asp_targid": "a"})], SESSION)
    assert d.assurance == "none"
    with pytest.raises(EvidenceLayoutError, match="no generate_nonce"):
        derive_bid([{"RawEv": [_b64(HASH_A)]}, _asp_evt("hashfile", {})], SESSION)
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
    assert d.assurance == "none" and d.bid is None


def test_unknown_asp_type_is_a_layout_error():
    et = _asp_evt("mystery_asp", {})
    with pytest.raises(EvidenceLayoutError, match="not in the session"):
        slot_layout(et, SESSION)


# ── FileLedger ───────────────────────────────────────────────────────────────


def test_commit_bundles_round_trip_pointers_and_duplicate_refusal(tmp_path):
    led = FileLedger(tmp_path / "ledger.jsonl")
    m = _measurement_bundle()
    a = _appraisal_bundle(m)
    receipt = led.commit_bundles([m, a])
    assert receipt.tx == 1 and receipt.verified
    assert receipt.keys == [key_for(m), key_for(a), f"judged_by/{m.bid}/{a.bid}"]
    assert led.get(m.bid) == m and led.get(a.bid) == a
    assert led.appraisals_of(m.bid) == [a] and led.appraisals_of(a.bid) == []
    # the same package again: refused before anything is written
    with pytest.raises(DuplicateNonceError):
        led.commit_bundles([m, a])
    assert len(led) == 1
    # a fresh measurement but a reused appraiser nonce: also refused
    m2 = _measurement_bundle(secrets.token_bytes(32))
    with pytest.raises(DuplicateNonceError):
        led.commit_bundles([m2, _appraisal_bundle(m2, base64.b64decode(a.nonce.b64))])
    assert len(led) == 1


def test_commit_bundles_rejects_inconsistent_batches(tmp_path):
    led = FileLedger(tmp_path / "l.jsonl")
    m = _measurement_bundle()
    with pytest.raises(LedgerError, match="empty"):
        led.commit_bundles([])
    with pytest.raises(LedgerError, match="duplicate bundle in one batch"):
        led.commit_bundles([m, m])
    stranger = _measurement_bundle(secrets.token_bytes(32))
    with pytest.raises(LedgerError, match="is not in the ledger"):
        led.commit_bundles([_appraisal_bundle(stranger)])  # input neither stored nor in the batch
    assert len(led) == 0


def test_many_appraisals_over_one_measurement(tmp_path):
    led = FileLedger(tmp_path / "l.jsonl")
    m = _measurement_bundle()
    live = _appraisal_bundle(m, kind="live")
    led.commit_bundles([m, live])
    audit = _appraisal_bundle(m, kind="audit", verdict=live.verdict.model_copy(update={"agrees_with_live": True}))
    slices = _appraisal_bundle(m, kind="slices-only", passed=False, session_sha256="s" * 64)
    led.commit_bundles([audit])
    led.commit_bundles([slices])
    of_m = led.appraisals_of(m.bid)
    assert {a.appraisal_kind for a in of_m} == {"live", "audit", "slices-only"}
    assert {a.verdict.passed for a in of_m if a.appraisal_kind == "slices-only"} == {False}
    # an appraisal of an appraisal: just an appraisal whose input is an appraisal
    audit2 = _appraisal_bundle(live, kind="audit")
    led.commit_bundles([audit2])
    assert [a.bid for a in led.appraisals_of(live.bid)] == [audit2.bid]
    assert len(led.bundles(role="appraisal")) == 4 and len(led.bundles(protocol_id="proto", role="measurement")) == 1


def test_chain_persists_reloads_and_detects_tampering(tmp_path):
    path = tmp_path / "l.jsonl"
    led = FileLedger(path)
    m = _measurement_bundle()
    a = _appraisal_bundle(m)
    led.commit_bundles([m, a])
    led.commit_mirror(MirrorRecord(store="github:o/r", repo="o/r", commit="c", state_tx=1, blobs=2))
    assert led.verify_chain() == 2

    reloaded = FileLedger(path)
    assert len(reloaded) == 2 and reloaded.latest_mirror("github:o/r").commit == "c"
    assert reloaded.tx_of(f"bundle/{m.bid}") == 1 and reloaded.tx_of("mirror/github-o-r/000000000001") == 2
    with pytest.raises(LedgerError, match="already exists"):
        reloaded.commit_mirror(MirrorRecord(store="github:o/r", commit="d", state_tx=1))

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


def test_provision_and_restore_records(tmp_path):
    led = FileLedger(tmp_path / "l.jsonl")
    legacy = BundleRecord(role="provision", protocol_id="p", response_sha256="r" * 64,
                          blob=BlobRef(blob_sha256="s" * 64, blob_bytes=100, encoding="json",
                                       locations=[Location(store="local", path="golden/_bundles/p/provision_bundle.json")]),
                          rawev_count=5, rawev_sha256="h" * 64,
                          signature=SignatureInfo(present=True, slot=0, asp="sig"), assurance="signed",
                          freshness="none", provision=ProvisionInfo(golden_ts="2026-11-01T00:00:00Z", targets=4))
    led.commit_bundles([legacy])
    with pytest.raises(DuplicateNonceError):
        led.commit_bundles([legacy])
    nonced = legacy.model_copy(update={"bid": sha256_hex(NONCE), "assurance": "signed+nonce",
                                       "freshness": "post-hoc", "nonce": _nonce_info(NONCE, slot=4)})
    led.commit_bundles([nonced])
    led.commit_restore(RestoreRecord(mode="exact", source_repo="o/r", source_commit="c",
                                     source_last_state_tx=3, tx_count=3))
    assert [r.kind for r in led.records()] == ["bundle", "bundle", "restore"]
    assert [r.role for r in led.bundles(protocol_id="p")] == ["provision", "provision"]
    assert led.exists(f"bundle/{sha256_hex(NONCE)}") and led.exists(f"bundle/sha256:{'s' * 64}")
    assert led.get_record(f"bundle/sha256:{'s' * 64}").provision.targets == 4


def test_appraiser_id_is_created_once_and_opaque(tmp_path):
    a = load_appraiser_id(str(tmp_path / "state"))
    b = load_appraiser_id(str(tmp_path / "state"))
    assert a == b and a.startswith("ap-") and len(a) == 11
    assert a not in json.dumps({"host": "adams-mbp"})  # nothing host-derived
