"""Constants, canonical form and errors shared by the ledger modules."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Literal

GENESIS = "0" * 64

AssuranceLevel = Literal["signed+nonce", "signed", "nonce", "none"]
ASSURANCE_RANK: Dict[str, int] = {"none": 0, "nonce": 1, "signed": 2, "signed+nonce": 3}
Freshness = Literal["post-hoc", "pre-registered", "none"]

NONCE_ASP = "generate_nonce"
NONCE_TARGID = "nonce_targ"
APPRAISER_NONCE_TARGID = "appraiser_nonce_targ"
SIG_ASPS = ("sig", "sig_tpm")


def canonical_json(obj: Any) -> bytes:
    """The stored form of every record: sorted keys, no whitespace, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class LedgerError(RuntimeError):
    """Base class for ledger failures."""


class DuplicateNonceError(LedgerError):
    """A bundle id the ledger already holds: a replayed or duplicated package."""


class LedgerIntegrityError(LedgerError):
    """The stored ledger does not verify (broken chain, altered value)."""


class EvidenceLayoutError(LedgerError):
    """A package's evidence type cannot be laid out against its session."""


def assurance_at_least(level: str, minimum: str) -> bool:
    return ASSURANCE_RANK.get(level, -1) >= ASSURANCE_RANK.get(minimum, 99)
