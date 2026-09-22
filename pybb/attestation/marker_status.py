"""
Per-crate contract slice integrity — the l1b marker tier's progress
grid, derived from measured evidence.

The l1b tier measures every codegen-managed `BEGIN/END MARKER` contract
block (readfile_marker_range, appraised against a signed golden). The
verus grid judges OUTCOMES (does the pair prove?) and cannot see a
contract that was weakened together with its implementation; this grid
judges the contract BYTES against the blessed model's rendering. One
row per contract-bearing crate — the worst of its marker blocks —
rendered with the same downgrade-only guardrails as the other grids:

  - a crate is only ever marked intact under every block's PASS;
  - fail-closed: a protocol error or a missing component downgrades
    to UNKNOWN, never up to intact;
  - the ROWS come from the AM-owned l1b fixture (marker targets
    derived from the attestation report at provisioning), never from
    a live scan of the tree.
"""

from __future__ import annotations

from typing import Dict, List

from .proof_status import (
    FAILING,
    PROVED,
    UNKNOWN,
    Checklist,
    ChecklistRow,
    DeclStatus,
)


def _crate_of(args: dict) -> str:
    """The crate a readfile_marker_range target measures: the path
    segment after `crates/` (targets are one-per-block, filepath under
    the crate's src tree)."""
    parts = (args.get("filepath") or "").split("/")
    if "crates" in parts:
        i = parts.index("crates")
        if i + 1 < len(parts):
            return parts[i + 1]
    return "?"


def _block_of(args: dict) -> str:
    return (args.get("begin_marker") or "?").removeprefix("BEGIN MARKER ").strip()


def marker_crate_checklist(verdict, marker_targets: Dict[str, dict]) -> Checklist:
    """One row per crate: ✓ when every one of its marker blocks matched
    its golden, ✗ naming the drifted block(s), ? when the tier could not
    judge."""
    by_crate: Dict[str, List[tuple]] = {}
    for targ, args in marker_targets.items():
        by_crate.setdefault(_crate_of(args), []).append((targ, _block_of(args)))

    rows = []
    for crate in sorted(by_crate):
        blocks = sorted(by_crate[crate], key=lambda tb: tb[1])
        if verdict.error:
            status = DeclStatus(state=UNKNOWN,
                                detail=f"protocol run failed: {verdict.error}")
        else:
            drifted, missing = [], []
            for targ, block in blocks:
                comp = next((c for c in verdict.components
                             if c.targ_id == targ), None)
                if comp is None:
                    missing.append(block)
                elif not comp.passed:
                    drifted.append(block)
            if drifted:
                status = DeclStatus(
                    state=FAILING,
                    detail=f"{', '.join(drifted)} drifted from golden")
            elif missing:
                status = DeclStatus(
                    state=UNKNOWN,
                    detail=f"no component for {', '.join(missing)}")
            else:
                status = DeclStatus(
                    state=PROVED,
                    detail=f"{len(blocks)} contract block(s) intact")
        rows.append(ChecklistRow(label=crate, status=status))
    return Checklist(rows=rows)
