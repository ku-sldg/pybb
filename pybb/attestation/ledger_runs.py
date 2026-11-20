"""
Nonce'd, two-run attestation that lands in the ledger as bundles
(docs/ledger_plan.md, sections B.0–B.7, D, K).

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

Each package becomes one `bundle` record (plan K): the measurement with
`role: measurement`, the appraisal with `role: appraisal`, `inputs` naming
the measurement it judged (bound by the `hashevidence` slot) and the
`verdict` pybb read from it. Both are committed in one batch, each keyed by
the sha256 of its own nonce. `appraise_bundle` runs the same appraisal
term over any stored bundle, under any session (policy), and records one
more appraisal bundle pointing at it — a different appraisal of the same
measurement, or an audit of an appraisal package (plan B.6: judged inside
the CVM via `magic_appr` pass-through + `goldenbytes_appr` over the
binding). pybb never judges: signatures, nonces and goldens are
companion-ASP verdicts read back through the verified summarizer (over
the extracted APPR branch) — plan B.9.

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
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel

from .appraisal import ComponentResult, overall_verdict, parse_appraisal, stamp_measured_files
from .copland import empty_evidence, inject_asp_args, normalize_term
from .ledger import (
    APPRAISER_NONCE_TARGID,
    NONCE_ASP,
    NONCE_TARGID,
    BlobRef,
    BundleRecord,
    DuplicateNonceError,
    EvidenceLayoutError,
    FailingComponent,
    InputRef,
    Interpreter,
    Ledger,
    LedgerConfig,
    LedgerError,
    Location,
    NonceInfo,
    PackageDescription,
    ProvisionInfo,
    SignatureInfo,
    ToolingRef,
    Verdict,
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


SHAPES = ("split", "combined")
HASHEVIDENCE_KEEP = {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "ALL"}, "ATTRS": []}


def combined_session(session: dict) -> dict:
    """The ledger session with `hashevidence` typed EXTEND (plan M.2): its
    output is prepended to its input, so the hash lane keeps the signed
    measurement P behind the hash. Used for `combined` runs and for reading
    (and auditing) the packages they produced — one FWD per ASP id per
    session, so an audit run over a combined package retains its input too
    (M.2 caveat; accepted in M.6)."""
    s = ledger_session(session)
    s["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
    return s


def combined_term(protocol: Any) -> dict:
    """
    One run, both artifacts (plan M.2):

        lseq M (lseq (bseq both_paths (lseq (lseq (asp generate_nonce) SIG) (asp hashevidence))
                                      APPR)
                     (lseq (asp generate_nonce) SIG))

    `M`'s evidence goes to both lanes: the signing lane draws the measurement
    nonce, signs (P), then `hashevidence` (EXTEND) prepends H = sha256(P) and
    keeps P; the APPR lane judges `M`'s evidence only, so no companion for
    `sig` or `generate_nonce` runs live. Then the appraiser nonce and the
    outer SIG. `M` is the protocol's term with APPR stripped and SIG detached.
    """
    from .provision import _measurement_term

    stripped = _measurement_term(normalize_term(inject_asp_args(protocol.term, protocol.asp_args)))
    if (stripped.get("TERM_CONSTRUCTOR") == "lseq" and len(stripped["TERM_BODY"]) == 2
            and stripped["TERM_BODY"][1] == _SIG):
        stripped = stripped["TERM_BODY"][0]
    sign_lane = _lseq(_lseq(_asp(NONCE_ASP, dict(NONCE_ARGS)), _SIG), _asp("hashevidence", {}))
    return _lseq(stripped, _lseq(_bseq("both_paths", sign_lane, _APPR),
                                 _lseq(_asp(NONCE_ASP, dict(APPRAISER_NONCE_ARGS)), _SIG)))


def combined_request(protocol: Any) -> dict:
    """The one request of a `combined` run; `protocol` must carry `combined_session`."""
    return _request(protocol, combined_term(protocol), empty_evidence())


def shaped_protocol(protocol: Any, shape: str) -> Any:
    """`ledger_protocol` with the session typing the shape needs."""
    lp = ledger_protocol(protocol)
    if shape == "combined":
        return lp.model_copy(update={"session": combined_session(protocol.session)})
    return lp


def session_for_bundle(protocol: Any, bundle: Any) -> dict:
    """The session under which a stored bundle's package lays out: combined
    packages need the EXTEND `hashevidence` typing, everything else the
    ordinary ledger session."""
    if getattr(bundle, "shape", None) == "combined":
        return combined_session(protocol.session)
    return ledger_session(protocol.session)


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
    left, right, offset = hash_lane(appraisal_payload, session)
    raw = appraisal_payload[0].get("RawEv", [])
    return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True,
            "PAYLOAD": [{"RawEv": raw[offset:]}, right]}


def hash_lane(appraisal_payload: list, session: dict) -> Tuple[dict, dict, int]:
    """
    Locate the `bseq both_paths (… hashevidence) APPR` split beneath the
    signature and nonce events of an appraisal package: returns the
    hashevidence lane's type, the APPR lane's type, and the RawEv offset at
    which the APPR lane starts. Under a REPLACE `hashevidence` the lane is
    one slot; under EXTEND (`combined`, plan M.2) it is the hash followed by
    the retained input, so the offset skips that input too — its size comes
    from laying out the type beneath the `hashevidence` node.
    """
    et = appraisal_payload[1]
    spans = slot_layout(et, session)
    hs = [s for s in spans if s.asp == "hashevidence" and not s.input]  # this run's, not a retained input's
    if len(hs) != 1:
        raise EvidenceLayoutError(f"appraisal package has {len(hs)} hashevidence events, expected 1")
    node = et
    while isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "asp_evt":
        node = node["EvidenceT_BODY"][2]
    if not (isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "split_evt"):
        raise EvidenceLayoutError("appraisal package: no split beneath the signature and nonce events")
    left, right = node["EvidenceT_BODY"]
    hev = left
    while isinstance(hev, dict) and hev.get("EvidenceT_CONSTRUCTOR") == "asp_evt" \
            and hev["EvidenceT_BODY"][1].get("ASP_ID") != "hashevidence":
        hev = hev["EvidenceT_BODY"][2]
    if not (isinstance(hev, dict) and hev.get("EvidenceT_CONSTRUCTOR") == "asp_evt"):
        raise EvidenceLayoutError("appraisal package: left lane carries no hashevidence binding")
    fwd = ((session.get("Session_Context", {}).get("ASP_Types", {}).get("hashevidence") or {})
           .get("FWD") or {}).get("FWD")
    offset = hs[0].start + hs[0].count
    if fwd == "EXTEND":
        offset += sum(sp.count for sp in slot_layout(hev["EvidenceT_BODY"][2], session))
    return left, right, offset


def lift_measurement(combined_payload: list, session: dict) -> list:
    """The signed measurement package P inside a `combined` package: the
    slots beneath the EXTEND `hashevidence` node, with that node's input
    type — byte for byte what a `measure` run would have returned, except
    that the nonce wraps `M` instead of sitting beside it (plan M.2)."""
    left, _right, _offset = hash_lane(combined_payload, session)
    hev = left
    while hev["EvidenceT_BODY"][1].get("ASP_ID") != "hashevidence":
        hev = hev["EvidenceT_BODY"][2]
    et_p = hev["EvidenceT_BODY"][2]
    spans = slot_layout(combined_payload[1], session)
    hs = next(s for s in spans if s.asp == "hashevidence" and not s.input)
    size = sum(sp.count for sp in slot_layout(et_p, session))
    raw = combined_payload[0]["RawEv"]
    return [{"RawEv": raw[hs.start + hs.count: hs.start + hs.count + size]}, et_p]


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


# ── bundles: the one record builder (plan K.1) ───────────────────────────────


class LedgerAttestation(BaseModel):
    """Outcome of one nonce'd two-run attestation (mapped onto a Verdict by
    knowledge_sources). `error` non-empty means the run failed closed."""

    protocol: str
    passed: bool = False
    components: List[ComponentResult] = []
    error: str = ""
    evidence_ref: str = ""  # archived measurement package (local path)
    appraisal_ref: str = ""  # archived appraisal package (local path)
    components_ref: str = ""
    bid: str = ""  # the measurement bundle id
    appraisal_bid: str = ""  # the appraisal bundle id
    ledger_ref: str = ""  # `bundle/<appraisal bid>`: the appraisal the verdict came from
    assurance: str = ""
    shape: str = ""  # the bundle shape that ran (plan M)

    @property
    def nonce_id(self) -> str:  # transitional name
        return self.bid


class LedgerMeasurement(BaseModel):
    """Outcome of a measurement-only run (plan N.1): the measurement bundle is
    in the ledger, nothing has judged it. Mapped onto `Measured` by
    knowledge_sources. `error` non-empty means nothing was recorded."""

    protocol: str
    bid: str = ""
    evidence_ref: str = ""
    assurance: str = ""
    ledger_ref: str = ""  # `bundle/<bid>`
    shape: str = "measure"
    error: str = ""


ArchiveFn = Callable[[Any, str, str], str]  # (obj, protocol_id, kind) -> path


def archiver(archive_dir: Any) -> ArchiveFn:
    """
    The standard archive callback: gzipped JSON under one directory per
    predicate instance, `<archive_dir>/<UTC stamp>-<4 hex>/<protocol>.<kind>[.<n>].json.gz`.
    Two instances started in the same second never share a directory; the
    name is an archive detail, not a ledger field (plan schema point 5).
    Lists (component artifacts) are written canonically so their hash is
    stable; CVM responses are written as plain JSON.
    """
    import secrets
    import time

    root = Path(os.path.expanduser(str(archive_dir)))
    episode: Dict[str, Path] = {}

    def archive(obj: Any, protocol_id: str, kind: str = "response") -> str:
        if "dir" not in episode:
            episode["dir"] = root / (time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2))
        d = episode["dir"]
        path = d / f"{protocol_id}.{kind}.json.gz"
        n = 1
        while path.exists():
            n += 1
            path = d / f"{protocol_id}.{kind}.{n}.json.gz"
        write_gz_json(path, obj)
        return str(path)

    return archive


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


def record_env(config: LedgerConfig) -> Dict[str, str]:
    appraiser_id = config.appraiser_id or load_appraiser_id(config.state_dir)
    return dict(committer_fp=key_fingerprint(config.verify_key_path),
                pybb_version=pybb_version(), appraiser_id=appraiser_id)


def blob_ref(path: str, data: Optional[bytes] = None, encoding: str = "gzip+json",
             remote_stores: Optional[List[str]] = None) -> BlobRef:
    """A BlobRef for archived bytes at `path`: the local location plus the
    content-addressed path every configured remote store will hold it at
    (plan K decision 7: locations are stated at commit, witnessed by
    `mirror` records)."""
    if not path and data is None:  # nothing archived: no bytes anywhere, so no locations are stated
        return BlobRef(blob_sha256="", blob_bytes=0, encoding=encoding, locations=[])
    if data is None:
        data = _gz_bytes(path)
    sha = sha256_hex(data)
    locs = [Location(store="local", path=str(path))] if path else []
    ext = ".json.gz" if encoding.startswith("gzip") else ".json"
    for store in remote_stores or []:
        locs.append(Location(store=store, path=f"blobs/{sha}{ext}"))
    return BlobRef(blob_sha256=sha, blob_bytes=len(data), encoding=encoding, locations=locs)


def build_bundle_record(role: str, lp: Any, payload: list, desc: PackageDescription,
                        blob: BlobRef, config: LedgerConfig, *,
                        protocol_id: Optional[str] = None,
                        inputs: Optional[List[InputRef]] = None,
                        verdict: Optional[Verdict] = None,
                        appraisal_kind: Optional[str] = None,
                        provision: Optional[ProvisionInfo] = None,
                        tooling: Optional[ToolingRef] = None,
                        exception_reason: Optional[str] = None,
                        error: str = "", shape: Optional[str] = None) -> BundleRecord:
    """The one bundle builder (plan K.1): the package as `describe_package`
    read it, the protocol files it ran under, where its bytes are, and the
    role-gated members the caller supplies. The role is asserted against
    the package: an appraisal package carries a `hashevidence` binding and
    an appraiser nonce, the others do not."""
    hs = desc.span_for("hashevidence")
    if role == "appraisal":
        if hs is None:
            raise LedgerError("appraisal bundle: package has no hashevidence binding")
        if not inputs or verdict is None:
            raise LedgerError("appraisal bundle: inputs and verdict are required")
        raw_b64 = payload[0]["RawEv"]
        bound = base64.b64decode(raw_b64[hs.start]).hex()
        inputs = [i.model_copy(update={"binding_hash": bound}) for i in inputs]
    elif hs is not None and role != "challenge":
        raise LedgerError(f"{role} bundle: package carries a hashevidence binding (is it an appraisal?)")
    env = record_env(config)
    nonce: Optional[NonceInfo] = None
    if desc.nonce is not None and desc.nonce_b64 is not None:
        nonce = NonceInfo(asp=desc.nonce.asp, b64=desc.nonce_b64,
                          bytes=len(base64.b64decode(desc.nonce_b64)))
    sig = desc.signature.model_copy(update={"signer_fp": env["committer_fp"] or None}) \
        if desc.signature.present else SignatureInfo(present=False)
    return BundleRecord(
        bid=desc.bid, role=role, protocol_id=protocol_id or lp.protocol_id,
        term_sha256=sha256_hex(canonical_json(lp.term)),
        session_sha256=sha256_hex(canonical_json(lp.session)),
        manifest_sha256=sha256_hex(canonical_json(lp.manifest)),
        response_sha256=desc.response_sha256, blob=blob, rawev_count=desc.rawev_count,
        rawev_sha256=desc.rawev_sha256, nonce=nonce, signature=sig, assurance=desc.assurance,
        freshness="post-hoc" if nonce else "none", exception_reason=exception_reason,
        tooling=tooling, error=error, shape=shape, inputs=inputs, verdict=verdict,
        appraisal_kind=appraisal_kind, provision=provision, **env)


def verdict_from(components: List[ComponentResult], interpreter: Interpreter,
                 components_blob: Optional[BlobRef] = None, checks: Optional[Dict[str, bool]] = None,
                 agrees_with_live: Optional[bool] = None) -> Verdict:
    failing = [FailingComponent(targ_id=c.targ_id, appr_asp=c.appr_asp, reason=c.reason)
               for c in components if not c.passed]
    return Verdict(passed=overall_verdict(components), components_total=len(components),
                   components_failed=len(failing), failing=failing,
                   components_sha256=sha256_hex(_components_json(components)),
                   components_blob=components_blob, interpreter=interpreter,
                   checks=checks or {}, agrees_with_live=agrees_with_live)


def remote_stores(config: LedgerConfig) -> List[str]:
    """Store ids of the configured evidence repo(s), for stated locations."""
    from .ledger_repo import configured_repo

    repo = configured_repo(config)
    return [repo.store_id()] if repo is not None else []


# ── the two-run flow: `attest` (plan K.3, live run) ─────────────────────────


def attest(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
           archive: Optional[ArchiveFn] = None,
           tooling: Optional[ToolingRef] = None,
           shape: Optional[str] = None) -> LedgerAttestation:
    """
    One live attestation of `protocol` under the configured bundle shape
    (plan M): `split` — a measurement run and an appraisal run over it — or
    `combined` — one run yielding the same two artifacts. Either way the
    result is a measurement bundle, its live appraisal bundle with
    `inputs=[measurement]` and `appraisal_kind: live`, and the `judged_by`
    pointer, committed in one batch.

    Every failure closes: a CVM error, an uninterpretable package, an
    assurance level below `config.min_assurance` (unless excepted), a
    duplicate nonce, or an unreachable ledger (unless `config.fail_open`)
    yields `error` set and `passed=False`.
    """
    pid = protocol.protocol_id
    out = LedgerAttestation(protocol=pid)
    shape = shape or config.shape_for(pid)
    if shape not in SHAPES:
        out.error = f"unknown bundle shape '{shape}' for {pid} (one of {', '.join(SHAPES)})"
        return out
    out.shape = shape
    if shape == "combined":
        return _attest_combined(client, protocol, ledger, config, archive, tooling, out)
    return _attest_split(client, protocol, ledger, config, archive, tooling, out)


def _attest_combined(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                     archive: Optional[ArchiveFn], tooling: Optional[ToolingRef],
                     out: LedgerAttestation) -> LedgerAttestation:
    """Shape `combined` (plan M.2): one run; P lifted from the hash lane."""
    pid = protocol.protocol_id
    lp = shaped_protocol(protocol, "combined")

    # 1. the one run
    try:
        resp = _run(client, lp, combined_request(lp))
    except Exception as e:
        out.error = f"combined run failed: {e}"
        return out
    if not resp.get("SUCCESS"):
        out.error = f"combined run failed: {str(resp.get('PAYLOAD'))[:300]}"
        return out
    payload = resp["PAYLOAD"]
    if archive:
        out.appraisal_ref = archive(resp, pid, "appraisal")

    # 2. lift P (the signed measurement) and describe both packages
    try:
        p_payload = lift_measurement(payload, lp.session)
        raw_desc: PackageDescription = describe_package(p_payload, lp.session)
        appr_desc = describe_package(payload, lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        out.error = f"combined package not describable: {e}"
        return out
    if raw_desc.bid is None:
        out.error = "lifted measurement carries no generate_nonce event"
        return out
    if appr_desc.bid is None:
        out.error = "combined package carries no appraiser nonce"
        return out
    out.bid, out.appraisal_bid, out.assurance = raw_desc.bid, appr_desc.bid, raw_desc.assurance
    if archive:  # P as a response of its own, assembled by pybb (blob.derived_from says so)
        out.evidence_ref = archive({"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True, "PAYLOAD": p_payload},
                                   pid, "response")

    # 3. interpretation: the APPR lane judged M only
    components = interpret_appraisal(payload, lp)
    if isinstance(components, str):
        out.error = components
        return out
    stamp_measured_files(components)
    out.components = components
    out.passed = overall_verdict(components)
    if archive:
        out.components_ref = archive([c.model_dump(mode="json") for c in components], pid, "components")

    # 4. assurance policy (plan B.7), on the measurement as lifted
    exception_reason: Optional[str] = None
    if not assurance_at_least(raw_desc.assurance, config.min_assurance):
        exception_reason = config.assurance_exceptions.get(pid)
        if exception_reason is None:
            out.error = (f"assurance {raw_desc.assurance} below minimum "
                         f"{config.min_assurance} (no exception for {pid})")
            out.passed = False
            return out

    # 5. the two bundles, one batch
    try:
        stores = remote_stores(config)
        p_blob = blob_ref(out.evidence_ref, remote_stores=stores)
        p_blob = p_blob.model_copy(update={"derived_from": appr_desc.bid})
        measurement = build_bundle_record("measurement", lp, p_payload, raw_desc, p_blob, config,
                                          tooling=tooling, exception_reason=exception_reason, shape="combined")
        comp_blob = blob_ref(out.components_ref, remote_stores=stores) if out.components_ref else None
        appraisal = build_bundle_record(
            "appraisal", lp, payload, appr_desc, blob_ref(out.appraisal_ref, remote_stores=stores),
            config, inputs=[InputRef(bid=raw_desc.bid)],
            verdict=verdict_from(components, interpreter_used(), comp_blob),
            appraisal_kind="live", tooling=tooling, shape="combined")
        ledger.commit_bundles([measurement, appraisal])
        out.ledger_ref = key_for(appraisal)
    except DuplicateNonceError as e:
        out.error = f"duplicate nonce: {e}"
        out.passed = False
    except (LedgerError, OSError) as e:
        if config.fail_open:
            out.error = ""
            out.ledger_ref = ""
        else:
            out.error = f"ledger commit failed: {e}"
            out.passed = False
    return out


def _measure_step(client: Any, lp: Any, pid: str, archive: Optional[ArchiveFn]
                  ) -> Tuple[Optional[list], Optional[PackageDescription], str, str]:
    """The `measure` run: returns (payload, description, archived path, error)."""
    try:
        resp = _run(client, lp, measurement_request(lp))
    except Exception as e:  # CvmError and transport failures alike
        return None, None, "", f"measurement run failed: {e}"
    if not resp.get("SUCCESS"):
        return None, None, "", f"measurement run failed: {str(resp.get('PAYLOAD'))[:300]}"
    payload = resp["PAYLOAD"]
    ref = archive(resp, pid, "response") if archive else ""
    try:
        desc = describe_package(payload, lp.session)
    except EvidenceLayoutError as e:
        return None, None, ref, f"raw package not describable: {e}"
    if desc.bid is None:
        return None, None, ref, "raw package carries no generate_nonce event"
    return payload, desc, ref, ""


def _assurance_exception(desc: PackageDescription, config: LedgerConfig, pid: str
                         ) -> Tuple[Optional[str], str]:
    """Plan B.7: (exception reason or None, error) — error non-empty refuses."""
    if assurance_at_least(desc.assurance, config.min_assurance):
        return None, ""
    reason = config.assurance_exceptions.get(pid)
    if reason is None:
        return None, (f"assurance {desc.assurance} below minimum "
                      f"{config.min_assurance} (no exception for {pid})")
    return reason, ""


def measure(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
            archive: Optional[ArchiveFn] = None,
            tooling: Optional[ToolingRef] = None) -> LedgerMeasurement:
    """
    Measurement-only (plan N.1): the `measure` run, archived, described,
    checked against the assurance policy, and committed as ONE measurement
    bundle in one transaction. Nothing judges it here; `appraise_bundle`
    does that later, under any policy. Fails closed like `attest`.
    """
    pid = protocol.protocol_id
    out = LedgerMeasurement(protocol=pid)
    lp = ledger_protocol(protocol)
    payload, desc, out.evidence_ref, err = _measure_step(client, lp, pid, archive)
    if err:
        out.error = err
        return out
    assert payload is not None and desc is not None and desc.bid is not None
    out.bid, out.assurance = desc.bid, desc.assurance
    exception_reason, err = _assurance_exception(desc, config, pid)
    if err:
        out.error = err
        return out
    try:
        rec = build_bundle_record("measurement", lp, payload, desc,
                                  blob_ref(out.evidence_ref, remote_stores=remote_stores(config)),
                                  config, tooling=tooling, exception_reason=exception_reason, shape="measure")
        ledger.commit_bundles([rec])
        out.ledger_ref = key_for(rec)
    except DuplicateNonceError as e:
        out.error = f"duplicate nonce: {e}"
    except (LedgerError, OSError) as e:
        out.error = "" if config.fail_open else f"ledger commit failed: {e}"
    return out


def _attest_split(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                  archive: Optional[ArchiveFn], tooling: Optional[ToolingRef],
                  out: LedgerAttestation) -> LedgerAttestation:
    """Shape `split` (plan M.1): the `measure` run, then the `appraise` run
    over it, both bundles in one batch. If the appraisal half fails after a
    good measurement, the measurement bundle is committed alone with `error`
    set (plan N.4) and the outcome fails."""
    pid = protocol.protocol_id
    lp = ledger_protocol(protocol)

    # 1. measurement run -> raw signed package; assurance policy (plan B.7)
    raw_payload, raw_desc, out.evidence_ref, err = _measure_step(client, lp, pid, archive)
    if err:
        out.error = err
        return out
    assert raw_payload is not None and raw_desc is not None and raw_desc.bid is not None
    out.bid, out.assurance = raw_desc.bid, raw_desc.assurance
    exception_reason, err = _assurance_exception(raw_desc, config, pid)
    if err:
        out.error = err
        return out
    stores = remote_stores(config)
    measurement = build_bundle_record(
        "measurement", lp, raw_payload, raw_desc, blob_ref(out.evidence_ref, remote_stores=stores),
        config, tooling=tooling, exception_reason=exception_reason, shape="measure")

    def measurement_only(reason: str) -> LedgerAttestation:
        """Plan N.4: the measurement stands as evidence; the verdict fails."""
        out.error = reason
        out.passed = False
        try:
            ledger.commit_bundles([measurement.model_copy(update={"error": reason})])
            out.ledger_ref = key_for(measurement)
        except DuplicateNonceError as e:
            out.error = f"duplicate nonce: {e}"
        except (LedgerError, OSError) as e:
            if not config.fail_open:
                out.error = f"{reason}; ledger commit failed: {e}"
        return out

    # 2. appraisal run -> signed appraisal package
    try:
        resp2 = _run(client, lp, appraisal_request(lp, raw_payload))
    except Exception as e:
        return measurement_only(f"appraisal run failed: {e}")
    if not resp2.get("SUCCESS"):
        return measurement_only(f"appraisal run failed: {str(resp2.get('PAYLOAD'))[:300]}")
    appr_payload = resp2["PAYLOAD"]
    if archive:
        out.appraisal_ref = archive(resp2, pid, "appraisal")
    try:
        appr_desc = describe_package(appr_payload, lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        return measurement_only(f"appraisal package not describable: {e}")
    if appr_desc.bid is None:
        return measurement_only("appraisal package carries no appraiser nonce")
    out.appraisal_bid = appr_desc.bid

    # 3. interpretation (the CVM judged; pybb reads)
    components = interpret_appraisal(appr_payload, lp)
    if isinstance(components, str):
        return measurement_only(components)
    stamp_measured_files(components)
    out.components = components
    out.passed = overall_verdict(components)
    if archive:
        out.components_ref = archive([c.model_dump(mode="json") for c in components], pid, "components")

    # 4. the two bundles and the one-batch commit (plan K.3)
    try:
        comp_blob = blob_ref(out.components_ref, remote_stores=stores) if out.components_ref else None
        appraisal = build_bundle_record(
            "appraisal", lp, appr_payload, appr_desc, blob_ref(out.appraisal_ref, remote_stores=stores),
            config, inputs=[InputRef(bid=raw_desc.bid)],
            verdict=verdict_from(components, interpreter_used(), comp_blob),
            appraisal_kind="live", tooling=tooling, shape="appraise")
        ledger.commit_bundles([measurement, appraisal])
        out.ledger_ref = key_for(appraisal)
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


attest_with_ledger = attest  # transitional name


def write_gz_json(path: Path, obj: Any) -> None:
    """Archive helper shared with knowledge_sources: canonical for lists
    (the components artifact), plain JSON for CVM responses."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(obj) if isinstance(obj, list) else json.dumps(obj).encode("utf-8")
    with gzip.open(path, "wb") as f:
        f.write(data)




# ── fetch a bundle's bytes (plan B.5, H) ─────────────────────────────────────


class FetchedBundle(BaseModel):
    record: BundleRecord
    payload: list  # the package [RawEv, EvidenceT]
    blob_sha256: str
    location: Location


def resolve_location(loc: Location, config: Optional[LedgerConfig] = None) -> Optional[bytes]:
    """Bytes at a location, or None when it does not resolve here. `local`
    paths are tried as given and relative to the current directory; other
    stores resolve through the configured evidence repo / `gh api`."""
    if loc.store == "local":
        for cand in (Path(loc.path), Path.cwd() / loc.path):
            if cand.is_file():
                return cand.read_bytes()
        return None
    from .ledger_repo import resolve_remote_location

    return resolve_remote_location(loc, config)


def _decode_blob(blob: bytes, encoding: str) -> Any:
    data = gzip.decompress(blob) if encoding.startswith("gzip") else blob
    return json.loads(data)


def fetch_bundle(ledger: Ledger, bid: str, config: Optional[LedgerConfig] = None,
                 extra: Optional[List[Location]] = None) -> FetchedBundle:
    """Verified-read the bundle record, then its bytes via its stated
    locations in order (local first, then remote stores, then `extra`);
    refuse bytes whose hash is not the record's `blob_sha256`."""
    rec = ledger.get(bid)
    for loc in [*rec.blob.locations, *(extra or [])]:
        blob = resolve_location(loc, config)
        if blob is None:
            continue
        if sha256_hex(blob) != rec.blob.blob_sha256:
            raise LedgerError(f"location {loc.store}:{loc.path} resolves to bytes whose sha256 "
                              f"is not the ledger's blob_sha256 for {bid}")
        obj = _decode_blob(blob, rec.blob.encoding)
        payload = obj["PAYLOAD"] if isinstance(obj, dict) and "PAYLOAD" in obj else obj
        # provision bundle files are `[payload, ctx]`; the caller unwraps by role
        return FetchedBundle(record=rec, payload=payload, blob_sha256=rec.blob.blob_sha256, location=loc)
    raise LedgerError(f"no location of bundle {bid} resolves on this host")


# ── appraise any stored bundle (plan K.4; B.5 re-appraisal; B.6 audit) ───────


class LedgerAppraisal(BaseModel):
    """Report of `appraise_bundle`. Truthy iff every check holds and the
    appraisal passed (CVM verdicts over sig/nonce/binding included)."""

    bid: str  # the bundle appraised
    appraisal_bid: str = ""  # the new appraisal bundle's id
    appraisal_kind: str = "audit"
    input_role: str = ""
    ledger_verified: bool = False
    bytes_match: bool = False
    bid_ok: bool = False
    signature_ok: Optional[bool] = None  # the sig_appr verdict (CVM)
    nonce_wellformed: Optional[bool] = None  # the nonce_appr verdict (CVM)
    binding_ok: Optional[bool] = None  # appraisal-of-appraisal: goldenbytes_appr over the binding (CVM)
    passed: bool = False
    agrees_with_live: Optional[bool] = None
    components: List[ComponentResult] = []
    assurance: str = ""
    freshness: str = "post-hoc"
    location_used: Optional[Location] = None
    appraisal_ref: str = ""
    ledger_ref: str = ""
    error: str = ""

    def __bool__(self) -> bool:
        return (self.error == "" and self.ledger_verified and self.bytes_match and self.bid_ok
                and self.passed and self.signature_ok is not False and self.nonce_wellformed is not False
                and self.binding_ok is not False)


def _verdict_of(components: List[ComponentResult], appr_asp: str) -> Optional[bool]:
    hits = [c.passed for c in components if c.appr_asp == appr_asp]
    return None if not hits else all(hits)


def needs_keep(ledger: Ledger, bundle: BundleRecord, _depth: int = 0) -> bool:
    """Whether a stored package lays out under the EXTEND `hashevidence`
    typing: `combined` packages do, and so does any `appraise` package whose
    input did (its run shared that session; plan M.2 caveat). A lifted P
    (`measurement`, shape combined) carries no hashevidence and reads under
    either typing."""
    if bundle.role == "measurement":
        return False
    if bundle.shape == "combined":
        return True
    if bundle.shape == "appraise" and _depth < 8:
        for i in bundle.inputs or []:
            try:
                if needs_keep(ledger, ledger.get(i.bid), _depth + 1):
                    return True
            except LedgerError:
                continue
    return False


def live_appraisal_of(ledger: Ledger, bid: str) -> Optional[BundleRecord]:
    for a in ledger.appraisals_of(bid):
        if a.appraisal_kind == "live":
            return a
    return None


def appraise_bundle(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig, bid: str,
                    session_override: Optional[dict] = None, appraisal_kind: Optional[str] = None,
                    archive: Optional[ArchiveFn] = None,
                    tooling: Optional[ToolingRef] = None) -> LedgerAppraisal:
    """
    Plan K.4: fetch bundle `bid` by its stated locations, check it
    structurally (bytes and id against the record), run the signed B.6
    appraisal term over it under `protocol`'s session (or `session_override`
    — a different policy), interpret, and commit one appraisal bundle with
    `inputs=[bid]` plus its `judged_by` pointer. `appraisal_kind` defaults
    to `audit`, or `deferred` for the first appraisal of a measurement that
    has no live appraisal (plan N.3).

    A measurement (or provision) bundle is judged by the protocol's
    companions through the verified summarizer, and `agrees_with_live`
    compares with its live appraisal under the same session. An appraisal
    bundle is judged inside the CVM (plan B.6): `sig_appr`, `nonce_appr`,
    and `goldenbytes_appr` over its binding against the judged bundle's
    `rawev_sha256`, with `magic_appr` passing its verdict slots through.
    """
    rep = LedgerAppraisal(bid=bid, appraisal_kind=appraisal_kind or "audit")
    try:
        fetched = fetch_bundle(ledger, bid, config)
    except LedgerError as e:
        rep.error = f"fetch failed: {e}"
        return rep
    target = fetched.record
    if appraisal_kind is None and target.role == "measurement" and not ledger.appraisals_of(bid):
        rep.appraisal_kind = "deferred"  # plan N.3: the first appraisal of a measurement nobody has judged
    keep = needs_keep(ledger, target)  # combined packages lay out under EXTEND hashevidence
    lp = shaped_protocol(protocol, "combined" if keep else "split")
    rep.ledger_verified = True  # ledger.get() succeeded through verified reads
    rep.bytes_match = True  # fetch_bundle refuses mismatching bytes
    rep.location_used = fetched.location
    rep.freshness = target.freshness
    rep.input_role = target.role
    if target.protocol_id != protocol.protocol_id:
        rep.error = f"bundle {bid} is of protocol {target.protocol_id}, not {protocol.protocol_id}"
        return rep
    payload = fetched.payload
    if target.role == "provision" and not (isinstance(payload[0], dict) and "RawEv" in payload[0]):
        payload = payload[0]  # provision bundle files are [payload, ctx]
    if target.role == "appraisal":
        return _appraise_appraisal_bundle(client, lp, protocol, ledger, config, target, payload, rep,
                                          archive, tooling)

    nonce_targid = NONCE_TARGID
    try:
        desc = describe_package(payload, lp.session, nonce_targid=nonce_targid)
    except EvidenceLayoutError as e:
        rep.error = f"fetched package not describable: {e}"
        return rep
    rep.bid_ok = (desc.bid == target.bid and desc.rawev_sha256 == target.rawev_sha256) \
        if target.bid else (desc.rawev_sha256 == target.rawev_sha256)
    if not rep.bid_ok:
        rep.error = "fetched package does not reproduce the recorded bundle id / rawev hash"
        return rep

    ap = lp if session_override is None else lp.model_copy(update={"session": ledger_session(session_override)})
    try:
        resp = _run(client, ap, appraisal_request(ap, payload))
    except Exception as e:
        rep.error = f"appraisal run failed: {e}"
        return rep
    if not resp.get("SUCCESS"):
        rep.error = f"appraisal run failed: {str(resp.get('PAYLOAD'))[:300]}"
        return rep
    appr_payload = resp["PAYLOAD"]
    if archive:
        rep.appraisal_ref = archive(resp, protocol.protocol_id, f"appraisal-{rep.appraisal_kind}")
    try:
        appr_desc = describe_package(appr_payload, ap.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        rep.error = f"appraisal package not describable: {e}"
        return rep
    if appr_desc.bid is None:
        rep.error = "appraisal package carries no appraiser nonce"
        return rep
    rep.appraisal_bid = appr_desc.bid
    rep.assurance = appr_desc.assurance
    components = interpret_appraisal(appr_payload, ap)
    if isinstance(components, str):
        rep.error = components
        return rep
    rep.components = components
    rep.passed = overall_verdict(components)
    rep.signature_ok = _verdict_of(components, "sig_appr")
    rep.nonce_wellformed = _verdict_of(components, "nonce_appr")
    live = live_appraisal_of(ledger, bid)
    if live is not None and live.verdict is not None and session_override is None:
        rep.agrees_with_live = (rep.passed == live.verdict.passed)

    _commit_appraisal(ledger, ap, target, appr_payload, appr_desc, components, rep, config,
                      interpreter_used(), tooling)
    return rep


def _commit_appraisal(ledger: Ledger, ap: Any, target: BundleRecord, appr_payload: list,
                      appr_desc: PackageDescription, components: List[ComponentResult],
                      rep: LedgerAppraisal, config: LedgerConfig, interpreter: Interpreter,
                      tooling: Optional[ToolingRef]) -> None:
    try:
        stores = remote_stores(config)
        verdict = verdict_from(components, interpreter,
                               checks={"ledger_verified": rep.ledger_verified, "bytes_match": rep.bytes_match,
                                       "bid_ok": rep.bid_ok},
                               agrees_with_live=rep.agrees_with_live)
        rec = build_bundle_record("appraisal", ap, appr_payload, appr_desc,
                                  blob_ref(rep.appraisal_ref, remote_stores=stores), config,
                                  protocol_id=target.protocol_id, inputs=[InputRef(bid=target.key_id)],
                                  verdict=verdict, appraisal_kind=rep.appraisal_kind, tooling=tooling,
                                  shape="appraise")
        ledger.commit_bundles([rec])
        rep.ledger_ref = key_for(rec)
    except (LedgerError, OSError) as e:
        rep.error = f"appraisal bundle not committed: {e}"


# ── CVM-native appraisal of an APPRAISAL bundle (plan B.6, 'audit of the audit') ─


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
    (each companion span's first slot is its verdict). Used where the
    verified summarizer refuses the shape (audits of appraisal packages)."""
    from .appraisal import _decode_verdict
    from .ledger import _appraised_node

    raw = branch_payload[0]["RawEv"]
    spans = slot_layout(branch_payload[1], session)
    # companion -> the ASP_ID of the event it judged, by walking the type tree
    judged: Dict[int, str] = {}

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
            if params.get("ASP_ID", "") in {s.asp for s in spans if s.companion}:
                node = _appraised_node(sub)
                judged[id(params)] = node["EvidenceT_BODY"][1].get("ASP_ID", "unknown") if node else "unknown"
            else:
                walk(sub)

    walk(branch_payload[1])
    targets = list(judged.values())
    comps: List[ComponentResult] = []
    k = 0
    for sp in spans:
        if not sp.companion:
            continue
        passed, reason = _decode_verdict(raw[sp.start] if sp.start < len(raw) else "")
        target = targets[k] if k < len(targets) else "unknown"
        k += 1
        comps.append(ComponentResult(appr_asp=sp.asp, target_asp=target, targ_id=sp.asp_targid,
                                     passed=passed, reason=reason, args=sp.args, description=target))
    return comps


def _appraise_appraisal_bundle(client: Any, lp: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                               target: BundleRecord, appr_payload: list, rep: LedgerAppraisal,
                               archive: Optional[ArchiveFn], tooling: Optional[ToolingRef]) -> LedgerAppraisal:
    """Plan B.6: judge a recorded appraisal package inside the CVM — its
    signature (`sig_appr`), its appraiser nonce (`nonce_appr`) and its binding
    to the bundle it judged (`goldenbytes_appr` against that bundle's
    `rawev_sha256`) — with the same signed B.6 term, so the result is itself
    a signed, nonce-bound appraisal bundle with `inputs=[the appraisal]`."""
    try:
        d = describe_package(appr_payload, lp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        rep.error = f"appraisal package not describable: {e}"
        return rep
    rep.bid_ok = (d.bid == target.bid and d.rawev_sha256 == target.rawev_sha256)
    if not rep.bid_ok:
        rep.error = "appraisal package does not reproduce the recorded bundle id / rawev hash"
        return rep
    if not target.inputs:
        rep.error = "appraisal bundle names no input to check its binding against"
        return rep
    try:
        judged = ledger.get(target.inputs[0].bid)
    except LedgerError as e:
        rep.error = f"judged bundle not in the ledger: {e}"
        return rep

    appraiser_asps = sorted({s.asp for s in d.spans if s.asp.endswith("_appr")})
    session = audit_session(protocol.session, appraiser_asps)
    if needs_keep(ledger, target):  # the audit run's own hashevidence retains too (M.2 caveat)
        session["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
    golden_b64 = base64.b64encode(bytes.fromhex(judged.rawev_sha256)).decode()
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
        rep.appraisal_ref = archive(resp, protocol.protocol_id, f"appraisal-{rep.appraisal_kind}-of-appraisal")
    try:
        ad = describe_package(audit_payload, session, nonce_targid=APPRAISER_NONCE_TARGID)
        branch = appraisal_branch(audit_payload, session)
    except EvidenceLayoutError as e:
        rep.error = f"audit package not describable: {e}"
        return rep
    if ad.bid is None:
        rep.error = "audit package carries no appraiser nonce"
        return rep
    rep.appraisal_bid = ad.bid
    rep.assurance = ad.assurance
    components = components_from_layout(branch["PAYLOAD"], session)
    rep.components = components
    rep.signature_ok = _verdict_of(components, "sig_appr")
    rep.nonce_wellformed = _verdict_of(components, "nonce_appr")
    rep.binding_ok = _verdict_of(components, "goldenbytes_appr")
    rep.passed = overall_verdict(components)
    rep.agrees_with_live = None  # this judges the appraisal package, not the targets
    interp = Interpreter(kind="legacy-walker", tool="pybb.attestation.ledger_runs.components_from_layout")
    _commit_appraisal(ledger, ap, target, audit_payload, ad, components, rep, config, interp, tooling)
    return rep
