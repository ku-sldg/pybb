"""
Schema v1 records (`pybb-ledger/v1`), kept read-only so v1 databases and
mirrors stay readable: `parse_record` in `ledger.py` dispatches here on the
record's `schema` field, and `as_bundle` projects one v1 run (nonce,
evidence, verdict, appraisal records) into the v2 `bundle` view. Nothing
writes v1 records anymore. Design history: docs/ledger_plan.md, sections
I (v1) and K (v2).
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ledger_common import (
    AssuranceLevel,
    Freshness,
    LedgerError,
    canonical_json,
    sha256_hex,
    utc_now,
)

SCHEMA_V1 = "pybb-ledger/v1"


class LedgerRecord(BaseModel):
    """v1 common envelope. Unknown fields are preserved, never dropped."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: str = Field(default=SCHEMA_V1, alias="schema")
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




def parse_record_v1(data: dict) -> LedgerRecord:
    cls = RECORD_TYPES.get(data.get("kind", ""), LedgerRecord)
    return cls.model_validate(data)
