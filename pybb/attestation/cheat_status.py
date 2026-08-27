"""Per-crate proof-escape checklist for the cheat tier.

The cheat tier's appraiser (goldenbytes_appr) is a REPLACE appraiser, so
its verdict carries the pass/fail per crate but NOT the live construct
counts (no retained measured slot, unlike the verus tier). This module
renders the ✓/✗ grid from the authoritative verdict, and for a refuted
crate annotates *which* proof-escape construct drifted by re-scanning
the crate's sources with the same counting rules as the
`cheat_scan_verus` ASP and diffing against the target's golden count
map. The ✗/✓ is the appraiser's; the annotation is explanatory.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Dict

from .proof_status import (
    FAILING,
    PROVED,
    UNKNOWN,
    Checklist,
    ChecklistRow,
    DeclStatus,
)

# constructs the cheat scan counts, in report order; external_body is a
# nested {bridge,component,other} map in the golden — we compare its sum
_SCALARS = ("assume", "admit", "axiom", "broadcast", "uninterp",
            "assume_specification", "external")


def _is_word(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


def _count_word(text: str, word: str, call_only: bool) -> int:
    """Whole-word occurrences of `word`; call_only additionally requires
    the next non-space char to be '(' (mirrors cheat_scan_verus)."""
    n, start = 0, 0
    while (pos := text.find(word, start)) != -1:
        end = pos + len(word)
        left_ok = pos == 0 or not _is_word(text[pos - 1])
        right_ok = end == len(text) or not _is_word(text[end])
        call_ok = not call_only or text[end:].lstrip().startswith("(")
        if left_ok and right_ok and call_ok:
            n += 1
        start = pos + max(len(word), 1)
    return n


def _count_sub(text: str, needle: str) -> int:
    n, start = 0, 0
    while (pos := text.find(needle, start)) != -1:
        n += 1
        start = pos + len(needle)
    return n


def _scan_counts(crate_dir: str) -> Dict[str, int]:
    """Live construct counts over crate_dir/**/*.rs, matching the ASP's
    scan_text for the constructs we annotate."""
    text_all = []
    root = Path(crate_dir)
    if root.is_dir():
        for p in sorted(root.rglob("*.rs")):
            try:
                text_all.append(p.read_text())
            except OSError:
                pass
    text = "\n".join(text_all)
    return {
        "assume": _count_word(text, "assume", True),
        "admit": _count_word(text, "admit", True),
        "external_body": _count_sub(text, "external_body"),
        "assume_specification": _count_sub(text, "assume_specification"),
        "axiom": _count_word(text, "axiom", False),
        "broadcast": _count_word(text, "broadcast", False),
        "uninterp": _count_word(text, "uninterp", False),
        "external": _count_bare_external(text),
    }


def _count_bare_external(text: str) -> int:
    """`verifier::external` not followed by a word char (excludes
    external_body / external_fn_specification); mirrors the ASP."""
    n, start, needle = 0, 0, "verifier::external"
    while (pos := text.find(needle, start)) != -1:
        end = pos + len(needle)
        if end == len(text) or not _is_word(text[end]):
            n += 1
        start = end
    return n


def _golden_flat(golden_b64: str) -> Dict[str, int]:
    """Flatten a golden cheat count map to scalars (external_body summed)."""
    try:
        g = json.loads(base64.b64decode(golden_b64))
    except Exception:
        return {}
    out = {}
    for k in ("assume", "admit", "axiom", "broadcast", "uninterp",
              "assume_specification", "external"):
        v = g.get(k, 0)
        out[k] = v if isinstance(v, int) else 0
    eb = g.get("external_body", 0)
    out["external_body"] = (sum(eb.values()) if isinstance(eb, dict)
                            else (eb if isinstance(eb, int) else 0))
    return out


def _drift(crate_dir: str, golden_b64: str) -> str:
    """Human annotation of which constructs moved: 'assume 0 → 1'."""
    live = _scan_counts(crate_dir)
    gold = _golden_flat(golden_b64)
    parts = []
    for k in ("assume", "admit", "axiom", "broadcast", "uninterp",
              "assume_specification", "external_body", "external"):
        g, l = gold.get(k, 0), live.get(k, 0)
        if g != l:
            parts.append(f"{k} {g} → {l}")
    return ", ".join(parts)


def _crate_of(args: dict) -> str:
    return (args.get("crate_dir") or "").rstrip("/").rsplit("/", 1)[-1] or "?"


def cheat_crate_checklist(verdict, cheat_targets: Dict[str, dict]) -> Checklist:
    """One row per scanned crate: ✓/✗ from the cheat verdict; a refuted
    row is annotated with the drifted proof-escape construct(s)."""
    rows = []
    for targ, args in sorted(cheat_targets.items(),
                             key=lambda kv: _crate_of(kv[1])):
        crate = _crate_of(args)
        if verdict.error:
            status = DeclStatus(state=UNKNOWN,
                                detail=f"scan failed: {verdict.error}")
        else:
            comp = next((c for c in verdict.components if c.targ_id == targ),
                        None)
            if comp is None:
                status = DeclStatus(state=UNKNOWN,
                                    detail=f"no component {targ}")
            elif comp.passed:
                status = DeclStatus(state=PROVED, detail="no proof escape")
            else:
                drift = _drift(args.get("crate_dir", ""),
                               args.get("golden_b64", ""))
                status = DeclStatus(
                    state=FAILING,
                    detail=(f"proof escape: {drift}" if drift
                            else "proof-escape count drifted from golden"))
        rows.append(ChecklistRow(label=crate, status=status))
    return Checklist(rows=rows)
