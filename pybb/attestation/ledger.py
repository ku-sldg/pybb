"""
Append-only ledger of Copland bundles — schema v2 (design: docs/ledger_plan.md,
section K; v1 history in sections A–I).

Every CVM run — a measurement, an appraisal, a provisioning run, a (future)
challenge — produces one signed, nonce'd package, and the ledger records it
as one `bundle` keyed by the sha256 of the nonce the CVM drew for that run.
What a bundle is evidence *of* is its `role` and its `inputs`: a
measurement is about the target system, an appraisal is about the bundle it
names as input (bound to it by a `hashevidence` value) and carries its own
`verdict`, so one measurement can be judged any number of times by any
policy. `judged_by/<input>/<appraisal>` pointers make those judgments one
prefix scan; a `mirror` record per push to a store witnesses what has been
mirrored; `restore` records a restore. Two further bundle roles record the
run context as Copland evidence (plan section O): a `stack` bundle is the
CVM/asp-libs installation measured by the CVM, a `config` bundle is one
protocol's exact inputs; a `blessing` record is the operator's approval of
a stack bundle. Runs carry no pointer to either: readers derive what was in
force from writer identity and transaction order. Five kinds, nothing
written about a run after its batch.

Division of labour (plan B.9): pybb IDENTIFIES and DESCRIBES evidence — it
hashes bytes to key and index them and reads evidence structure to label
it — and the CVM JUDGES. The one check pybb owns outright is refusing a
bundle id the ledger already holds.

This module holds the v2 records, the package inspection helpers, the
`Ledger` interface and `FileLedger` (a JSONL hash chain for tests and the
no-server fallback). immudb lives in `ledger_immudb.py`; v1 records are
readable through `ledger_v1.py`.
"""

from __future__ import annotations

import base64
import os
import secrets
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ledger_common import (  # noqa: F401  (re-exported)
    APPRAISER_NONCE_TARGID,
    ASSURANCE_RANK,
    GENESIS,
    NONCE_ASP,
    NONCE_TARGID,
    SIG_ASPS,
    AssuranceLevel,
    DuplicateNonceError,
    EvidenceLayoutError,
    Freshness,
    LedgerError,
    LedgerIntegrityError,
    assurance_at_least,
    canonical_json,
    sha256_hex,
    utc_now,
)

import json  # noqa: E402

SCHEMA = "pybb-ledger/v2"
Role = Literal["measurement", "appraisal", "provision", "challenge", "stack", "config"]


# ── record schema (plan section K) ───────────────────────────────────────────


class LedgerRecord(BaseModel):
    """Common envelope. Unknown fields are preserved, never dropped; None
    fields are omitted from the stored form so a measurement bundle never
    shows appraisal-only keys."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: str = Field(default=SCHEMA, alias="schema")
    kind: str
    bid: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)
    committer_fp: str = ""
    pybb_version: str = ""
    appraiser_id: str = ""

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, mode="json", exclude_none=True)

    def canonical(self) -> bytes:
        return canonical_json(self.to_dict())

    def content_sha256(self) -> str:
        return sha256_hex(self.canonical())


class SlotRef(BaseModel):
    """Where an event's output sits in the flat RawEv list. A reading tool
    (plan L): it appears in `PackageDescription`, never in a record."""

    slot: int
    asp: str
    asp_targid: Optional[str] = None


class NonceInfo(BaseModel):
    """The bundle's nonce: which ASP drew it and its value (stored in clear;
    a nonce's worth is unpredictability before use, not secrecy after).
    Position-free (plan L): where it sat is re-derived from the package."""

    asp: str
    b64: str
    bytes: int


class SignatureInfo(BaseModel):
    """That, and by which ASP, the package is signed, and whose key pybb
    trusts. Position-free (plan L)."""

    present: bool
    asp: Optional[str] = None
    signer_fp: Optional[str] = None


class ToolingRef(BaseModel):
    """Copland evidence identifying the binaries in force (plan B.8)."""

    kind: Literal["bundle", "run"]
    ref: str


class Location(BaseModel):
    """One place a blob is or will be. `store` is `local` or a configured
    store id such as `github:owner/name`; remote paths are content-addressed
    and therefore known at commit time (plan K decision 7)."""

    store: str
    path: str


class BlobRef(BaseModel):
    """Archived bytes: hash, size, encoding and every known location."""

    blob_sha256: str
    blob_bytes: int
    encoding: str = "gzip+json"
    locations: List[Location] = []
    # set when pybb assembled these bytes from a span of another bundle's
    # package (the lifted P of a `combined` run, plan M.2): that bundle's id
    derived_from: Optional[str] = None


class InputRef(BaseModel):
    """A bundle this run took as initial evidence. For an appraisal
    `binding_hash` is the value of the `hashevidence` slot over the judged
    bundle's flattened RawEv bytes — compare with that bundle's
    `rawev_sha256` (plan L.1: a cross-check, never a source of truth)."""

    bid: str
    binding_hash: Optional[str] = None


class FailingComponent(BaseModel):
    targ_id: Optional[str] = None
    appr_asp: str = ""
    reason: str = ""


class Interpreter(BaseModel):
    kind: Literal["verified-summary", "legacy-walker"]
    tool: str = ""


class Verdict(BaseModel):
    """An appraisal bundle's reading (plan K decision 2)."""

    passed: bool
    components_total: int = 0
    components_failed: int = 0
    failing: List[FailingComponent] = []
    components_sha256: str = ""
    components_blob: Optional[BlobRef] = None
    interpreter: Interpreter
    # appraisals of a stored bundle: the ledger/bytes/id checks pybb made
    checks: Dict[str, bool] = {}
    # agreement with the input measurement's live appraisal, when this is a
    # later appraisal of the same measurement under the same policy
    agrees_with_live: Optional[bool] = None


class ProvisionInfo(BaseModel):
    golden_ts: str = ""
    targets: int = 0


class ChallengeInfo(BaseModel):
    """Section G (planned): the appraiser's pre-registered challenge."""

    requested_protocol: str = ""
    requester: str = ""
    issued_at: str = ""
    expires_at: str = ""


class StackInfo(BaseModel):
    """On a `stack` bundle (plan O.1): the CVM/asp-libs installation the CVM
    measured. `plc` is the Copland place the CVM ran as; `executables` is
    the number of `stack:*` targets."""

    plc: str = ""
    executables: int = 0


class ConfigFile(BaseModel):
    """One materialized input of a `config` bundle, archived as a blob so a
    reader can fetch the exact term/session/manifest a run used."""

    targ_id: str
    blob: BlobRef


class ConfigInfo(BaseModel):
    """On a `config` bundle (plan O.2): one protocol's inputs per term
    constructor pybb can run."""

    constructors: List[str] = []
    files: List[ConfigFile] = []


class BundleRecord(LedgerRecord):
    """One record per CVM run output (plan K.1)."""

    kind: Literal["bundle"] = "bundle"
    role: Role
    protocol_id: str
    term_sha256: str = ""
    session_sha256: str = ""
    manifest_sha256: str = ""
    response_sha256: str
    blob: BlobRef
    rawev_count: int
    rawev_sha256: str
    nonce: Optional[NonceInfo] = None  # None only on legacy nonce-less provisioning bundles
    signature: SignatureInfo
    assurance: AssuranceLevel
    freshness: Freshness = "post-hoc"
    exception_reason: Optional[str] = None
    tooling: Optional[ToolingRef] = None
    error: str = ""  # measurement whose appraisal never happened: why
    # the term shape that produced this package (plan M.3a): `split`,
    # `combined`, `measure` (provisioning); None on foreign or legacy bundles
    shape: Optional[str] = None
    # role-gated members (serialized only when set)
    inputs: Optional[List[InputRef]] = None
    verdict: Optional[Verdict] = None
    appraisal_kind: Optional[str] = None
    provision: Optional[ProvisionInfo] = None
    state: Optional[str] = None
    challenge: Optional[ChallengeInfo] = None
    # run context (plan O): stack / config bundles describe themselves; an
    # audit of a stack bundle names the blessing its goldens came from
    stack: Optional[StackInfo] = None
    config: Optional[ConfigInfo] = None
    baseline: Optional[str] = None

    @model_validator(mode="after")
    def _role_invariants(self) -> "BundleRecord":
        if self.nonce is not None:
            if sha256_hex(base64.b64decode(self.nonce.b64)) != self.bid:
                raise ValueError("bid is not sha256 of the nonce bytes")
            if len(base64.b64decode(self.nonce.b64)) != self.nonce.bytes:
                raise ValueError("nonce.bytes disagrees with the nonce length")
        elif self.bid is not None:
            raise ValueError("a bundle without a nonce has no bid (legacy bundles key by blob hash)")
        if self.role == "appraisal":
            if not self.inputs or self.verdict is None:
                raise ValueError("an appraisal bundle needs inputs and a verdict")
        else:
            if self.inputs and self.role != "challenge" and self.role != "measurement":
                raise ValueError(f"a {self.role} bundle takes no inputs")
            if self.verdict is not None or self.appraisal_kind is not None:
                raise ValueError(f"a {self.role} bundle carries no verdict")
        if self.role == "measurement" and self.inputs and len(self.inputs) != 1:
            raise ValueError("a challenged measurement names exactly one challenge bundle")
        if self.role == "challenge" and not self.state:
            raise ValueError("a challenge bundle needs a state")
        if self.role != "challenge" and (self.state or self.challenge):
            raise ValueError(f"a {self.role} bundle has no challenge state")
        if self.stack is not None and self.role != "stack":
            raise ValueError(f"a {self.role} bundle carries no stack info")
        if self.config is not None and self.role != "config":
            raise ValueError(f"a {self.role} bundle carries no config info")
        if self.baseline is not None and self.role != "appraisal":
            raise ValueError(f"a {self.role} bundle names no baseline")
        return self

    @property
    def key_id(self) -> str:
        return self.bid if self.bid else f"sha256:{self.blob.blob_sha256}"


class JudgedByRecord(LedgerRecord):
    """Pointer: `bid` (the judged bundle) → `appraisal_bid` (plan K.2)."""

    kind: Literal["judged_by"] = "judged_by"
    bid: str
    appraisal_bid: str


class MirrorRecord(LedgerRecord):
    """One per push to a store (plan K decision 7)."""

    kind: Literal["mirror"] = "mirror"
    store: str
    repo: str = ""
    commit: str = ""
    state_tx: int
    state_hash: str = ""
    journal_from_tx: int = 0
    journal_to_tx: int = 0
    blobs: int = 0
    blob_hashes_sha256: str = ""
    skipped: List[Dict[str, str]] = []


class RestoreRecord(LedgerRecord):
    kind: Literal["restore"] = "restore"
    mode: Literal["exact", "replay"]
    source_repo: str
    source_commit: str
    source_last_state_tx: int
    tx_count: int


class BlessingRecord(LedgerRecord):
    """The operator's approval of a `stack` bundle (plan O.5): "these are the
    binaries I trust". `goldens` are the measured values read off that
    bundle's signed package, target id -> base64 hash, so an audit of a
    later stack bundle takes its expectations from the ledger alone. One
    blessing per stack bundle; attributable through the envelope."""

    kind: Literal["blessing"] = "blessing"
    stack_bid: str
    targets: List[str] = []
    goldens: Dict[str, str] = {}
    note: str = ""


RECORD_TYPES = {
    "bundle": BundleRecord,
    "judged_by": JudgedByRecord,
    "mirror": MirrorRecord,
    "restore": RestoreRecord,
    "blessing": BlessingRecord,
}


def parse_record(data: dict) -> Any:
    """Rebuild the typed record from its stored dict. v1 records (by their
    `schema` tag) come back as `ledger_v1` models; unknown v2 kinds stay
    generic."""
    if str(data.get("schema", "")).endswith("/v1"):
        from .ledger_v1 import parse_record_v1

        return parse_record_v1(data)
    cls = RECORD_TYPES.get(data.get("kind", ""), LedgerRecord)
    return cls.model_validate(data)


def store_slug(store: str) -> str:
    """A store id as a key/path segment: `github:owner/name` → `github-owner-name`."""
    return store.replace(":", "-").replace("/", "-")


def key_for(record: Any) -> str:
    """The ledger key of a record (plan K.2)."""
    k = record.kind
    if k == "bundle":
        return f"bundle/{record.key_id}"
    if k == "judged_by":
        return f"judged_by/{record.bid}/{record.appraisal_bid}"
    if k == "mirror":
        return f"mirror/{store_slug(record.store)}/{record.state_tx:012d}"
    if k == "restore":
        return f"restore/{record.created_at}"
    if k == "blessing":
        return f"blessing/{record.stack_bid}"
    if str(getattr(record, "schema_version", "")).endswith("/v1"):
        from .ledger_v1 import key_for as key_for_v1

        return key_for_v1(record)
    raise LedgerError(f"no key rule for record kind '{k}'")


# ── package inspection: identify and describe, never judge ───────────────────


class SlotSpan(BaseModel):
    """One event's output span in the flat RawEv list (DFS order, newest first).

    `companion` marks an appraiser event (a value of the session's
    ASP_Comps); `retained` marks the appraised evidence bytes an EXTEND
    companion keeps beneath its verdict (attributed to the measured ASP);
    `input` marks events beneath a `hashevidence` node — the package that
    ASP hashed, kept behind the hash when it is typed EXTEND (plan M.2).
    Input events belong to another package: `describe_package` never takes
    this package's nonce or signature from them."""

    asp: str
    plc: str = ""
    args: Dict[str, Any] = {}
    start: int
    count: int
    companion: bool = False
    retained: bool = False
    input: bool = False

    @property
    def asp_targid(self) -> Optional[str]:
        t = self.args.get("asp_targid")
        return str(t) if t else None


def _fwd_of(asp_types: dict, asp_id: str) -> Tuple[str, int]:
    t = asp_types.get(asp_id)
    if not isinstance(t, dict):
        raise EvidenceLayoutError(f"ASP '{asp_id}' is not in the session's ASP_Types")
    fwd = t.get("FWD", t)
    kind = fwd.get("FWD") if isinstance(fwd, dict) else None
    size = fwd.get("_BODY") if isinstance(fwd, dict) else None
    if kind not in ("EXTEND", "REPLACE") or not isinstance(size, int):
        raise EvidenceLayoutError(
            f"ASP '{asp_id}': unsupported or incomplete FWD type {t!r}")
    return kind, size


def _appraised_node(sub: Any) -> Any:
    """The event a companion judged: the CVM records it as a path of
    left_evt/right_evt wrappers (outermost wrapper = innermost split
    choice) over the original evidence type."""
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
    return node if isinstance(node, dict) and node.get("EvidenceT_CONSTRUCTOR") == "asp_evt" else None


def slot_layout(et: Any, session: dict) -> List[SlotSpan]:
    """
    Lay the evidence type out against the flat RawEv list.

    Mirrors the CVM's bundling. Measurement events: an EXTEND event's output
    precedes (is prepended to) the evidence it extended, a REPLACE event's
    output stands in for it, splits lay out left then right. Companion
    (appraiser) events — the values of the session's ASP_Comps — carry the
    original evidence type beneath them for attribution only: a REPLACE
    companion contributes just its verdict slots; an EXTEND companion
    contributes its verdict slots plus the bytes of the event it judged
    (that event's whole raw-package subtree), which the CVM retains. The
    judged event's own sub-evidence is appraised separately, as a sibling
    in the output tree. Spike-verified on hashfile/goldenbytes_appr
    (REPLACE) and run_command_rocq/run_command_rocq_appr (EXTEND).
    """
    ctx = session.get("Session_Context") or {}
    asp_types = ctx.get("ASP_Types") or {}
    companions = set((ctx.get("ASP_Comps") or {}).values())
    spans: List[SlotSpan] = []
    cursor = [0]
    depth_input = [0]  # > 0 while walking beneath a hashevidence node

    def measured_size(node: Any) -> int:
        """Bytes of a raw-package subtree (measurement semantics)."""
        if not isinstance(node, dict):
            raise EvidenceLayoutError(f"malformed evidence type node {node!r}")
        ctor = node.get("EvidenceT_CONSTRUCTOR")
        body = node.get("EvidenceT_BODY")
        if ctor == "mt_evt":
            return 0
        if ctor == "nonce_evt":
            return 1
        if ctor == "asp_evt":
            _plc, params, sub = body
            kind, size = _fwd_of(asp_types, params.get("ASP_ID", ""))
            return size + (measured_size(sub) if kind == "EXTEND" else 0)
        if ctor == "split_evt":
            return measured_size(body[0]) + measured_size(body[1])
        if ctor in ("left_evt", "right_evt"):
            return measured_size(body if isinstance(body, dict) else body[0])
        raise EvidenceLayoutError(f"unknown evidence constructor {ctor!r}")

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            raise EvidenceLayoutError(f"malformed evidence type node {node!r}")
        ctor = node.get("EvidenceT_CONSTRUCTOR")
        body = node.get("EvidenceT_BODY")
        if ctor == "mt_evt":
            return
        if ctor == "nonce_evt":
            spans.append(SlotSpan(asp="<nonce_evt>", start=cursor[0], count=1))
            cursor[0] += 1
            return
        if ctor == "asp_evt":
            plc, params, sub = body
            asp_id = params.get("ASP_ID", "")
            kind, size = _fwd_of(asp_types, asp_id)
            is_companion = asp_id in companions
            spans.append(SlotSpan(asp=asp_id, plc=str(plc),
                                  args=dict(params.get("ASP_ARGS") or {}),
                                  start=cursor[0], count=size, companion=is_companion,
                                  input=depth_input[0] > 0))
            cursor[0] += size
            if is_companion:
                if kind == "EXTEND":
                    judged = _appraised_node(sub)
                    if judged is None:
                        raise EvidenceLayoutError(
                            f"EXTEND companion '{asp_id}': cannot locate the judged event")
                    kept = measured_size(judged)
                    jp = judged["EvidenceT_BODY"][1]
                    spans.append(SlotSpan(asp=jp.get("ASP_ID", ""), plc=str(judged["EvidenceT_BODY"][0]),
                                          args=dict(jp.get("ASP_ARGS") or {}), start=cursor[0],
                                          count=kept, retained=True))
                    cursor[0] += kept
                return  # the type beneath a companion is attribution only
            if kind == "EXTEND":
                if asp_id == "hashevidence":
                    depth_input[0] += 1
                    walk(sub)
                    depth_input[0] -= 1
                else:
                    walk(sub)
            return  # REPLACE measurement: the sub-evidence bytes are gone
        if ctor == "split_evt":
            walk(body[0])
            walk(body[1])
            return
        if ctor in ("left_evt", "right_evt"):
            walk(body if isinstance(body, dict) else body[0])
            return
        raise EvidenceLayoutError(f"unknown evidence constructor {ctor!r}")

    walk(et)
    return spans


def rawev_bytes(payload: list) -> List[bytes]:
    return [base64.b64decode(s) for s in payload[0].get("RawEv", [])]


class PackageDescription(BaseModel):
    """What pybb can say about a package by looking at it (no judgment)."""

    rawev_count: int
    response_sha256: str  # canonical JSON of the whole payload
    rawev_sha256: str  # sha256 over the flattened RawEv bytes (= hashevidence)
    spans: List[SlotSpan]
    nonce: Optional[SlotRef] = None  # where the nonce sits (reading only)
    bid: Optional[str] = None
    nonce_b64: Optional[str] = None
    signature_ref: Optional[SlotRef] = None  # where the signature sits (reading only)
    signature: SignatureInfo  # position-free, as recorded
    assurance: AssuranceLevel

    def span_for(self, asp: str, asp_targid: Optional[str] = None) -> Optional[SlotSpan]:
        for sp in self.spans:
            if sp.asp == asp and (asp_targid is None or sp.asp_targid == asp_targid):
                return sp
        return None


def describe_package(payload: list, session: dict,
                     nonce_targid: Optional[str] = NONCE_TARGID) -> PackageDescription:
    """
    Describe a raw package `[RawEv-dict, EvidenceT]` against its session.

    Identifies the nonce event (deriving `nid` as sha256 of its bytes) and
    the signature event, and labels the assurance level from what is
    present. Raises EvidenceLayoutError when the layout does not account
    for every RawEv slot, when there is not exactly one nonce event, or
    when the nonce event's output is not a single slot.
    """
    if not isinstance(payload, list) or len(payload) < 2:
        raise EvidenceLayoutError("payload is not [RawEv, EvidenceT]")
    raw = rawev_bytes(payload)
    spans = slot_layout(payload[1], session)
    accounted = sum(sp.count for sp in spans)
    if accounted != len(raw):
        raise EvidenceLayoutError(
            f"evidence type accounts for {accounted} slots, RawEv has {len(raw)}")

    nonces = [sp for sp in spans if sp.asp == NONCE_ASP and not sp.input
              and (nonce_targid is None or sp.asp_targid == nonce_targid)]
    nonce_ref: Optional[SlotRef] = None
    bid: Optional[str] = None
    nonce_b64: Optional[str] = None
    if len(nonces) > 1:
        raise EvidenceLayoutError(f"{len(nonces)} nonce events in one package")
    if nonces:
        sp = nonces[0]
        if sp.count != 1:
            raise EvidenceLayoutError("nonce event does not occupy exactly one slot")
        nonce_ref = SlotRef(slot=sp.start, asp=sp.asp, asp_targid=sp.asp_targid)
        bid = sha256_hex(raw[sp.start])
        nonce_b64 = payload[0]["RawEv"][sp.start]

    sigs = [sp for sp in spans if sp.asp in SIG_ASPS and not sp.input]
    signature_ref: Optional[SlotRef] = None
    if sigs:
        sp = sigs[0]
        signature_ref = SlotRef(slot=sp.start, asp=sp.asp, asp_targid=sp.asp_targid)
        signature = SignatureInfo(present=True, asp=sp.asp)
    else:
        signature = SignatureInfo(present=False)

    if signature.present and nonce_ref:
        assurance: AssuranceLevel = "signed+nonce"
    elif signature.present:
        assurance = "signed"
    elif nonce_ref:
        assurance = "nonce"
    else:
        assurance = "none"

    return PackageDescription(
        rawev_count=len(raw),
        response_sha256=sha256_hex(canonical_json(payload)),
        rawev_sha256=sha256_hex(b"".join(raw)),
        spans=spans,
        nonce=nonce_ref,
        bid=bid,
        nonce_b64=nonce_b64,
        signature_ref=signature_ref,
        signature=signature,
        assurance=assurance,
    )


def derive_bid(payload: list, session: dict) -> str:
    """The bundle id, or EvidenceLayoutError when the package has no nonce."""
    desc = describe_package(payload, session)
    if desc.bid is None:
        raise EvidenceLayoutError("package carries no generate_nonce event")
    return desc.bid


derive_nid = derive_bid  # transitional alias


# ── configuration ────────────────────────────────────────────────────────────


def _read_secret(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


class ContextConfig(BaseModel):
    """Run context (plan O): the generated protocols that measure the stack
    and each protocol's inputs, and where their materialized files live
    (relative to `state_dir`). There is no cadence: measurement happens only
    on operator command (`examples/ledger_context.py`)."""

    stack_protocol_id: str = "attestation_stack"
    config_protocol_id: str = "attestation_config"
    dir: str = "context"


class LedgerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3322
    db: str = Field(default_factory=lambda: os.environ.get("PYBB_IMMUDB_DB", "pybb2"))
    user: str = Field(default_factory=lambda: os.environ.get("PYBB_IMMUDB_USER", "pybb"))
    # PYBB_IMMUDB_PASSWORD, else the file <state_dir>/immudb_password written
    # by scripts/immudb_dev.sh bootstrap (never a value in code or chat)
    password: str = Field(default_factory=lambda: os.environ.get("PYBB_IMMUDB_PASSWORD")
                          or _read_secret(os.path.expanduser("~/.pybb/immudb_password")))
    state_dir: str = Field(default_factory=lambda: os.path.expanduser("~/.pybb"))
    # the verifying public key (the copy baked into sig_appr at build time);
    # its fingerprint is every record's committer_fp
    verify_key_path: str = Field(default_factory=lambda: os.environ.get(
        "PYBB_VERIFY_KEY",
        os.path.expanduser("~/Claude_workspace/asp-libs/common_files/unsecure_pub_key_dont_use.pem")))
    # PYBB_EVIDENCE_REPO, else the clone path written to <state_dir>/evidence_repo
    evidence_repo: Optional[str] = Field(default_factory=lambda: os.environ.get("PYBB_EVIDENCE_REPO")
                                         or _read_secret(os.path.expanduser("~/.pybb/evidence_repo")) or None)
    # where provisioning bundles live (<golden_root>/_bundles/<pid>/)
    golden_root: str = Field(default_factory=lambda: os.environ.get("PYBB_GOLDEN_ROOT", "golden"))
    fail_open: bool = False
    min_assurance: AssuranceLevel = "signed+nonce"
    assurance_exceptions: Dict[str, str] = {}  # protocol_id -> reason
    context: ContextConfig = ContextConfig()
    appraiser_id: Optional[str] = None  # None: load or create under state_dir
    # bundle shapes (plan M): `split` (two runs; appraisal now or later) or
    # `combined` (one run; same two artifacts); per protocol, else the default
    default_shape: str = Field(default_factory=lambda: os.environ.get("PYBB_BUNDLE_SHAPE", "split"))
    shapes: Dict[str, str] = {}  # protocol_id -> shape

    def shape_for(self, protocol_id: str) -> str:
        return self.shapes.get(protocol_id, self.default_shape)


def load_appraiser_id(state_dir: str) -> str:
    """
    The opaque, stable id of this pybb installation (plan I.1): random,
    created once under state_dir, never a hostname or username.
    """
    path = Path(state_dir) / "appraiser_id"
    if path.is_file():
        value = path.read_text().strip()
        if value:
            return value
    path.parent.mkdir(parents=True, exist_ok=True)
    value = "ap-" + secrets.token_hex(4)
    path.write_text(value + "\n")
    return value


def pybb_version() -> str:
    try:
        from importlib.metadata import version

        return version("pybb")
    except Exception:
        return "0.0.0"


# ── ledger interface ─────────────────────────────────────────────────────────


class Receipt(BaseModel):
    tx: int
    keys: List[str]
    verified: bool = False  # client-side proof checked (immudb); FileLedger: chain ok


class Ledger(ABC):
    """The ledger interface (plan K). Every write is append-only; the only key
    the appraiser ever writes twice is a `challenge` bundle's (section G)."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def get_record(self, key: str) -> Optional[Any]: ...

    @abstractmethod
    def _write_batch(self, records: List[Any]) -> Receipt: ...

    @abstractmethod
    def history(self) -> Iterator[Tuple[int, str, Any]]:
        """Every (tx, key, record) in transaction order."""

    def scan_prefix(self, prefix: str) -> Dict[str, Any]:
        """Latest record per key under `prefix`; backends override with a
        real prefix scan."""
        out: Dict[str, Any] = {}
        for _tx, key, rec in self.history():
            if key.startswith(prefix):
                out[key] = rec
        return out

    def journal(self, since_tx: int = 0) -> Iterator[dict]:
        """Journal lines (plan H.1) for txs after `since_tx`, in order:
        `{tx, ts, db, keys: {key: content_sha256}}`."""
        current: Optional[dict] = None
        for tx, key, rec in self.history():
            if tx <= since_tx:
                continue
            if current is None or current["tx"] != tx:
                if current is not None:
                    yield current
                current = {"tx": tx, "ts": "", "db": self.db_name(), "keys": {}}
            current["keys"][key] = rec.content_sha256()
        if current is not None:
            yield current

    def db_name(self) -> str:
        return "ledger"

    def state(self) -> dict:
        """The backend's current head: `{kind, db, tx_id, tx_hash_hex}`."""
        raise NotImplementedError

    # -- writes ---------------------------------------------------------------

    def commit_bundles(self, bundles: List[BundleRecord]) -> Receipt:
        """
        One batch for one or more bundles (plan K.3): a live run passes its
        measurement and appraisal together; a later appraisal passes one.
        `judged_by` pointers are added for every appraisal input. Refused
        when any bundle key already exists (the uniqueness rule — each
        bundle's own nonce), when an appraisal's input is neither in the
        ledger nor in this batch, or when records disagree.
        """
        if not bundles:
            raise LedgerError("empty batch")
        keys = [key_for(b) for b in bundles]
        if len(set(keys)) != len(keys):
            raise LedgerError("commit_bundles: duplicate bundle in one batch")
        for b, k in zip(bundles, keys):
            if self.exists(k):
                if b.role == "challenge":
                    continue  # versions of a challenge are allowed (section G)
                raise DuplicateNonceError(f"duplicate bundle {b.key_id}")
        in_batch = set(k.split("/", 1)[1] for k in keys)
        pointers: List[JudgedByRecord] = []
        for b in bundles:
            for inp in b.inputs or []:
                if inp.bid not in in_batch and not self.exists(f"bundle/{inp.bid}"):
                    raise LedgerError(f"commit_bundles: input bundle {inp.bid} is not in the ledger")
                if b.role == "appraisal":
                    pointers.append(JudgedByRecord(bid=inp.bid, appraisal_bid=b.key_id,
                                                   committer_fp=b.committer_fp,
                                                   pybb_version=b.pybb_version,
                                                   appraiser_id=b.appraiser_id))
        return self._write_batch([*bundles, *pointers])

    def commit_mirror(self, mirror: MirrorRecord) -> Receipt:
        if self.exists(key_for(mirror)):
            raise LedgerError(f"mirror record for {mirror.store} at tx {mirror.state_tx} already exists")
        return self._write_batch([mirror])

    def commit_restore(self, restore: RestoreRecord) -> Receipt:
        return self._write_batch([restore])

    def commit_blessing(self, blessing: BlessingRecord) -> Receipt:
        """One blessing per stack bundle (plan O.5); the bundle must be a
        `stack` bundle already in the ledger."""
        rec = self.get_record(f"bundle/{blessing.stack_bid}")
        if not isinstance(rec, BundleRecord) or rec.role != "stack":
            raise LedgerError(f"{blessing.stack_bid} is not a stack bundle in the ledger")
        if self.exists(key_for(blessing)):
            raise LedgerError(f"stack bundle {blessing.stack_bid} is already blessed")
        return self._write_batch([blessing])

    def blessing_of(self, stack_bid: str) -> Optional[BlessingRecord]:
        rec = self.get_record(f"blessing/{stack_bid}")
        return rec if isinstance(rec, BlessingRecord) else None

    # -- reads ----------------------------------------------------------------

    def get(self, bid: str) -> BundleRecord:
        rec = self.get_record(f"bundle/{bid}")
        if not isinstance(rec, BundleRecord):
            raise LedgerError(f"bundle {bid} is not in the ledger")
        return rec

    def tx_of(self, key: str) -> Optional[int]:
        """The transaction that wrote `key`'s current value, when the backend
        exposes it."""
        return None

    def appraisals_of(self, bid: str) -> List[BundleRecord]:
        """Every appraisal bundle whose input is `bid`, in ledger order (a
        prefix scan returns key order, so the pointers' tx ids sort them)."""
        pointers = self.scan_prefix(f"judged_by/{bid}/")
        out: List[BundleRecord] = []
        for key in sorted(pointers, key=lambda k: (self.tx_of(k) or 0, getattr(pointers[k], "created_at", ""), k)):
            rec = self.get_record(f"bundle/{key.rsplit('/', 1)[1]}")
            if isinstance(rec, BundleRecord):
                out.append(rec)
        return out

    def latest_mirror(self, store: str) -> Optional[MirrorRecord]:
        hits = self.scan_prefix(f"mirror/{store_slug(store)}/")
        if not hits:
            return None
        rec = hits[max(hits)]
        return rec if isinstance(rec, MirrorRecord) else None

    def records(self, kind: Optional[str] = None, protocol_id: Optional[str] = None,
                role: Optional[str] = None) -> Iterator[Any]:
        for _tx, _key, rec in self.history():
            if kind and rec.kind != kind:
                continue
            if protocol_id and getattr(rec, "protocol_id", None) != protocol_id:
                continue
            if role and getattr(rec, "role", None) != role:
                continue
            yield rec

    def bundles(self, protocol_id: Optional[str] = None, role: Optional[str] = None) -> List[BundleRecord]:
        return [r for r in self.records(kind="bundle", protocol_id=protocol_id, role=role)
                if isinstance(r, BundleRecord)]


# ── FileLedger: JSONL hash chain ─────────────────────────────────────────────


class FileLedger(Ledger):
    """
    Append-only JSONL ledger with a hash chain: each line is one
    transaction `{tx, ts, prev, entries:[{key, value, content_sha256}], hash}`
    with `hash = sha256(prev || canonical({tx, ts, entries}))`. Values are
    the records' canonical JSON strings, so a reader can verify any value
    against its content hash exactly as with the immudb journal.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._txs: List[dict] = []
        self._latest: Dict[str, Tuple[int, dict]] = {}
        if self.path.exists():
            self._load()

    # -- chain ----------------------------------------------------------------

    @staticmethod
    def _tx_hash(prev: str, tx: int, ts: str, entries: List[dict]) -> str:
        body = canonical_json({"tx": tx, "ts": ts, "entries": entries})
        return sha256_hex(prev.encode("ascii") + body)

    def _load(self) -> None:
        prev = GENESIS
        with open(self.path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    tx = json.loads(line)
                except json.JSONDecodeError as e:
                    raise LedgerIntegrityError(f"{self.path}:{lineno}: not JSON ({e})")
                expected = self._tx_hash(prev, tx["tx"], tx["ts"], tx["entries"])
                if tx.get("prev") != prev or tx.get("hash") != expected:
                    raise LedgerIntegrityError(
                        f"{self.path}:{lineno}: chain broken at tx {tx.get('tx')}")
                if tx["tx"] != len(self._txs) + 1:
                    raise LedgerIntegrityError(
                        f"{self.path}:{lineno}: tx numbering gap at {tx['tx']}")
                for e in tx["entries"]:
                    if sha256_hex(e["value"].encode("utf-8")) != e["content_sha256"]:
                        raise LedgerIntegrityError(
                            f"{self.path}:{lineno}: value of {e['key']} does not match its hash")
                self._index(tx)
                prev = tx["hash"]

    def _index(self, tx: dict) -> None:
        self._txs.append(tx)
        for e in tx["entries"]:
            self._latest[e["key"]] = (tx["tx"], json.loads(e["value"]))

    def verify_chain(self) -> int:
        """Re-read the file and verify every link; returns the tx count."""
        fresh = FileLedger.__new__(FileLedger)
        fresh.path, fresh._txs, fresh._latest = self.path, [], {}
        if self.path.exists():
            fresh._load()
        return len(fresh._txs)

    # -- Ledger ---------------------------------------------------------------

    def exists(self, key: str) -> bool:
        return key in self._latest

    def get_record(self, key: str) -> Optional[LedgerRecord]:
        hit = self._latest.get(key)
        return parse_record(hit[1]) if hit else None

    def tx_of(self, key: str) -> Optional[int]:
        hit = self._latest.get(key)
        return hit[0] if hit else None

    def _write_batch(self, records: List[LedgerRecord]) -> Receipt:
        if not records:
            raise LedgerError("empty batch")
        entries = []
        for rec in records:
            value = rec.canonical().decode("utf-8")
            entries.append({"key": key_for(rec), "value": value,
                            "content_sha256": sha256_hex(value.encode("utf-8"))})
        prev = self._txs[-1]["hash"] if self._txs else GENESIS
        tx_no = len(self._txs) + 1
        ts = utc_now()
        tx = {"tx": tx_no, "ts": ts, "prev": prev, "entries": entries,
              "hash": self._tx_hash(prev, tx_no, ts, entries)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(tx, separators=(",", ":"), ensure_ascii=False) + "\n")
        self._index(tx)
        return Receipt(tx=tx_no, keys=[e["key"] for e in entries], verified=True)

    def history(self) -> Iterator[Tuple[int, str, LedgerRecord]]:
        for tx in self._txs:
            for e in tx["entries"]:
                yield tx["tx"], e["key"], parse_record(json.loads(e["value"]))

    def journal(self, since_tx: int = 0) -> Iterator[dict]:
        for tx in self._txs:
            if tx["tx"] > since_tx:
                yield {"tx": tx["tx"], "ts": tx["ts"], "db": self.db_name(),
                       "keys": {e["key"]: e["content_sha256"] for e in tx["entries"]}}

    def db_name(self) -> str:
        return self.path.stem

    def state(self) -> dict:
        return {"kind": "file", "db": self.db_name(), "tx_id": len(self._txs),
                "tx_hash_hex": self._txs[-1]["hash"] if self._txs else GENESIS}

    def __len__(self) -> int:
        return len(self._txs)
