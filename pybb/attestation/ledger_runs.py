"""
Nonce'd, two-run attestation that lands in the ledger (docs/ledger_plan.md,
sections B.0–B.7, D).

One protocol run is two CVM invocations:

  1. measurement run   lseq (bseq left_path (asp generate_nonce) M) SIG
                       -> the RAW SIGNED PACKAGE: nonce, measurements,
                          signature (APPR stripped; `M` is the protocol's
                          measurement term, `SIG` its own signature step)
  2. appraisal run     lseq (bseq both_paths (asp hashevidence) APPR)
                            (lseq (asp generate_nonce) SIG)
                       over the raw package
                       -> the SIGNED APPRAISAL PACKAGE: [sig | appraiser
                          nonce | binding hash | verdict slots...]

pybb then archives both packages and the interpreted component list,
derives the run's identity from the signed nonce slot, and commits the
run's records to the ledger in one batch. pybb never judges: signatures,
nonces and goldens are companion-ASP verdicts read back through the
verified summarizer (over the extracted APPR branch) — see plan B.9.

Spike-verified against the real CVM on 2026-11-17 (plan section C).
"""

from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel

from .appraisal import ComponentResult, overall_verdict, parse_appraisal, stamp_measured_files
from .copland import empty_evidence, inject_asp_args, normalize_term
from .ledger import (
    APPRAISER_NONCE_TARGID,
    NONCE_ASP,
    NONCE_TARGID,
    AppraisalRecord,
    Binding,
    DuplicateNonceError,
    EvidenceLayoutError,
    EvidenceRecord,
    FailingComponent,
    Interpreter,
    Ledger,
    LedgerConfig,
    LedgerError,
    Locator,
    LocatorRecord,
    NonceRecord,
    PackageDescription,
    SignatureInfo,
    SlotRef,
    ToolingRef,
    VerdictRecord,
    assurance_at_least,
    canonical_json,
    describe_package,
    key_for,
    load_appraiser_id,
    pybb_version,
    sha256_hex,
    slot_layout,
)

NONCE_BYTES = 32
NONCE_ARGS = {"asp_targid": NONCE_TARGID, "bytes": NONCE_BYTES}
APPRAISER_NONCE_ARGS = {"asp_targid": APPRAISER_NONCE_TARGID, "bytes": NONCE_BYTES}

# Session additions for ledger runs (plan B.1 / B.6); REPLACE for
# hashevidence so the binding is one slot, not hash + a copy of the package.
LEDGER_ASP_TYPES: Dict[str, dict] = {
    NONCE_ASP: {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"}, "ATTRS": []},
    "nonce_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
    "hashevidence": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
    "magic_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
}
LEDGER_ASP_COMPS: Dict[str, str] = {NONCE_ASP: "nonce_appr", "hashevidence": "goldenbytes_appr"}
LEDGER_ASPS = sorted(LEDGER_ASP_TYPES)

_SIG = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}
_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}


def _asp(asp_id: str, args: dict) -> dict:
    return {"TERM_CONSTRUCTOR": "asp",
            "TERM_BODY": {"ASP_CONSTRUCTOR": "ASPC", "ASP_BODY": {"ASP_ID": asp_id, "ASP_ARGS": args}}}


def _lseq(a: dict, b: dict) -> dict:
    return {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [a, b]}


def _bseq(sp: str, a: dict, b: dict) -> dict:
    return {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": [sp, a, b]}


# ── protocol augmentation ────────────────────────────────────────────────────


def ledger_session(session: dict) -> dict:
    """The protocol's session plus the ASP types/companions ledger runs need."""
    s = copy.deepcopy(session)
    ctx = s.setdefault("Session_Context", {})
    ctx.setdefault("ASP_Types", {}).update(copy.deepcopy(LEDGER_ASP_TYPES))
    ctx.setdefault("ASP_Comps", {}).update(LEDGER_ASP_COMPS)
    return s


def ledger_manifest(manifest: dict) -> dict:
    m = copy.deepcopy(manifest)
    m["ASPS"] = sorted(set(m.get("ASPS", [])) | set(LEDGER_ASPS))
    return m


def ledger_protocol(protocol: Any) -> Any:
    """A copy of the ProtocolDir whose session and manifest carry the ledger
    ASPs; the on-disk protocol directory is untouched."""
    return protocol.model_copy(update={
        "session": ledger_session(protocol.session),
        "manifest": ledger_manifest(protocol.manifest),
        "prebuilt_request": None,
    })


def measurement_term(protocol: Any) -> dict:
    """
    `lseq (bseq left_path (asp generate_nonce) M) SIG` (plan B.1).

    `M` is the protocol's term with APPR stripped and SIG detached
    (provision's strip-APPR-keep-SIG transform yields `lseq M SIG`). A
    protocol without a SIG step yields `bseq left_path (generate_nonce) M`
    and its packages label as `nonce`, not `signed+nonce` (plan B.7).
    """
    from .provision import _measurement_term

    stripped = _measurement_term(normalize_term(inject_asp_args(protocol.term, protocol.asp_args)))
    nonce = _asp(NONCE_ASP, dict(NONCE_ARGS))
    if (stripped.get("TERM_CONSTRUCTOR") == "lseq" and len(stripped["TERM_BODY"]) == 2
            and stripped["TERM_BODY"][1] == _SIG):
        return _lseq(_bseq("left_path", nonce, stripped["TERM_BODY"][0]), _SIG)
    return _bseq("left_path", nonce, stripped)


def appraisal_term() -> dict:
    """`lseq (bseq both_paths (asp hashevidence) APPR) (lseq (asp generate_nonce) SIG)` (plan B.6)."""
    return _lseq(_bseq("both_paths", _asp("hashevidence", {}), _APPR),
                 _lseq(_asp(NONCE_ASP, dict(APPRAISER_NONCE_ARGS)), _SIG))


def _request(protocol: Any, term: dict, evidence: list) -> dict:
    plc = protocol.session.get("Session_Plc", "P0")
    return {"TYPE": "REQUEST", "ACTION": "RUN", "REQ_PLC": plc, "TO_PLC": plc,
            "TERM": term, "EVIDENCE": evidence, "ATTESTATION_SESSION": protocol.session}


def measurement_request(protocol: Any) -> dict:
    """Run-1 request; `protocol` must already be `ledger_protocol(...)`."""
    return _request(protocol, measurement_term(protocol), empty_evidence())


def appraisal_request(protocol: Any, raw_payload: list) -> dict:
    """Run-2 request over the raw package; `protocol` must be `ledger_protocol(...)`."""
    return _request(protocol, appraisal_term(), raw_payload)


# ── appraisal package → the APPR branch the summarizer accepts ───────────────


def appraisal_branch(appraisal_payload: list, session: dict) -> dict:
    """
    The pure appraisal evidence inside a signed appraisal package, as a
    response dict the verified summarizer type-checks (spike: identical
    to an APPR-only run's summary). Structure: asp_evt(sig, asp_evt(
    generate_nonce, split_evt(asp_evt(hashevidence, …), APPR_OUT))).
    Located by slot layout — structural reading only (plan B.9).
    """
    spans = slot_layout(appraisal_payload[1], session)
    hs = [s for s in spans if s.asp == "hashevidence"]
    if len(hs) != 1:
        raise EvidenceLayoutError(f"appraisal package has {len(hs)} hashevidence events, expected 1")
    offset = hs[0].start + hs[0].count
    node = appraisal_payload[1]
    while isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "asp_evt":
        node = node["EvidenceT_BODY"][2]
    if not (isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "split_evt"):
        raise EvidenceLayoutError("appraisal package: no split beneath the signature and nonce events")
    left, right = node["EvidenceT_BODY"]
    if not (isinstance(left, dict) and left.get("EvidenceT_CONSTRUCTOR") == "asp_evt"
            and left["EvidenceT_BODY"][1].get("ASP_ID") == "hashevidence"):
        raise EvidenceLayoutError("appraisal package: left branch is not the hashevidence binding")
    raw = appraisal_payload[0].get("RawEv", [])
    return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True,
            "PAYLOAD": [{"RawEv": raw[offset:]}, right]}


def interpret_appraisal(appraisal_payload: list, protocol: Any) -> Union[List[ComponentResult], str]:
    """Components of the appraisal package: verified summary over the APPR
    branch when the tool is present (fail closed on refusal), else the
    legacy walker. Returns the components, or a refusal string."""
    from . import summarizer

    try:
        branch = appraisal_branch(appraisal_payload, protocol.session)
    except EvidenceLayoutError as e:
        return f"appraisal package not interpretable: {e}"
    if summarizer.available():
        try:
            return summarizer.summarize_response(branch, protocol.session)
        except summarizer.SummaryError as e:
            return f"verified appraisal summary refused: {e}"
    return parse_appraisal(branch, protocol.target_records())


def interpreter_used() -> Interpreter:
    from . import summarizer

    if summarizer.available():
        return Interpreter(kind="verified-summary", tool="copland-evidence-tools")
    return Interpreter(kind="legacy-walker", tool="pybb.attestation.appraisal")


# ── the two-run flow ─────────────────────────────────────────────────────────


class LedgerAttestation(BaseModel):
    """Outcome of one nonce'd two-run attestation (mapped onto a Verdict by
    knowledge_sources). `error` non-empty means the run failed closed."""

    protocol: str
    passed: bool = False
    components: List[ComponentResult] = []
    error: str = ""
    evidence_ref: str = ""
    appraisal_ref: str = ""
    components_ref: str = ""
    nonce_id: str = ""
    ledger_ref: str = ""
    assurance: str = ""


ArchiveFn = Callable[[Any, str, str], str]  # (obj, protocol_id, kind) -> path


def _gz_bytes(path: str) -> bytes:
    return Path(path).read_bytes() if path else b""


def key_fingerprint(path: str) -> str:
    """`sha256:<hex>` of the verifying public key file, "" when absent."""
    try:
        return "sha256:" + hashlib.sha256(Path(os.path.expanduser(path)).read_bytes()).hexdigest()
    except OSError:
        return ""


def _components_json(components: List[ComponentResult]) -> bytes:
    return canonical_json([c.model_dump(mode="json") for c in components])


def _run(client: Any, protocol: Any, request: dict) -> dict:
    return client.run_protocol(protocol.model_copy(update={"prebuilt_request": request}))


def attest_with_ledger(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                       archive: Optional[ArchiveFn] = None,
                       tooling: Optional[ToolingRef] = None) -> LedgerAttestation:
    """
    Measurement run, appraisal run, interpretation, archive, ledger commit.

    Every failure closes: a CVM error, an uninterpretable package, an
    assurance level below `config.min_assurance` (unless excepted), a
    duplicate nonce, or an unreachable ledger (unless `config.fail_open`)
    yields `error` set and `passed=False`.
    """
    pid = protocol.protocol_id
    out = LedgerAttestation(protocol=pid)
    lp = ledger_protocol(protocol)

    # 1. measurement run -> raw signed package
    try:
        resp1 = _run(client, lp, measurement_request(lp))
    except Exception as e:  # CvmError and transport failures alike
        out.error = f"measurement run failed: {e}"
        return out
    if not resp1.get("SUCCESS"):
        out.error = f"measurement run failed: {str(resp1.get('PAYLOAD'))[:300]}"
        return out
    raw_payload = resp1["PAYLOAD"]
    if archive:
        out.evidence_ref = archive(resp1, pid, "response")
    try:
        raw_desc: PackageDescription = describe_package(raw_payload, lp.session)
    except EvidenceLayoutError as e:
        out.error = f"raw package not describable: {e}"
        return out
    if raw_desc.nid is None:
        out.error = "raw package carries no generate_nonce event"
        return out
    out.nonce_id = raw_desc.nid
    out.assurance = raw_desc.assurance

    # 2. appraisal run -> signed appraisal package
    try:
        resp2 = _run(client, lp, appraisal_request(lp, raw_payload))
    except Exception as e:
        out.error = f"appraisal run failed: {e}"
        return out
    if not resp2.get("SUCCESS"):
        out.error = f"appraisal run failed: {str(resp2.get('PAYLOAD'))[:300]}"
        return out
    appr_payload = resp2["PAYLOAD"]
    if archive:
        out.appraisal_ref = archive(resp2, pid, "appraisal")
    try:
        appr_desc = describe_package(appr_payload, lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        out.error = f"appraisal package not describable: {e}"
        return out
    if appr_desc.nid is None:
        out.error = "appraisal package carries no appraiser nonce"
        return out

    # 3. interpretation (the CVM judged; pybb reads)
    components = interpret_appraisal(appr_payload, lp)
    if isinstance(components, str):
        out.error = components
        return out
    stamp_measured_files(components)
    out.components = components
    out.passed = overall_verdict(components)
    if archive:
        out.components_ref = archive([c.model_dump(mode="json") for c in components], pid, "components")

    # 4. assurance policy (plan B.7)
    exception_reason: Optional[str] = None
    if not assurance_at_least(raw_desc.assurance, config.min_assurance):
        exception_reason = config.assurance_exceptions.get(pid)
        if exception_reason is None:
            out.error = (f"assurance {raw_desc.assurance} below minimum "
                         f"{config.min_assurance} (no exception for {pid})")
            out.passed = False
            return out

    # 5. records and the one-batch commit (plan B.3/B.4, D)
    try:
        records = build_run_records(lp, raw_payload, raw_desc, appr_payload, appr_desc,
                                    components, out, config, exception_reason, tooling)
        receipt = ledger.commit_run(*records["batch"], extra=records["locators"])
        out.ledger_ref = f"evidence/{out.nonce_id}"
        _ = receipt
    except DuplicateNonceError as e:
        out.error = f"duplicate nonce: {e}"
        out.passed = False
    except (LedgerError, OSError) as e:
        if config.fail_open:
            out.error = ""  # recorded nowhere; the verdict stands, unledgered
            out.ledger_ref = ""
        else:
            out.error = f"ledger commit failed: {e}"
            out.passed = False
    return out


def build_run_records(lp: Any, raw_payload: list, raw_desc: PackageDescription,
                      appr_payload: list, appr_desc: PackageDescription,
                      components: List[ComponentResult], out: LedgerAttestation,
                      config: LedgerConfig, exception_reason: Optional[str],
                      tooling: Optional[ToolingRef]) -> Dict[str, Any]:
    """The five records of a run plus local locator records for the
    appraisal and components blobs (plan I)."""
    pid = lp.protocol_id
    nid, anid = raw_desc.nid, appr_desc.nid
    assert nid and anid and raw_desc.nonce and appr_desc.nonce
    appraiser_id = config.appraiser_id or load_appraiser_id(config.state_dir)
    committer_fp = key_fingerprint(config.verify_key_path)
    env = dict(committer_fp=committer_fp, pybb_version=pybb_version(), appraiser_id=appraiser_id)
    raw_b64 = raw_payload[0]["RawEv"]
    appr_b64 = appr_payload[0]["RawEv"]

    nonce = NonceRecord(nid=nid, nonce_b64=raw_b64[raw_desc.nonce.slot], nonce_bytes=NONCE_BYTES,
                        role="measurement", protocol_id=pid, **env)
    appraiser_nonce = NonceRecord(nid=anid, nonce_b64=appr_b64[appr_desc.nonce.slot],
                                  nonce_bytes=NONCE_BYTES, role="appraisal", for_nid=nid,
                                  protocol_id=pid, **env)
    raw_blob = _gz_bytes(out.evidence_ref)
    sig = raw_desc.signature.model_copy(update={"signer_fp": committer_fp or None})
    evidence = EvidenceRecord(
        nid=nid, protocol_id=pid,
        term_sha256=sha256_hex(canonical_json(lp.term)),
        session_sha256=sha256_hex(canonical_json(lp.session)),
        manifest_sha256=sha256_hex(canonical_json(lp.manifest)),
        response_sha256=raw_desc.response_sha256, blob_sha256=sha256_hex(raw_blob),
        blob_bytes=len(raw_blob), rawev_count=raw_desc.rawev_count,
        rawev_sha256=raw_desc.rawev_sha256, signature=sig, nonce=raw_desc.nonce,
        assurance=raw_desc.assurance, exception_reason=exception_reason, tooling=tooling,
        locators=[Locator(kind="local", path=out.evidence_ref, appraiser_id=appraiser_id)]
        if out.evidence_ref else [], **env)

    hs = appr_desc.span_for("hashevidence")
    if hs is None:
        raise LedgerError("appraisal package has no hashevidence binding")
    binding = Binding(slot=hs.start, evidence_hash=base64.b64decode(appr_b64[hs.start]).hex())
    appr_blob = _gz_bytes(out.appraisal_ref)
    comp_bytes = _components_json(components)
    interp = interpreter_used()
    appraisal = AppraisalRecord(
        nid=nid, seq=1, mode="live", anid=anid,
        response_sha256=appr_desc.response_sha256, blob_sha256=sha256_hex(appr_blob),
        blob_bytes=len(appr_blob), rawev_sha256=appr_desc.rawev_sha256, binding=binding,
        signature=appr_desc.signature.model_copy(update={"signer_fp": committer_fp or None}),
        nonce=appr_desc.nonce, assurance=appr_desc.assurance, passed=out.passed,
        components_sha256=sha256_hex(comp_bytes), interpreter=interp, tooling=tooling, **env)

    failing = [FailingComponent(targ_id=c.targ_id, appr_asp=c.appr_asp, reason=c.reason)
               for c in components if not c.passed]
    verdict = VerdictRecord(
        nid=nid, protocol_id=pid, passed=out.passed, components_total=len(components),
        components_failed=len(failing), failing=failing, components_sha256=sha256_hex(comp_bytes),
        appraisal_seq=1, evidence_assurance=raw_desc.assurance,
        appraisal_assurance=appr_desc.assurance, interpreter=interp, error=out.error, **env)

    locators: List[LocatorRecord] = []
    seq = 1
    if out.appraisal_ref:
        locators.append(LocatorRecord(nid=nid, seq=seq, target="appraisal", blob_sha256=sha256_hex(appr_blob),
                                      locator=Locator(kind="local", path=out.appraisal_ref,
                                                      appraiser_id=appraiser_id), verified=True, **env))
        seq += 1
    if out.components_ref:
        comp_blob = _gz_bytes(out.components_ref)
        locators.append(LocatorRecord(nid=nid, seq=seq, target="components", blob_sha256=sha256_hex(comp_blob),
                                      locator=Locator(kind="local", path=out.components_ref,
                                                      appraiser_id=appraiser_id), verified=True, **env))
    return {"batch": (nonce, appraiser_nonce, evidence, appraisal, verdict), "locators": locators}


def write_gz_json(path: Path, obj: Any) -> None:
    """Archive helper shared with knowledge_sources: canonical for lists
    (the components artifact), plain JSON for CVM responses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(obj) if isinstance(obj, list) else json.dumps(obj).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(data)


# ── fetch and re-appraise from the ledger (plan B.5, B.6 audits, E) ─────────


class FetchedRun(BaseModel):
    records: Any  # RunRecords
    payload: list  # the raw package [RawEv, EvidenceT]
    blob_sha256: str
    locator: Locator


def resolve_locator(loc: Locator) -> Optional[bytes]:
    """Bytes behind a locator, or None when it does not resolve here. `local`
    paths are tried as given and relative to the current directory; `github`
    resolution arrives with the evidence repo (plan H, step 6)."""
    if loc.kind == "local":
        for cand in (Path(loc.path), Path.cwd() / loc.path):
            if cand.is_file():
                return cand.read_bytes()
        return None
    if loc.kind == "github":
        from .ledger_repo import resolve_github_locator

        return resolve_github_locator(loc)
    return None


def _decode_blob(blob: bytes, encoding: str) -> Any:
    data = gzip.decompress(blob) if encoding.startswith("gzip") else blob
    return json.loads(data)


def fetch_run(ledger: Ledger, nid: str, locators_extra: Optional[List[Locator]] = None) -> FetchedRun:
    """Verified-read the run's records, then the raw package via its locators
    in order (evidence record's own, then `locator` records of target
    `evidence`, then `locators_extra`); refuse bytes whose hash is not the
    record's `blob_sha256`."""
    records = ledger.get(nid)
    ev = records.evidence
    candidates: List[Locator] = list(ev.locators)
    candidates += [l.locator for l in records.locators if l.target == "evidence"]
    candidates += list(locators_extra or [])
    for loc in candidates:
        blob = resolve_locator(loc)
        if blob is None:
            continue
        if sha256_hex(blob) != ev.blob_sha256:
            raise LedgerError(f"locator {loc.kind}:{loc.path} resolves to bytes whose sha256 "
                              f"is not the ledger's blob_sha256 for {nid}")
        obj = _decode_blob(blob, ev.encoding)
        payload = obj["PAYLOAD"] if isinstance(obj, dict) and "PAYLOAD" in obj else obj
        return FetchedRun(records=records, payload=payload, blob_sha256=ev.blob_sha256, locator=loc)
    raise LedgerError(f"no locator of run {nid} resolves on this host")


class LedgerAppraisal(BaseModel):
    """Report of a ledger-driven appraisal (plan B.5): either a fresh signed
    appraisal of the raw package (`audits_seq` None) or a CVM-native audit of
    an appraisal package (`audits_seq` set). Truthy iff every check holds
    and the appraisal passed."""

    nid: str
    seq: int = 0
    mode: str = "audit"
    audits_seq: Optional[int] = None
    ledger_verified: bool = False
    bytes_match: bool = False
    nid_ok: bool = False
    signature_ok: Optional[bool] = None  # the sig_appr verdict (CVM)
    nonce_wellformed: Optional[bool] = None  # the nonce_appr verdict (CVM)
    binding_ok: Optional[bool] = None  # audit of appraisal: goldenbytes_appr over the binding (CVM)
    passed: bool = False
    agrees_with_recorded_verdict: Optional[bool] = None
    components: List[ComponentResult] = []
    assurance: str = ""
    freshness: str = "post-hoc"
    locator_used: Optional[Locator] = None
    appraisal_ref: str = ""
    ledger_ref: str = ""
    error: str = ""

    def __bool__(self) -> bool:
        return (self.error == "" and self.ledger_verified and self.bytes_match and self.nid_ok
                and self.passed and self.signature_ok is not False and self.nonce_wellformed is not False
                and self.binding_ok is not False)


def _verdict_of(components: List[ComponentResult], appr_asp: str) -> Optional[bool]:
    hits = [c.passed for c in components if c.appr_asp == appr_asp]
    return None if not hits else all(hits)


def _next_seq(records: Any) -> int:
    return max([a.seq for a in records.appraisals] + [0]) + 1


def _commit_audit(ledger: Ledger, lp: Any, nid: str, seq: int, appr_payload: list,
                  appr_desc: PackageDescription, components: List[ComponentResult],
                  report: LedgerAppraisal, config: LedgerConfig, binding: Binding,
                  interpreter: Interpreter, audits_seq: Optional[int], tooling: Optional[ToolingRef]) -> None:
    appraiser_id = config.appraiser_id or load_appraiser_id(config.state_dir)
    committer_fp = key_fingerprint(config.verify_key_path)
    env = dict(committer_fp=committer_fp, pybb_version=pybb_version(), appraiser_id=appraiser_id)
    assert appr_desc.nid and appr_desc.nonce
    anonce = NonceRecord(nid=appr_desc.nid, nonce_b64=appr_payload[0]["RawEv"][appr_desc.nonce.slot],
                         nonce_bytes=NONCE_BYTES, role="appraisal", for_nid=nid,
                         protocol_id=lp.protocol_id, **env)
    blob = _gz_bytes(report.appraisal_ref)
    comp_bytes = _components_json(components)
    rec = AppraisalRecord(
        nid=nid, seq=seq, mode="audit", anid=appr_desc.nid, audits_seq=audits_seq,
        response_sha256=appr_desc.response_sha256, blob_sha256=sha256_hex(blob), blob_bytes=len(blob),
        rawev_sha256=appr_desc.rawev_sha256, binding=binding,
        signature=appr_desc.signature.model_copy(update={"signer_fp": committer_fp or None}),
        nonce=appr_desc.nonce, assurance=appr_desc.assurance, freshness=report.freshness,
        passed=report.passed, components_sha256=sha256_hex(comp_bytes), interpreter=interpreter,
        tooling=tooling,
        checks={"ledger_verified": report.ledger_verified, "bytes_match": report.bytes_match,
                "nid_ok": report.nid_ok},
        locator_used=report.locator_used,
        agrees_with_recorded_verdict=report.agrees_with_recorded_verdict, **env)
    extra: List[LocatorRecord] = []
    if report.appraisal_ref:
        next_loc = max([l.seq for l in ledger.get(nid).locators] + [0]) + 1
        extra.append(LocatorRecord(nid=nid, seq=next_loc, target="appraisal", blob_sha256=sha256_hex(blob),
                                   locator=Locator(kind="local", path=report.appraisal_ref,
                                                   appraiser_id=appraiser_id), verified=True, **env))
    ledger.append_appraisal(rec, anonce, extra=extra)
    report.seq = seq
    report.ledger_ref = key_for(rec)


def appraise_record(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig, nid: str,
                    archive: Optional[ArchiveFn] = None,
                    tooling: Optional[ToolingRef] = None) -> LedgerAppraisal:
    """
    Plan B.5: fetch the raw package from the ledger, check it structurally
    (bytes and nonce id against the records), run the signed B.6 appraisal
    term over it, interpret via the summarizer, compare with the recorded
    verdict, and append an `appraisal` record (mode audit) with a fresh
    appraiser nonce. A disagreement is surfaced, never re-decided.
    """
    rep = LedgerAppraisal(nid=nid)
    lp = ledger_protocol(protocol)
    try:
        fetched = fetch_run(ledger, nid)
    except LedgerError as e:
        rep.error = f"fetch failed: {e}"
        return rep
    records = fetched.records
    rep.ledger_verified = True  # ledger.get() succeeded through verified reads
    rep.bytes_match = True  # fetch_run refuses mismatching bytes
    rep.locator_used = fetched.locator
    rep.freshness = records.nonce.freshness
    if records.evidence.protocol_id != protocol.protocol_id:
        rep.error = f"run {nid} is of protocol {records.evidence.protocol_id}, not {protocol.protocol_id}"
        return rep
    try:
        raw_desc = describe_package(fetched.payload, lp.session)
    except EvidenceLayoutError as e:
        rep.error = f"fetched package not describable: {e}"
        return rep
    rep.nid_ok = (raw_desc.nid == nid and raw_desc.rawev_sha256 == records.evidence.rawev_sha256)
    if not rep.nid_ok:
        rep.error = "fetched package does not reproduce the recorded nonce id / rawev hash"
        return rep

    try:
        resp = _run(client, lp, appraisal_request(lp, fetched.payload))
    except Exception as e:
        rep.error = f"audit appraisal run failed: {e}"
        return rep
    if not resp.get("SUCCESS"):
        rep.error = f"audit appraisal run failed: {str(resp.get('PAYLOAD'))[:300]}"
        return rep
    appr_payload = resp["PAYLOAD"]
    if archive:
        rep.appraisal_ref = archive(resp, protocol.protocol_id, "audit-appraisal")
    try:
        appr_desc = describe_package(appr_payload, lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        rep.error = f"audit appraisal package not describable: {e}"
        return rep
    if appr_desc.nid is None:
        rep.error = "audit appraisal package carries no appraiser nonce"
        return rep
    rep.assurance = appr_desc.assurance
    components = interpret_appraisal(appr_payload, lp)
    if isinstance(components, str):
        rep.error = components
        return rep
    rep.components = components
    rep.passed = overall_verdict(components)
    rep.signature_ok = _verdict_of(components, "sig_appr")
    rep.nonce_wellformed = _verdict_of(components, "nonce_appr")
    rep.agrees_with_recorded_verdict = (rep.passed == records.verdict.passed)

    hs = appr_desc.span_for("hashevidence")
    if hs is None:
        rep.error = "audit appraisal package has no hashevidence binding"
        return rep
    binding = Binding(slot=hs.start, evidence_hash=base64.b64decode(appr_payload[0]["RawEv"][hs.start]).hex())
    try:
        _commit_audit(ledger, lp, nid, _next_seq(records), appr_payload, appr_desc, components, rep,
                      config, binding, interpreter_used(), None, tooling)
    except (LedgerError, OSError) as e:
        rep.error = f"audit record not committed: {e}"
    return rep


# ── CVM-native audit of an APPRAISAL package (plan B.6, 'audit of the audit') ─


PASSTHROUGH_APPR = "magic_appr"


def audit_session(session: dict, appraiser_asps: List[str]) -> dict:
    """The B.6 audit session: every appraiser ASP that appears in the package
    gets the pass-through companion, so APPR over an appraisal package judges
    its `sig`, `generate_nonce` and `hashevidence` events and passes the
    verdict nodes through."""
    s = ledger_session(session)
    comps = s["Session_Context"]["ASP_Comps"]
    for a in appraiser_asps:
        comps.setdefault(a, PASSTHROUGH_APPR)
    return s


def inject_binding_golden(et: Any, golden_b64: str) -> Any:
    """Put `golden_b64` into the hashevidence event's args of an appraisal
    package's (unsigned) evidence type — the `_inject_goldens` pattern — so
    `goldenbytes_appr` judges the binding against the recorded hash."""
    et = copy.deepcopy(et)

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        c, b = n.get("EvidenceT_CONSTRUCTOR"), n.get("EvidenceT_BODY")
        if c == "asp_evt":
            if b[1].get("ASP_ID") == "hashevidence":
                args = dict(b[1].get("ASP_ARGS") or {})
                args["golden_b64"] = golden_b64
                b[1]["ASP_ARGS"] = args
            walk(b[2])
        elif c == "split_evt":
            walk(b[0]); walk(b[1])
        elif c in ("left_evt", "right_evt"):
            walk(b if isinstance(b, dict) else b[0])

    walk(et)
    return et


def components_from_layout(branch_payload: list, session: dict) -> List[ComponentResult]:
    """Per-appraiser verdicts of an appraisal-output tree read by slot layout
    (REPLACE appraisers: one verdict slot each). Used where the verified
    summarizer refuses the shape (audits of appraisal packages)."""
    from .appraisal import _decode_verdict

    raw = branch_payload[0]["RawEv"]
    out: List[ComponentResult] = []

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        c, b = n.get("EvidenceT_CONSTRUCTOR"), n.get("EvidenceT_BODY")
        if c == "split_evt":
            walk(b[0]); walk(b[1])
        elif c in ("left_evt", "right_evt"):
            walk(b if isinstance(b, dict) else b[0])
        elif c == "asp_evt":
            params, sub = b[1], b[2]
            asp = params.get("ASP_ID", "")
            if asp.endswith("_appr"):
                out.append((asp, dict(params.get("ASP_ARGS") or {}), sub))
            else:
                walk(sub)

    def appraised_asp(sub: Any) -> str:
        """The appraised event: the CVM records it as a path of left_evt /
        right_evt wrappers (outermost wrapper = innermost split choice)
        over the original evidence type, so follow the path through the
        splits down to an asp_evt."""
        dirs: List[str] = []
        node = sub
        while isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") in ("left_evt", "right_evt"):
            dirs.append(node["EvidenceT_CONSTRUCTOR"])
            b = node.get("EvidenceT_BODY")
            node = b if isinstance(b, dict) else (b[0] if b else None)
        for d in reversed(dirs):
            if not (isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "split_evt"):
                break
            node = node["EvidenceT_BODY"][0 if d == "left_evt" else 1]
        if isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "asp_evt":
            return node["EvidenceT_BODY"][1].get("ASP_ID", "unknown")
        return "unknown"

    walk(branch_payload[1])
    comps: List[ComponentResult] = []
    for i, (asp, args, sub) in enumerate(out):
        passed, reason = _decode_verdict(raw[i] if i < len(raw) else "")
        target = appraised_asp(sub)
        comps.append(ComponentResult(appr_asp=asp, target_asp=target, targ_id=args.get("asp_targid"),
                                     passed=passed, reason=reason, args=args, description=target))
    return comps


def audit_appraisal_package(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                            nid: str, seq: int = 1, archive: Optional[ArchiveFn] = None,
                            tooling: Optional[ToolingRef] = None) -> LedgerAppraisal:
    """
    Plan B.6: judge a recorded appraisal package inside the CVM — its
    signature (`sig_appr`), its appraiser nonce (`nonce_appr`) and its binding
    to the raw package (`goldenbytes_appr` against the evidence record's
    `rawev_sha256`) — using the same signed B.6 term, so the audit is itself a
    signed, nonce-bound appraisal package recorded with `audits_seq`.
    """
    rep = LedgerAppraisal(nid=nid, audits_seq=seq)
    try:
        records = ledger.get(nid)
    except LedgerError as e:
        rep.error = f"fetch failed: {e}"
        return rep
    target = next((a for a in records.appraisals if a.seq == seq), None)
    if target is None:
        rep.error = f"run {nid} has no appraisal seq {seq}"
        return rep
    rep.ledger_verified = True
    rep.freshness = records.nonce.freshness
    loc = next((l.locator for l in records.locators if l.target == "appraisal"
                and l.blob_sha256 == target.blob_sha256), None)
    blob = resolve_locator(loc) if loc else None
    if blob is None:
        rep.error = f"appraisal package of {nid} seq {seq} does not resolve on this host"
        return rep
    if sha256_hex(blob) != target.blob_sha256:
        rep.error = "appraisal package bytes do not match the ledger's blob_sha256"
        return rep
    rep.bytes_match = True
    rep.locator_used = loc
    obj = _decode_blob(blob, target.encoding)
    appr_payload = obj["PAYLOAD"] if isinstance(obj, dict) and "PAYLOAD" in obj else obj

    lp = ledger_protocol(protocol)
    try:
        d = describe_package(appr_payload, lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        rep.error = f"appraisal package not describable: {e}"
        return rep
    rep.nid_ok = (d.nid == target.anid and d.rawev_sha256 == target.rawev_sha256)
    if not rep.nid_ok:
        rep.error = "appraisal package does not reproduce the recorded appraiser nonce id / rawev hash"
        return rep

    appraiser_asps = sorted({s.asp for s in d.spans if s.asp.endswith("_appr")})
    session = audit_session(protocol.session, appraiser_asps)
    golden_b64 = base64.b64encode(bytes.fromhex(records.evidence.rawev_sha256)).decode()
    evidence = [appr_payload[0], inject_binding_golden(appr_payload[1], golden_b64)]
    ap = lp.model_copy(update={"session": session,
                               "manifest": {**lp.manifest, "ASPS": sorted(set(lp.manifest["ASPS"]) | {PASSTHROUGH_APPR})}})
    try:
        resp = _run(client, ap, _request(ap, appraisal_term(), evidence))
    except Exception as e:
        rep.error = f"audit run failed: {e}"
        return rep
    if not resp.get("SUCCESS"):
        rep.error = f"audit run failed: {str(resp.get('PAYLOAD'))[:300]}"
        return rep
    audit_payload = resp["PAYLOAD"]
    if archive:
        rep.appraisal_ref = archive(resp, protocol.protocol_id, f"audit-of-appraisal-{seq}")
    try:
        ad = describe_package(audit_payload, session, nonce_targid=APPRAISER_NONCE_TARGID)
        branch = appraisal_branch(audit_payload, session)
    except EvidenceLayoutError as e:
        rep.error = f"audit package not describable: {e}"
        return rep
    if ad.nid is None:
        rep.error = "audit package carries no appraiser nonce"
        return rep
    rep.assurance = ad.assurance
    components = components_from_layout(branch["PAYLOAD"], session)
    rep.components = components
    rep.signature_ok = _verdict_of(components, "sig_appr")
    rep.nonce_wellformed = _verdict_of(components, "nonce_appr")
    rep.binding_ok = _verdict_of(components, "goldenbytes_appr")
    rep.passed = overall_verdict(components)
    rep.agrees_with_recorded_verdict = None  # this audit judges the appraisal package, not the targets

    hs = ad.span_for("hashevidence")
    if hs is None:
        rep.error = "audit package has no hashevidence binding"
        return rep
    binding = Binding(slot=hs.start, evidence_hash=base64.b64decode(audit_payload[0]["RawEv"][hs.start]).hex(),
                      matches_evidence=rep.binding_ok)
    interp = Interpreter(kind="legacy-walker", tool="pybb.attestation.ledger_runs.components_from_layout")
    try:
        _commit_audit(ledger, lp, nid, _next_seq(records), audit_payload, ad, components, rep,
                      config, binding, interp, seq, tooling)
    except (LedgerError, OSError) as e:
        rep.error = f"audit record not committed: {e}"
    return rep
