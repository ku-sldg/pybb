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
    StackInfo,
    ConfigFile,
    ConfigInfo,
    ContextClaim,
    GoldenProvenance,
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
    # the claim lane (plan P.2) hashes five files in every run term
    "hashfile": {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"}, "ATTRS": []},
    "goldenbytes_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
}
LEDGER_ASP_COMPS: Dict[str, str] = {NONCE_ASP: "nonce_appr", "hashevidence": "goldenbytes_appr",
                                    "hashfile": "goldenbytes_appr"}

# the measured claim lane (plan P.2): the run's own inputs, the CVM invocation
# and the writer's claim, hashed by the CVM as the left-most branch of the term
LANE = (("term", "term.json"), ("session", "session.json"), ("manifest", "manifest.json"),
        ("invocation", "cvm_config.json"), ("claim", "claim.json"))
LANE_PREFIX = "claim:"


def lane_targ(name: str) -> str:
    return f"{LANE_PREFIX}{name}"


def hashfile_targets(files: Dict[str, Any], metadata: str) -> Dict[str, dict]:
    """`hashfile` targets for files by logical id (plan O.1): the path lives in
    the args, never in the id."""
    return {targ: {"filepath": str(path), "env_var": "", "measure_in_place": True,
                   "metadata": metadata, "asp_targid": targ}
            for targ, path in files.items()}


def lane_files(config: LedgerConfig, protocol_id: str, constructor: str) -> Dict[str, Path]:
    """Target id -> path of a run's lane files, stable per protocol and
    constructor (so the term's args do not churn and a config bundle can
    measure the term that names them)."""
    root = Path(os.path.expanduser(config.state_dir)) / config.context.dir / "runs" / protocol_id / constructor
    return {lane_targ(name): root / fname for name, fname in LANE}


def lane_term(files: Dict[str, Path]) -> dict:
    """The lane's `hashfile` chain with its args injected, in LANE order."""
    targets = hashfile_targets(files, "claim::lane")
    from .tools import _hashfile_chain

    return normalize_term(inject_asp_args(_hashfile_chain(targets), {"hashfile": targets}))


def is_lane_span(sp: Any) -> bool:
    return sp.asp == "hashfile" and (sp.asp_targid or "").startswith(LANE_PREFIX)
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


def _with_lane(lane: Optional[dict], body: dict) -> dict:
    """`bseq right_path LANE body` (plan P.2): the lane gets empty evidence,
    `body` the incoming evidence, so an appraisal's lane never retains a copy
    of the package it appraises."""
    return _bseq("right_path", lane, body) if lane is not None else body


def measurement_term(protocol: Any, lane: Optional[dict] = None) -> dict:
    """
    `lseq (bseq left_path (asp generate_nonce) (bseq right_path LANE M)) SIG`
    (plan B.1, lane per P.2; without a lane the inner split is just `M`).

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
        return _lseq(_bseq("left_path", nonce, _with_lane(lane, stripped["TERM_BODY"][0])), _SIG)
    return _bseq("left_path", nonce, _with_lane(lane, stripped))


def appraisal_term(lane: Optional[dict] = None) -> dict:
    """`lseq (bseq right_path LANE (bseq both_paths (asp hashevidence) APPR)) (lseq (asp generate_nonce) SIG)`
    (plan B.6, lane per P.2)."""
    return _lseq(_with_lane(lane, _bseq("both_paths", _asp("hashevidence", {}), _APPR)),
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


def combined_term(protocol: Any, lane: Optional[dict] = None) -> dict:
    """
    One run, both artifacts (plan M.2; lane per P.2 as `bseq right_path LANE`
    around the inner split):

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
    return _lseq(stripped, _lseq(_with_lane(lane, _bseq("both_paths", sign_lane, _APPR)),
                                 _lseq(_asp(NONCE_ASP, dict(APPRAISER_NONCE_ARGS)), _SIG)))


def combined_request(protocol: Any, lane: Optional[dict] = None) -> dict:
    """The one request of a `combined` run; `protocol` must carry `combined_session`."""
    return _request(protocol, combined_term(protocol, lane), empty_evidence())


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


def measurement_request(protocol: Any, lane: Optional[dict] = None) -> dict:
    """Run-1 request; `protocol` must already be `ledger_protocol(...)`."""
    return _request(protocol, measurement_term(protocol, lane), empty_evidence())


def appraisal_request(protocol: Any, raw_payload: list, lane: Optional[dict] = None) -> dict:
    """Run-2 request over the raw package; `protocol` must be `ledger_protocol(...)`."""
    return _request(protocol, appraisal_term(lane), raw_payload)


# ── the writer's cache and claim (plan P.3) ──────────────────────────────────


def context_root(config: LedgerConfig) -> Path:
    return Path(os.path.expanduser(config.state_dir)) / config.context.dir


def cache_path(config: LedgerConfig) -> Path:
    return context_root(config) / "claim.json"


def load_cache(config: LedgerConfig) -> dict:
    p = cache_path(config)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def build_claim(config: LedgerConfig, protocol_id: str, fresh: str = "none") -> Optional[dict]:
    """The claim a run makes (plan P.3), as the dict written to the lane's
    `claim.json`: the cache restricted to this protocol, plus what this run
    re-measured and the policy in force. None when the writer has measured
    nothing yet (the run then makes no claim)."""
    cache = load_cache(config)
    stack = cache.get("stack") or {}
    cfg = (cache.get("configs") or {}).get(protocol_id) or {}
    if not stack and not cfg:
        return None
    return {"writer": cache.get("writer", ""), "protocol_id": protocol_id,
            "stack": {"bid": stack.get("bid", ""), "fingerprint": stack.get("fingerprint", ""),
                      "measured_at": stack.get("measured_at", "")},
            "config": {"bid": cfg.get("bid", ""), "fingerprint": cfg.get("fingerprint", ""),
                       "measured_at": cfg.get("measured_at", "")},
            "fresh": fresh, "policy": config.context.refresh}


def _blob_copy(root: Path, data: bytes, ext: str = ".json") -> Path:
    blob = root / "blobs" / f"{sha256_hex(data)}{ext}"
    blob.parent.mkdir(parents=True, exist_ok=True)
    if not blob.exists():
        blob.write_bytes(data)
    return blob


def _cvm_config_dump(cvm_config: Any) -> dict:
    if cvm_config is None:
        return {}
    return cvm_config.model_dump(mode="json") if hasattr(cvm_config, "model_dump") else dict(vars(cvm_config))


def prepare_run(config: LedgerConfig, client: Any, lp: Any, protocol_id: str, constructor: str,
                make_request: Callable[[dict], dict], fresh: str = "none"
                ) -> Tuple[dict, Dict[str, Path], Optional[dict]]:
    """Write a run's lane files (plan P.2) and build its request with the
    lane: `cvm_config.json` and `claim.json` first (independent of the
    term), then the request, then `term.json`/`session.json`/`manifest.json`
    as the canonical bytes of exactly what the CVM is handed — the term file
    is a fixed point, it names itself as a target. Returns (request, lane
    files, claim dict or None)."""
    files = lane_files(config, protocol_id, constructor)
    next(iter(files.values())).parent.mkdir(parents=True, exist_ok=True)
    claim = build_claim(config, protocol_id, fresh)
    files[lane_targ("invocation")].write_bytes(canonical_json(_cvm_config_dump(getattr(client, "config", None))))
    files[lane_targ("claim")].write_bytes(canonical_json(claim if claim is not None else {}))
    req = make_request(lane_term(files))
    files[lane_targ("term")].write_bytes(canonical_json(req["TERM"]))
    files[lane_targ("session")].write_bytes(canonical_json(req["ATTESTATION_SESSION"]))
    files[lane_targ("manifest")].write_bytes(canonical_json(lp.manifest))
    return req, files, claim


def lane_goldens(files: Dict[str, Path]) -> Dict[str, str]:
    """Expectations for the lane's five `hashfile` events: the digests of the
    files pybb wrote (base64 of the raw sha256, what `hashfile` outputs). pybb
    supplies the expectation that the files the CVM measured are the files
    it archives; the CVM compares (plan B.9 rule 2, P.5)."""
    return {targ: base64.b64encode(hashlib.sha256(p.read_bytes()).digest()).decode()
            for targ, p in files.items() if p.is_file()}


def claim_record(claim: Optional[dict], files: Dict[str, Path], config: LedgerConfig) -> Optional[ContextClaim]:
    """The `claim` member of a run bundle (plan P.3) from the lane's claim
    dict and files, the files archived as content-addressed blobs. A run
    whose writer has measured nothing yet still measured its lane: its claim
    names no stack or config (empty bids) but keeps the files, so later
    appraisals can judge the lane."""
    root = context_root(config)
    stores = remote_stores(config)
    archived: List[ConfigFile] = []
    for targ, p in files.items():
        if p.is_file():
            data = p.read_bytes()
            archived.append(ConfigFile(targ_id=targ, blob=blob_ref(str(_blob_copy(root, data)), data,
                                                                   encoding="json", remote_stores=stores)))
    if claim is None:
        return ContextClaim(policy=config.context.refresh, files=archived) if archived else None
    return ContextClaim(stack_bid=claim["stack"]["bid"], stack_fingerprint=claim["stack"]["fingerprint"],
                        stack_measured_at=claim["stack"]["measured_at"], config_bid=claim["config"]["bid"],
                        config_fingerprint=claim["config"]["fingerprint"],
                        config_measured_at=claim["config"]["measured_at"], fresh=claim["fresh"],
                        policy=claim["policy"], files=archived)


def has_lane(payload: list, session: dict) -> bool:
    try:
        return any(is_lane_span(s) and not s.companion and not s.input for s in slot_layout(payload[1], session))
    except EvidenceLayoutError:
        return False


def stored_lane_goldens(ledger: Ledger, target: BundleRecord) -> Tuple[Dict[str, str], List[GoldenProvenance]]:
    """Goldens for the lane inside a STORED package (plan P.5): term, session
    and manifest from the config bundle the claim names (the CVM-measured
    configuration — that comparison is the run→config link), the invocation
    and the claim file from the run's own archived lane files; everything
    from the run's files when no config bundle is named or matches."""
    if target.claim is None:
        return {}, []
    own = {f.targ_id: base64.b64encode(bytes.fromhex(f.blob.blob_sha256)).decode()
           for f in target.claim.files if f.blob.blob_sha256}
    goldens = dict(own)
    prov = [GoldenProvenance(source="bundle", ref=f"bundle/{target.key_id}", targets=sorted(own))]
    cbid = target.claim.config_bid
    if cbid:
        try:
            cfg = ledger.get(cbid)
        except LedgerError:
            cfg = None
        if cfg is not None and cfg.config is not None:
            files = {f.targ_id: f.blob.blob_sha256 for f in cfg.config.files}
            mine = {"term": target.term_sha256, "session": target.session_sha256, "manifest": target.manifest_sha256}
            for c in sorted({t.split(":")[1] for t in files}):
                if all(files.get(f"input:{c}:{n}") == mine[n] for n in mine):
                    from_cfg = {lane_targ(n): base64.b64encode(bytes.fromhex(files[f"input:{c}:{n}"])).decode()
                                for n in mine}
                    goldens.update(from_cfg)
                    prov = [GoldenProvenance(source="bundle", ref=f"bundle/{cfg.key_id}", targets=sorted(from_cfg)),
                            GoldenProvenance(source="bundle", ref=f"bundle/{target.key_id}",
                                             targets=sorted(set(own) - set(from_cfg)))]
                    break
    return goldens, [g for g in prov if g.targets]


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
    if _is_lane_type(left):  # the claim lane is the left-most branch (plan P.2): step over it
        node = right
        if not (isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "split_evt"):
            raise EvidenceLayoutError("appraisal package: no split beneath the claim lane")
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


def _is_lane_type(et: Any) -> bool:
    """An evidence type made only of `hashfile` events over `claim:*` targets."""
    ids: List[bool] = []

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        c, b = n.get("EvidenceT_CONSTRUCTOR"), n.get("EvidenceT_BODY")
        if c == "asp_evt":
            params = b[1]
            ids.append(params.get("ASP_ID") == "hashfile"
                       and str((params.get("ASP_ARGS") or {}).get("asp_targid", "")).startswith(LANE_PREFIX))
            walk(b[2])
        elif c == "split_evt":
            walk(b[0]); walk(b[1])
        elif c in ("left_evt", "right_evt"):
            walk(b if isinstance(b, dict) else b[0])

    walk(et)
    return bool(ids) and all(ids)


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
                        golden_provenance: Optional[List[GoldenProvenance]] = None,
                        provision: Optional[ProvisionInfo] = None,
                        exception_reason: Optional[str] = None,
                        error: str = "", shape: Optional[str] = None,
                        request: Optional[dict] = None,
                        stack: Optional[StackInfo] = None,
                        config_info: Optional[ConfigInfo] = None,
                        claim: Optional[ContextClaim] = None) -> BundleRecord:
    """The one bundle builder (plan K.1): the package as `describe_package`
    read it, the inputs it ran under, where its bytes are, and the
    role-gated members the caller supplies. The role is asserted against
    the package: an appraisal package carries a `hashevidence` binding and
    an appraiser nonce, the others do not.

    Pins (plan O.3): with `request` — the exact request the CVM ran —
    `term_sha256` and `session_sha256` hash the canonical TERM and
    ATTESTATION_SESSION of that request, which is what a `config` bundle's
    `input:*` targets measure; without it they hash the protocol's own
    term and session (provisioning bundles)."""
    hs = desc.span_for("hashevidence")
    if role == "appraisal":
        if hs is None:
            raise LedgerError("appraisal bundle: package has no hashevidence binding")
        if not inputs or verdict is None:
            raise LedgerError("appraisal bundle: inputs and verdict are required")
        raw_b64 = payload[0]["RawEv"]
        bound = base64.b64decode(raw_b64[hs.start]).hex()
        inputs = [i.model_copy(update={"binding_hash": bound}) for i in inputs]
    elif hs is not None and role not in ("challenge", "stack", "config"):  # context packages carry a fingerprint
        raise LedgerError(f"{role} bundle: package carries a hashevidence binding (is it an appraisal?)")
    if (stack is not None) != (role == "stack") or (config_info is not None) != (role == "config"):
        raise LedgerError(f"{role} bundle: stack/config info must match the role")
    env = record_env(config)
    nonce: Optional[NonceInfo] = None
    if desc.nonce is not None and desc.nonce_b64 is not None:
        nonce = NonceInfo(asp=desc.nonce.asp, b64=desc.nonce_b64,
                          bytes=len(base64.b64decode(desc.nonce_b64)))
    sig = desc.signature.model_copy(update={"signer_fp": env["committer_fp"] or None}) \
        if desc.signature.present else SignatureInfo(present=False)
    term = request["TERM"] if request is not None else lp.term
    session = request["ATTESTATION_SESSION"] if request is not None else lp.session
    return BundleRecord(
        bid=desc.bid, role=role, protocol_id=protocol_id or lp.protocol_id,
        term_sha256=sha256_hex(canonical_json(term)),
        session_sha256=sha256_hex(canonical_json(session)),
        manifest_sha256=sha256_hex(canonical_json(lp.manifest)),
        response_sha256=desc.response_sha256, blob=blob, rawev_count=desc.rawev_count,
        rawev_sha256=desc.rawev_sha256, nonce=nonce, signature=sig, assurance=desc.assurance,
        freshness="post-hoc" if nonce else "none", exception_reason=exception_reason,
        error=error, shape=shape, inputs=inputs, verdict=verdict,
        golden_provenance=golden_provenance, provision=provision,
        stack=stack, config=config_info, claim=claim, **env)


def verdict_from(components: List[ComponentResult], interpreter: Interpreter,
                 components_blob: Optional[BlobRef] = None) -> Verdict:
    failing = [FailingComponent(targ_id=c.targ_id, appr_asp=c.appr_asp, reason=c.reason)
               for c in components if not c.passed]
    return Verdict(passed=overall_verdict(components), components_total=len(components),
                   components_failed=len(failing), failing=failing,
                   components_sha256=sha256_hex(_components_json(components)),
                   components_blob=components_blob, interpreter=interpreter)


def remote_stores(config: LedgerConfig) -> List[str]:
    """Store ids of the configured evidence repo(s), for stated locations."""
    from .ledger_repo import configured_repo

    repo = configured_repo(config)
    return [repo.store_id()] if repo is not None else []


# ── the two-run flow: `attest` (plan K.3, live run) ─────────────────────────


def attest(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
           archive: Optional[ArchiveFn] = None,
           shape: Optional[str] = None, fresh: str = "none") -> LedgerAttestation:
    """
    One live attestation of `protocol` under the configured bundle shape
    (plan M): `split` — a measurement run and an appraisal run over it — or
    `combined` — one run yielding the same two artifacts. Either way the
    result is a measurement bundle, its live appraisal bundle with
    `inputs=[measurement]`, and the `judged_by`
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
        return _attest_combined(client, protocol, ledger, config, archive, out, fresh)
    return _attest_split(client, protocol, ledger, config, archive, out, fresh)


def _attest_combined(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                     archive: Optional[ArchiveFn], out: LedgerAttestation, fresh: str = "none") -> LedgerAttestation:
    """Shape `combined` (plan M.2): one run; P lifted from the hash lane."""
    pid = protocol.protocol_id
    lp = shaped_protocol(protocol, "combined")

    # 1. the one run, with the claim lane (plan P.2); APPR judges M only, so no lane goldens are needed live
    req, lane, claim = prepare_run(config, client, lp, pid, "combined", lambda l: combined_request(lp, l), fresh)
    try:
        resp = _run(client, lp, req)
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
        crec = claim_record(claim, lane, config)
        measurement = build_bundle_record("measurement", lp, p_payload, raw_desc, p_blob, config,
                                          exception_reason=exception_reason, shape="combined", request=req,
                                          claim=crec)
        comp_blob = blob_ref(out.components_ref, remote_stores=stores) if out.components_ref else None
        appraisal = build_bundle_record(
            "appraisal", lp, payload, appr_desc, blob_ref(out.appraisal_ref, remote_stores=stores),
            config, inputs=[InputRef(bid=raw_desc.bid)],
            verdict=verdict_from(components, interpreter_used(), comp_blob),
            golden_provenance=[GoldenProvenance(source="protocol")], shape="combined", request=req, claim=crec)
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


def _measure_step(client: Any, lp: Any, pid: str, archive: Optional[ArchiveFn], request: Optional[dict] = None
                  ) -> Tuple[Optional[list], Optional[PackageDescription], str, str, dict]:
    """The `measure` run: returns (payload, description, archived path, error,
    the request that ran). `request` defaults to `measurement_request(lp)`."""
    req = request if request is not None else measurement_request(lp)
    try:
        resp = _run(client, lp, req)
    except Exception as e:  # CvmError and transport failures alike
        return None, None, "", f"measurement run failed: {e}", req
    if not resp.get("SUCCESS"):
        return None, None, "", f"measurement run failed: {str(resp.get('PAYLOAD'))[:300]}", req
    payload = resp["PAYLOAD"]
    ref = archive(resp, pid, "response") if archive else ""
    try:
        desc = describe_package(payload, lp.session)
    except EvidenceLayoutError as e:
        return None, None, ref, f"raw package not describable: {e}", req
    if desc.bid is None:
        return None, None, ref, "raw package carries no generate_nonce event", req
    return payload, desc, ref, "", req


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
            archive: Optional[ArchiveFn] = None, fresh: str = "none") -> LedgerMeasurement:
    """
    Measurement-only (plan N.1): the `measure` run, archived, described,
    checked against the assurance policy, and committed as ONE measurement
    bundle in one transaction. Nothing judges it here; `appraise_bundle`
    does that later, under any policy. Fails closed like `attest`.
    """
    pid = protocol.protocol_id
    out = LedgerMeasurement(protocol=pid)
    lp = ledger_protocol(protocol)
    req, lane, claim = prepare_run(config, client, lp, pid, "measure", lambda l: measurement_request(lp, l), fresh)
    payload, desc, out.evidence_ref, err, req = _measure_step(client, lp, pid, archive, request=req)
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
                                  config, exception_reason=exception_reason, shape="measure", request=req,
                                  claim=claim_record(claim, lane, config))
        ledger.commit_bundles([rec])
        out.ledger_ref = key_for(rec)
    except DuplicateNonceError as e:
        out.error = f"duplicate nonce: {e}"
    except (LedgerError, OSError) as e:
        out.error = "" if config.fail_open else f"ledger commit failed: {e}"
    return out


def _attest_split(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                  archive: Optional[ArchiveFn], out: LedgerAttestation, fresh: str = "none") -> LedgerAttestation:
    """Shape `split` (plan M.1): the `measure` run, then the `appraise` run
    over it, both bundles in one batch. If the appraisal half fails after a
    good measurement, the measurement bundle is committed alone with `error`
    set (plan N.4) and the outcome fails."""
    pid = protocol.protocol_id
    lp = ledger_protocol(protocol)

    # 1. measurement run -> raw signed package; assurance policy (plan B.7)
    req1, lane1, claim1 = prepare_run(config, client, lp, pid, "measure", lambda l: measurement_request(lp, l), fresh)
    raw_payload, raw_desc, out.evidence_ref, err, req1 = _measure_step(client, lp, pid, archive, request=req1)
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
        config, exception_reason=exception_reason, shape="measure", request=req1,
        claim=claim_record(claim1, lane1, config))

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

    # 2. appraisal run -> signed appraisal package. The raw package's lane events are judged
    # too (plan P.5): pybb supplies the digests of the lane files it wrote, the CVM compares.
    lane1_goldens = lane_goldens(lane1) if has_lane(raw_payload, lp.session) else {}
    evidence = [raw_payload[0], inject_goldens(raw_payload[1], lane1_goldens, only_known=True)] if lane1_goldens else raw_payload
    req2, lane2, claim2 = prepare_run(config, client, lp, pid, "appraise",
                                      lambda l: appraisal_request(lp, evidence, l), fresh)
    try:
        resp2 = _run(client, lp, req2)
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
            golden_provenance=[GoldenProvenance(source="protocol")] + ([GoldenProvenance(
                source="bundle", ref=f"bundle/{raw_desc.bid}", targets=sorted(lane1_goldens))] if lane1_goldens else []),
            shape="appraise", request=req2, claim=claim_record(claim2, lane2, config))
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
    input_role: str = ""
    golden_provenance: List[GoldenProvenance] = []  # where the injected goldens came from (plan P.11)
    ledger_verified: bool = False
    bytes_match: bool = False
    bid_ok: bool = False
    signature_ok: Optional[bool] = None  # the sig_appr verdict (CVM)
    nonce_wellformed: Optional[bool] = None  # the nonce_appr verdict (CVM)
    binding_ok: Optional[bool] = None  # appraisal-of-appraisal: goldenbytes_appr over the binding (CVM)
    passed: bool = False
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
    if bundle.role in ("stack", "config"):  # the fingerprint hashevidence is EXTEND (plan P.1)
        return True
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


def appraise_bundle(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig, bid: str,
                    session_override: Optional[dict] = None,
                    archive: Optional[ArchiveFn] = None,
                    against: Optional[str] = None, fresh: str = "none") -> LedgerAppraisal:
    """
    Plan K.4: fetch bundle `bid` by its stated locations, check it
    structurally (bytes and id against the record), run the signed B.6
    appraisal term over it under `protocol`'s session (or `session_override`
    — a different policy), interpret, and commit one appraisal bundle with
    `inputs=[bid]` plus its `judged_by` pointer. There are no kinds of
    appraisal (plan P.11): live, first-later and audit are positions in the
    chain `judged_by/<bid>/…`, and `golden_provenance` says where the
    goldens the CVM compared against came from.

    A measurement (or provision) bundle is judged by the protocol's
    companions through the verified summarizer. An appraisal
    bundle is judged inside the CVM (plan B.6): `sig_appr`, `nonce_appr`,
    and `goldenbytes_appr` over its binding against the judged bundle's
    `rawev_sha256`, with `magic_appr` passing its verdict slots through.

    A `stack` or `config` bundle (plan O.6) is judged under the generated
    context protocol, `protocol` unused: stack targets against the goldens
    of a blessing (`against`: a `blessing/<bid>` key; default the latest),
    config targets against the hashes of the files the bundle archived.
    """
    rep = LedgerAppraisal(bid=bid)
    try:
        fetched = fetch_bundle(ledger, bid, config)
    except LedgerError as e:
        rep.error = f"fetch failed: {e}"
        return rep
    target = fetched.record
    if target.role in ("stack", "config"):
        rep.ledger_verified = rep.bytes_match = True
        rep.location_used, rep.freshness, rep.input_role = fetched.location, target.freshness, target.role
        return _appraise_context_bundle(client, ledger, config, target, fetched.payload, rep, archive, against)
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
        return _appraise_appraisal_bundle(client, lp, protocol, ledger, config, target, payload, rep, archive, fresh)

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
    # the stored package's lane (if any) is judged against the files it archived / the config bundle (plan P.5)
    lane_g, lane_prov = stored_lane_goldens(ledger, target) if has_lane(payload, ap.session) else ({}, [])
    evidence = [payload[0], inject_goldens(payload[1], lane_g, only_known=True)] if lane_g else payload
    req, lane, claim = prepare_run(config, client, ap, protocol.protocol_id,
                                   "appraise_combined" if keep else "appraise",
                                   lambda l: appraisal_request(ap, evidence, l), fresh)
    try:
        resp = _run(client, ap, req)
    except Exception as e:
        rep.error = f"appraisal run failed: {e}"
        return rep
    if not resp.get("SUCCESS"):
        rep.error = f"appraisal run failed: {str(resp.get('PAYLOAD'))[:300]}"
        return rep
    appr_payload = resp["PAYLOAD"]
    if archive:
        rep.appraisal_ref = archive(resp, protocol.protocol_id, "reappraisal")
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
    rep.golden_provenance = [GoldenProvenance(source="protocol"), *lane_prov]  # goldens provisioned into the term
    _commit_appraisal(ledger, ap, target, appr_payload, appr_desc, components, rep, config,
                      interpreter_used(), req, claim_record(claim, lane, config))
    return rep


def _commit_appraisal(ledger: Ledger, ap: Any, target: BundleRecord, appr_payload: list,
                      appr_desc: PackageDescription, components: List[ComponentResult],
                      rep: LedgerAppraisal, config: LedgerConfig, interpreter: Interpreter,
                      request: dict, claim: Optional[ContextClaim] = None) -> None:
    try:
        stores = remote_stores(config)
        verdict = verdict_from(components, interpreter)
        rec = build_bundle_record("appraisal", ap, appr_payload, appr_desc,
                                  blob_ref(rep.appraisal_ref, remote_stores=stores), config,
                                  protocol_id=target.protocol_id, inputs=[InputRef(bid=target.key_id)],
                                  verdict=verdict, golden_provenance=rep.golden_provenance,
                                  shape="appraise", request=request, claim=claim)
        ledger.commit_bundles([rec])
        rep.ledger_ref = key_for(rec)
    except (LedgerError, OSError) as e:
        rep.error = f"appraisal bundle not committed: {e}"


# ── CVM-native appraisal of an APPRAISAL bundle (plan B.6, 'audit of the audit') ─


PASSTHROUGH_APPR = "magic_appr"


def audit_appraisers(session: dict) -> List[str]:
    """Every appraiser ASP a protocol's packages can carry: its own
    companions, the ledger's, and `sig_appr`. The static set makes the audit
    session a function of the protocol alone, so a `config` bundle can
    measure it (plan O.2, constructor `audit`)."""
    comps = (session.get("Session_Context") or {}).get("ASP_Comps") or {}
    return sorted(set(comps.values()) | set(LEDGER_ASP_COMPS.values()) | {"sig_appr"})


def audit_session(session: dict, appraiser_asps: Optional[List[str]] = None) -> dict:
    """The B.6 audit session: every appraiser ASP (`audit_appraisers`, plus
    any the caller found in a package) gets the pass-through companion, so
    APPR over an appraisal package judges its `sig`, `generate_nonce` and
    `hashevidence` events and passes the verdict nodes through."""
    s = ledger_session(session)
    comps = s["Session_Context"]["ASP_Comps"]
    for a in sorted(set(appraiser_asps or []) | set(audit_appraisers(session))):
        comps.setdefault(a, PASSTHROUGH_APPR)
    return s


def audit_manifest(manifest: dict) -> dict:
    """The audit run's manifest: the ledger manifest plus the pass-through companion."""
    m = ledger_manifest(manifest)
    m["ASPS"] = sorted(set(m["ASPS"]) | {PASSTHROUGH_APPR})
    return m


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
                               archive: Optional[ArchiveFn], fresh: str = "none") -> LedgerAppraisal:
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
    et = inject_binding_golden(appr_payload[1], golden_b64)
    lane_g, lane_prov = stored_lane_goldens(ledger, target) if has_lane(appr_payload, session) else ({}, [])
    if lane_g:
        et = inject_goldens(et, lane_g, only_known=True)
    evidence = [appr_payload[0], et]
    ap = lp.model_copy(update={"session": session, "manifest": audit_manifest(protocol.manifest)})
    req, lane, claim = prepare_run(config, client, ap, protocol.protocol_id,
                                   "audit_combined" if needs_keep(ledger, target) else "audit",
                                   lambda l: _request(ap, appraisal_term(l), evidence), fresh)
    try:
        resp = _run(client, ap, req)
    except Exception as e:
        rep.error = f"audit run failed: {e}"
        return rep
    if not resp.get("SUCCESS"):
        rep.error = f"audit run failed: {str(resp.get('PAYLOAD'))[:300]}"
        return rep
    audit_payload = resp["PAYLOAD"]
    if archive:
        rep.appraisal_ref = archive(resp, protocol.protocol_id, "appraisal-of-appraisal")
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
    rep.golden_provenance = [GoldenProvenance(source="bundle", ref=f"bundle/{judged.key_id}", asp="hashevidence"),
                             *lane_prov]
    interp = Interpreter(kind="legacy-walker", tool="pybb.attestation.ledger_runs.components_from_layout")
    _commit_appraisal(ledger, ap, target, audit_payload, ad, components, rep, config, interp, req,
                      claim_record(claim, lane, config))
    return rep


# ── audits of stack / config bundles (plan O.6) ──────────────────────────────


MISSING_GOLDEN_B64 = base64.b64encode(bytes(32)).decode()  # a target the expectation source does not know: fails


def inject_goldens(et: Any, goldens: Dict[str, str], asp_id: str = "hashfile",
                   only_known: bool = False) -> Any:
    """Put a `golden_b64` into `asp_id` events' args of a package's (unsigned)
    evidence type, by `asp_targid` — the `_inject_goldens` pattern (plan B.9
    rule 2): pybb supplies the expectation, the CVM's `goldenbytes_appr`
    compares. By default every `asp_id` event is covered and a target with no
    golden gets a value that cannot match (an audit of a stack: a new binary
    fails); with `only_known` only the targets in `goldens` are touched (the
    claim lane inside a package whose other events carry their own goldens)."""
    et = copy.deepcopy(et)

    def walk(n: Any) -> None:
        if not isinstance(n, dict):
            return
        c, b = n.get("EvidenceT_CONSTRUCTOR"), n.get("EvidenceT_BODY")
        if c == "asp_evt":
            params = b[1]
            if params.get("ASP_ID") == asp_id:
                args = dict(params.get("ASP_ARGS") or {})
                targ = str(args.get("asp_targid", ""))
                if not only_known or targ in goldens:
                    args["golden_b64"] = goldens.get(targ, MISSING_GOLDEN_B64)
                    params["ASP_ARGS"] = args
            walk(b[2])
        elif c == "split_evt":
            walk(b[0]); walk(b[1])
        elif c in ("left_evt", "right_evt"):
            walk(b if isinstance(b, dict) else b[0])

    walk(et)
    return et


def _appraise_context_bundle(client: Any, ledger: Ledger, config: LedgerConfig, target: BundleRecord,
                             payload: list, rep: LedgerAppraisal, archive: Optional[ArchiveFn],
                             against: Optional[str]) -> LedgerAppraisal:
    """Plan O.6: judge a `stack` bundle against a blessing's goldens, or a
    `config` bundle against the hashes of the files it archived, inside the
    CVM with the ordinary `appraise` term under the generated context
    protocol. The result is an appraisal bundle with `inputs=[the bundle]`
    whose `golden_provenance` names the blessing or the bundle's own files."""
    from .ledger_context import context_goldens, context_protocol

    cp = context_protocol(target, config)
    try:
        desc = describe_package(payload, cp.session)
    except EvidenceLayoutError as e:
        rep.error = f"fetched package not describable: {e}"
        return rep
    rep.bid_ok = (desc.bid == target.bid and desc.rawev_sha256 == target.rawev_sha256)
    if not rep.bid_ok:
        rep.error = "fetched package does not reproduce the recorded bundle id / rawev hash"
        return rep
    goldens, fingerprint, provenance, err = context_goldens(ledger, target, against)
    if err:
        rep.error = err
        return rep
    rep.golden_provenance = provenance
    et = inject_goldens(payload[1], goldens)
    if fingerprint:  # the CVM judges H against the baseline's fingerprint too (plan P.5)
        et = inject_goldens(et, {"": fingerprint}, "hashevidence")
    evidence = [payload[0], et]
    req = _request(cp, appraisal_term(), evidence)
    try:
        resp = _run(client, cp, req)
    except Exception as e:
        rep.error = f"audit run failed: {e}"
        return rep
    if not resp.get("SUCCESS"):
        rep.error = f"audit run failed: {str(resp.get('PAYLOAD'))[:300]}"
        return rep
    appr_payload = resp["PAYLOAD"]
    if archive:
        rep.appraisal_ref = archive(resp, target.protocol_id, f"appraisal-{target.role}")
    try:
        appr_desc = describe_package(appr_payload, cp.session, nonce_targid=APPRAISER_NONCE_TARGID)
    except EvidenceLayoutError as e:
        rep.error = f"audit package not describable: {e}"
        return rep
    if appr_desc.bid is None:
        rep.error = "audit package carries no appraiser nonce"
        return rep
    rep.appraisal_bid, rep.assurance = appr_desc.bid, appr_desc.assurance
    components = interpret_appraisal(appr_payload, cp)
    if isinstance(components, str):
        rep.error = components
        return rep
    rep.components = components
    rep.passed = overall_verdict(components)
    rep.signature_ok = _verdict_of(components, "sig_appr")
    rep.nonce_wellformed = _verdict_of(components, "nonce_appr")
    _commit_appraisal(ledger, cp, target, appr_payload, appr_desc, components, rep, config,
                      interpreter_used(), req)
    return rep
