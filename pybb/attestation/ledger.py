"""
Append-only ledger of Copland runs (design: docs/ledger_plan.md).

The ledger records what the CVM produced — a nonce'd, signed measurement
package; a signed, nonce-bound appraisal package; the verdict read out of
it — and where the bytes live. It is keyed and linked by nonce ids and
content hashes and carries no blackboard or orchestration concepts, so a
reader who knows nothing of pybb can verify it.

Division of labour (plan B.9): pybb IDENTIFIES and DESCRIBES evidence —
it hashes bytes to key and index them and reads evidence structure to
label it — and the CVM JUDGES. Nothing in this module verifies a
signature, compares a nonce, or compares a golden; those are companion
ASP verdicts, read back through the verified summarizer. The one check
pybb owns outright is duplicate-nonce refusal, which is ledger policy
over history the CVM cannot see.

This module holds the record schema (plan section I), canonicalization,
package inspection helpers, the `Ledger` interface, and `FileLedger`, a
JSONL hash chain used by tests and as the no-server fallback. The immudb
backend lives in `ledger_immudb.py` (plan step 4).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterator, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA = "pybb-ledger/v1"
GENESIS = "0" * 64

AssuranceLevel = Literal["signed+nonce", "signed", "nonce", "none"]
ASSURANCE_RANK: Dict[str, int] = {"none": 0, "nonce": 1, "signed": 2, "signed+nonce": 3}
Freshness = Literal["post-hoc", "pre-registered", "none"]

NONCE_ASP = "generate_nonce"
NONCE_TARGID = "nonce_targ"
APPRAISER_NONCE_TARGID = "appraiser_nonce_targ"
SIG_ASPS = ("sig", "sig_tpm")


# ── canonical form ───────────────────────────────────────────────────────────


def canonical_json(obj: Any) -> bytes:
    """The stored form of every record: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── errors ───────────────────────────────────────────────────────────────────


class LedgerError(RuntimeError):
    """Base class for ledger failures."""


class DuplicateNonceError(LedgerError):
    """A nonce id the ledger already holds: a replayed or duplicated package."""


class LedgerIntegrityError(LedgerError):
    """The stored ledger does not verify (broken chain, altered value)."""


class EvidenceLayoutError(LedgerError):
    """A package's evidence type cannot be laid out against its session."""


# ── record schema (plan section I) ───────────────────────────────────────────


class LedgerRecord(BaseModel):
    """Common envelope (I.1). Unknown fields are preserved, never dropped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # `schema` shadows a deprecated BaseModel attribute; alias it on the wire.
    schema_version: str = Field(default=SCHEMA, alias="schema")
    kind: str
    nid: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)
    committer_fp: str = ""
    pybb_version: str = ""
    appraiser_id: str = ""

    def to_dict(self) -> dict:
        return self.model_dump(by_alias=True, mode="json")

    def canonical(self) -> bytes:
        return canonical_json(self.to_dict())

    def content_sha256(self) -> str:
        return sha256_hex(self.canonical())


class SlotRef(BaseModel):
    """Where an event's output sits in the flat RawEv list."""

    slot: int
    asp: str
    asp_targid: Optional[str] = None


class SignatureInfo(BaseModel):
    present: bool
    slot: Optional[int] = None
    asp: Optional[str] = None
    signer_fp: Optional[str] = None
    # set only by a CVM-native audit (sig_appr verdict); never by pybb
    verified: Optional[bool] = None


class ToolingRef(BaseModel):
    """Copland evidence identifying the binaries in force (plan B.8)."""

    kind: Literal["bundle", "run"]
    ref: str


class Locator(BaseModel):
    kind: Literal["local", "github"]
    path: str
    appraiser_id: Optional[str] = None  # local: whose filesystem
    repo: Optional[str] = None  # github
    commit: Optional[str] = None
    git_blob_sha: Optional[str] = None


class NonceRecord(LedgerRecord):
    kind: Literal["nonce"] = "nonce"
    nid: str
    nonce_b64: str
    nonce_bytes: int
    role: Literal["measurement", "appraisal"] = "measurement"
    for_nid: Optional[str] = None
    state: str = "committed"
    freshness: Freshness = "post-hoc"
    protocol_id: str

    @model_validator(mode="after")
    def _nid_matches_bytes(self) -> "NonceRecord":
        raw = base64.b64decode(self.nonce_b64)
        if sha256_hex(raw) != self.nid:
            raise ValueError("nid is not sha256 of the nonce bytes")
        if len(raw) != self.nonce_bytes:
            raise ValueError("nonce_bytes disagrees with the nonce length")
        if self.role == "appraisal" and not self.for_nid:
            raise ValueError("an appraisal nonce must name the run it judged (for_nid)")
        return self


class EvidenceRecord(LedgerRecord):
    kind: Literal["evidence"] = "evidence"
    nid: str
    protocol_id: str
    term_sha256: str = ""
    session_sha256: str = ""
    manifest_sha256: str = ""
    response_sha256: str
    blob_sha256: str
    blob_bytes: int
    encoding: str = "gzip+json"
    rawev_count: int
    rawev_sha256: str
    signature: SignatureInfo
    nonce: SlotRef
    assurance: AssuranceLevel
    freshness: Freshness = "post-hoc"
    exception_reason: Optional[str] = None
    tooling: Optional[ToolingRef] = None
    locators: List[Locator] = []


class FailingComponent(BaseModel):
    targ_id: Optional[str] = None
    appr_asp: str = ""
    reason: str = ""


class Interpreter(BaseModel):
    kind: Literal["verified-summary", "legacy-walker"]
    tool: str = ""


class VerdictRecord(LedgerRecord):
    kind: Literal["verdict"] = "verdict"
    nid: str
    protocol_id: str
    passed: bool
    components_total: int = 0
    components_failed: int = 0
    failing: List[FailingComponent] = []
    components_sha256: str = ""
    appraisal_seq: int = 1
    evidence_assurance: AssuranceLevel
    appraisal_assurance: AssuranceLevel
    interpreter: Interpreter
    error: str = ""


class LocatorRecord(LedgerRecord):
    kind: Literal["locator"] = "locator"
    nid: str
    seq: int
    target: Literal["evidence", "appraisal", "components", "bundle"]
    blob_sha256: str
    locator: Locator
    verified: bool = False


class Binding(BaseModel):
    slot: int
    asp: str = "hashevidence"
    evidence_hash: str
    # goldenbytes_appr verdict from a CVM-native audit (plan B.6); null until one ran
    matches_evidence: Optional[bool] = None


class AppraisalRecord(LedgerRecord):
    kind: Literal["appraisal"] = "appraisal"
    nid: str
    seq: int
    mode: Literal["live", "audit"]
    anid: str
    response_sha256: str
    blob_sha256: str
    blob_bytes: int
    encoding: str = "gzip+json"
    rawev_sha256: str
    binding: Binding
    signature: SignatureInfo
    nonce: SlotRef
    assurance: AssuranceLevel
    freshness: Freshness = "post-hoc"
    passed: bool
    components_sha256: str = ""
    interpreter: Interpreter
    tooling: Optional[ToolingRef] = None
    checks: Dict[str, bool] = {}
    locator_used: Optional[Locator] = None
    agrees_with_recorded_verdict: Optional[bool] = None
    # audit of an APPRAISAL package (plan B.6 'audit of the audit'): the seq
    # of the appraisal record judged; None when the raw package was judged
    audits_seq: Optional[int] = None


class BundleRecord(LedgerRecord):
    kind: Literal["bundle"] = "bundle"
    nid: Optional[str] = None  # legacy bundles have no nonce
    protocol_id: str
    response_sha256: str
    blob_sha256: str
    blob_bytes: int
    encoding: str = "json"
    golden_ts: str = ""
    targets: int = 0
    rawev_count: int
    rawev_sha256: str = ""
    signature: SignatureInfo
    nonce: Optional[SlotRef] = None
    assurance: AssuranceLevel
    freshness: Freshness = "post-hoc"
    tooling: Optional[ToolingRef] = None
    locators: List[Locator] = []


class RestoreRecord(LedgerRecord):
    kind: Literal["restore"] = "restore"
    mode: Literal["exact", "replay"]
    source_repo: str
    source_commit: str
    source_last_state_tx: int
    tx_count: int


RECORD_TYPES = {
    "nonce": NonceRecord,
    "evidence": EvidenceRecord,
    "verdict": VerdictRecord,
    "locator": LocatorRecord,
    "appraisal": AppraisalRecord,
    "bundle": BundleRecord,
    "restore": RestoreRecord,
}


def parse_record(data: dict) -> LedgerRecord:
    """Rebuild the typed record from its stored dict (unknown kinds stay generic)."""
    cls = RECORD_TYPES.get(data.get("kind", ""), LedgerRecord)
    return cls.model_validate(data)


def key_for(record: LedgerRecord) -> str:
    """The ledger key of a record (plan B.3 / I)."""
    k = record.kind
    if k in ("nonce", "evidence", "verdict"):
        return f"{k}/{record.nid}"
    if k in ("locator", "appraisal"):
        return f"{k}/{record.nid}/{record.seq}"  # type: ignore[attr-defined]
    if k == "bundle":
        if record.nid:
            return f"bundle/{record.nid}"
        return f"bundle/sha256:{record.blob_sha256}"  # type: ignore[attr-defined]
    if k == "restore":
        return f"restore/{record.created_at}"
    raise LedgerError(f"no key rule for record kind '{k}'")


# ── package inspection: identify and describe, never judge ───────────────────


class SlotSpan(BaseModel):
    """One event's output span in the flat RawEv list (DFS order, newest first).

    `companion` marks an appraiser event (a value of the session's
    ASP_Comps); `retained` marks the appraised evidence bytes an EXTEND
    companion keeps beneath its verdict (attributed to the measured ASP)."""

    asp: str
    plc: str = ""
    args: Dict[str, Any] = {}
    start: int
    count: int
    companion: bool = False
    retained: bool = False

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
                                  start=cursor[0], count=size, companion=is_companion))
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
    nonce: Optional[SlotRef] = None
    nid: Optional[str] = None
    signature: SignatureInfo
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

    nonces = [sp for sp in spans if sp.asp == NONCE_ASP
              and (nonce_targid is None or sp.asp_targid == nonce_targid)]
    nonce_ref: Optional[SlotRef] = None
    nid: Optional[str] = None
    if len(nonces) > 1:
        raise EvidenceLayoutError(f"{len(nonces)} nonce events in one package")
    if nonces:
        sp = nonces[0]
        if sp.count != 1:
            raise EvidenceLayoutError("nonce event does not occupy exactly one slot")
        nonce_ref = SlotRef(slot=sp.start, asp=sp.asp, asp_targid=sp.asp_targid)
        nid = sha256_hex(raw[sp.start])

    sigs = [sp for sp in spans if sp.asp in SIG_ASPS]
    if sigs:
        sp = sigs[0]
        signature = SignatureInfo(present=True, slot=sp.start, asp=sp.asp)
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
        nid=nid,
        signature=signature,
        assurance=assurance,
    )


def derive_nid(payload: list, session: dict) -> str:
    """The run's nonce id, or EvidenceLayoutError when the package has no nonce."""
    desc = describe_package(payload, session)
    if desc.nid is None:
        raise EvidenceLayoutError("package carries no generate_nonce event")
    return desc.nid


def assurance_at_least(level: str, minimum: str) -> bool:
    return ASSURANCE_RANK.get(level, -1) >= ASSURANCE_RANK.get(minimum, 99)


# ── configuration ────────────────────────────────────────────────────────────


def _read_secret(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


class ToolingConfig(BaseModel):
    protocol_id: Optional[str] = "attestation_tools"
    measure: Literal["at_provisioning", "every_episode", "every_run"] = "at_provisioning"


class LedgerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 3322
    db: str = "pybb"
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
    # where provisioning bundles live (<golden_root>/_bundles/<pid>/); the
    # attestation_tools blessing is read from here (B.8)
    golden_root: str = Field(default_factory=lambda: os.environ.get("PYBB_GOLDEN_ROOT", "golden"))
    fail_open: bool = False
    min_assurance: AssuranceLevel = "signed+nonce"
    assurance_exceptions: Dict[str, str] = {}  # protocol_id -> reason
    tooling: ToolingConfig = ToolingConfig()
    appraiser_id: Optional[str] = None  # None: load or create under state_dir


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


class RunRecords(BaseModel):
    nonce: NonceRecord
    evidence: EvidenceRecord
    verdict: VerdictRecord
    appraisals: List[AppraisalRecord] = []
    appraiser_nonces: List[NonceRecord] = []
    locators: List[LocatorRecord] = []


class Ledger(ABC):
    """The ledger interface (plan section A). Every write is append-only."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def get_record(self, key: str) -> Optional[LedgerRecord]: ...

    @abstractmethod
    def _write_batch(self, records: List[LedgerRecord]) -> Receipt: ...

    @abstractmethod
    def history(self) -> Iterator[Tuple[int, str, LedgerRecord]]:
        """Every (tx, key, record) in transaction order."""

    def journal(self, since_tx: int = 0) -> Iterator[dict]:
        """Journal lines (plan H.1/I.9) for txs after `since_tx`, in order:
        `{tx, ts, db, keys: {key: content_sha256}}`. Backends override
        when they can do it in fewer reads."""
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

    # -- run commit -----------------------------------------------------------

    def commit_run(self, nonce: NonceRecord, appraiser_nonce: NonceRecord,
                   evidence: EvidenceRecord, appraisal: AppraisalRecord,
                   verdict: VerdictRecord,
                   extra: Optional[List[LocatorRecord]] = None) -> Receipt:
        """One batch per run (plan B.3/B.4); refuses a nonce already held.
        `extra` carries the local locator records for the appraisal and
        components blobs, written in the same batch."""
        nid = nonce.nid
        if nonce.role != "measurement":
            raise LedgerError("commit_run: the run nonce must have role 'measurement'")
        if not (evidence.nid == verdict.nid == appraisal.nid == nid):
            raise LedgerError("commit_run: records disagree on nid")
        if appraiser_nonce.role != "appraisal" or appraiser_nonce.for_nid != nid:
            raise LedgerError("commit_run: appraiser nonce must have role 'appraisal' for this nid")
        if appraisal.anid != appraiser_nonce.nid or appraisal.seq != 1 or appraisal.mode != "live":
            raise LedgerError("commit_run: appraisal must be the live seq-1 record for the appraiser nonce")
        if evidence.nonce.slot < 0:
            raise LedgerError("commit_run: evidence record has no nonce slot")
        for n in (nonce, appraiser_nonce):
            if self.exists(key_for(n)):
                raise DuplicateNonceError(f"duplicate nonce {n.nid}")
        for loc in extra or []:
            if loc.nid != nid:
                raise LedgerError("commit_run: locator record for another nid")
        return self._write_batch([nonce, appraiser_nonce, evidence, appraisal, verdict, *(extra or [])])

    def append_appraisal(self, appraisal: AppraisalRecord,
                         appraiser_nonce: NonceRecord,
                         extra: Optional[List[LocatorRecord]] = None) -> Receipt:
        """A later audit (plan B.5): next seq for the run, new appraiser nonce,
        plus the local locator record for the archived audit package."""
        if appraisal.mode != "audit":
            raise LedgerError("append_appraisal is for audit appraisals")
        if not self.exists(f"evidence/{appraisal.nid}") and not self.exists(f"bundle/{appraisal.nid}"):
            raise LedgerError(f"no run or bundle {appraisal.nid} to audit")
        if self.exists(key_for(appraisal)):
            raise LedgerError(f"appraisal seq {appraisal.seq} already recorded for {appraisal.nid}")
        if appraiser_nonce.nid != appraisal.anid or appraiser_nonce.for_nid != appraisal.nid:
            raise LedgerError("appraiser nonce does not match the appraisal")
        if self.exists(key_for(appraiser_nonce)):
            raise DuplicateNonceError(f"duplicate nonce {appraiser_nonce.nid}")
        for loc in extra or []:
            if loc.nid != appraisal.nid or self.exists(key_for(loc)):
                raise LedgerError("append_appraisal: bad or duplicate locator record")
        return self._write_batch([appraiser_nonce, appraisal, *(extra or [])])

    def append_locator(self, locator: LocatorRecord) -> Receipt:
        if self.exists(key_for(locator)):
            raise LedgerError(f"locator seq {locator.seq} already recorded for {locator.nid}")
        return self._write_batch([locator])

    def commit_bundle(self, bundle: BundleRecord) -> Receipt:
        key = key_for(bundle)
        if self.exists(key):
            if bundle.nid:
                raise DuplicateNonceError(f"duplicate nonce {bundle.nid}")
            raise LedgerError(f"bundle {key} already recorded")
        return self._write_batch([bundle])

    def commit_restore(self, restore: RestoreRecord) -> Receipt:
        return self._write_batch([restore])

    # -- reads ----------------------------------------------------------------

    def exists_nid(self, nid: str) -> bool:
        return self.exists(f"nonce/{nid}")

    def get(self, nid: str) -> RunRecords:
        nonce = self.get_record(f"nonce/{nid}")
        evidence = self.get_record(f"evidence/{nid}")
        verdict = self.get_record(f"verdict/{nid}")
        if not (isinstance(nonce, NonceRecord) and isinstance(evidence, EvidenceRecord)
                and isinstance(verdict, VerdictRecord)):
            raise LedgerError(f"run {nid} is not (fully) in the ledger")
        appraisals: List[AppraisalRecord] = []
        appraiser_nonces: List[NonceRecord] = []
        locators: List[LocatorRecord] = []
        for _tx, key, rec in self.history():
            if isinstance(rec, AppraisalRecord) and rec.nid == nid:
                appraisals.append(rec)
                an = self.get_record(f"nonce/{rec.anid}")
                if isinstance(an, NonceRecord):
                    appraiser_nonces.append(an)
            elif isinstance(rec, LocatorRecord) and rec.nid == nid:
                locators.append(rec)
        return RunRecords(nonce=nonce, evidence=evidence, verdict=verdict,
                          appraisals=appraisals, appraiser_nonces=appraiser_nonces,
                          locators=locators)

    def records(self, kind: Optional[str] = None,
                protocol_id: Optional[str] = None) -> Iterator[LedgerRecord]:
        for _tx, _key, rec in self.history():
            if kind and rec.kind != kind:
                continue
            if protocol_id and getattr(rec, "protocol_id", None) != protocol_id:
                continue
            yield rec


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
