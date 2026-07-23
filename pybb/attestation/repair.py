"""
Repair on the routed blackboard: converge live targets back to gold.

Repair unit = measurement unit. `WholeFileRestoreKS` pairs with whole-file
hash tiers (gumbo_l1a): it restores entire files — the only repair that
can return a whole-file hash to its golden value. `SliceRestoreKS` pairs
with block tiers (gumbo_l1b): it splices only the violated BEGIN/END
block, mandatory in developer-owned files where everything around the
block is legitimately in motion.

Scope discipline: whole-file repair restores only files the refinement
tier (gumbo_l2) confirmed violated — benign drift (l1a failed, every l2
slice passed) is never repaired. Tolerated drift is blessed by
re-provisioning, not laundered by repair.

Repair cannot mint trust: a repair rung acts, exhausts its single
attempt, and the entry escalates carrying the repair in its ks_history —
rendered by trust_summary as "repaired from golden — verification pending
next episode". Fresh evidence comes from the next workflow run (fresh
predicates re-attest everything). Both KSs read gold and write live — the
one permitted direction — and never raise: unrestorable components are
left for the escalation report.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource
from .knowledge_sources import Verdict
from .snapshot import mirror_path


def _latest_verdict(blackboard: Blackboard, key: str, protocol: str) -> Optional[Verdict]:
    """Most recent Verdict for key rendered by the named protocol."""
    for hist_key, entry in reversed(blackboard.get_history()):
        if hist_key == key and isinstance(entry.result, Verdict) \
                and entry.result.protocol == protocol:
            return entry.result
    return None


def _failing_filepaths(verdict: Verdict) -> List[str]:
    return [c.args["filepath"] for c in verdict.failing() if c.args.get("filepath")]


class WholeFileRestoreKS(KnowledgeSource):
    """
    Whole-file repair rung for a whole-file hash tier, placed after the
    refinement rung on the fail chain. Restores from golden exactly the
    files the refinement tier confirmed violated (>=1 failing slice);
    falls back to every failing file of the entry's own verdict when no
    refinement verdict exists in history.
    """

    name: str = "repair:whole-file"
    partition: List[str] = []
    max_attempts: int = 1
    golden_root: Path
    refined_by: str = "gumbo_l2"

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if not isinstance(entry.result, Verdict):
                continue
            refine = _latest_verdict(blackboard, key, self.refined_by)
            # NB: `refine if refine else ...` would be wrong — Verdict
            # truthiness is the appraisal outcome, and the refinement
            # verdict is failing precisely when repair has work to do
            targets = _failing_filepaths(entry.result if refine is None else refine)
            restored, unrestorable = [], []
            for filepath in sorted(set(targets)):
                try:
                    golden_copy = mirror_path(self.golden_root, Path(filepath))
                    if not golden_copy.is_file():
                        unrestorable.append(filepath)
                        continue
                    shutil.copy2(golden_copy, filepath)
                    restored.append(filepath)
                except OSError:
                    unrestorable.append(filepath)
            print(f"  {self.name}: restored {len(restored)} file(s) from golden"
                  + (f", {len(unrestorable)} unrestorable" if unrestorable else ""))
            blackboard.write_entry(
                key=key, predicate=entry.predicate,
                measurement=entry.measurement, result=None,
            )


def _marker_span(lines: List[str], begin: str, end: str) -> Optional[Tuple[int, int]]:
    b = next((i for i, line in enumerate(lines) if begin in line), None)
    if b is None:
        return None
    e = next((i for i in range(b + 1, len(lines)) if end in lines[i]), None)
    if e is None:
        return None
    return b, e


class SliceRestoreKS(KnowledgeSource):
    """
    Block repair rung for a marker-range tier: splice each violated
    BEGIN/END block from the golden copy into the live file, touching
    nothing outside the block. Components without markers (or with markers
    missing from either file) are left unrestorable for the report.
    """

    name: str = "repair:slice"
    partition: List[str] = []
    max_attempts: int = 1
    golden_root: Path

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            if not isinstance(entry.result, Verdict):
                continue
            restored, unrestorable = [], []
            for comp in entry.result.failing():
                label = comp.targ_id or comp.description
                try:
                    if self._splice(comp.args):
                        restored.append(label)
                    else:
                        unrestorable.append(label)
                except OSError:
                    unrestorable.append(label)
            print(f"  {self.name}: restored {len(restored)} block(s) from golden"
                  + (f", {len(unrestorable)} unrestorable" if unrestorable else ""))
            blackboard.write_entry(
                key=key, predicate=entry.predicate,
                measurement=entry.measurement, result=None,
            )

    def _splice(self, args: dict) -> bool:
        filepath = args.get("filepath")
        begin, end = args.get("begin_marker"), args.get("end_marker")
        if not (filepath and begin and end):
            return False
        live = Path(filepath)
        golden_copy = mirror_path(self.golden_root, live)
        if not (live.is_file() and golden_copy.is_file()):
            return False
        live_lines = live.read_text().splitlines(keepends=True)
        gold_lines = golden_copy.read_text().splitlines(keepends=True)
        live_span = _marker_span(live_lines, begin, end)
        gold_span = _marker_span(gold_lines, begin, end)
        if live_span is None or gold_span is None:
            return False
        live_lines[live_span[0]:live_span[1] + 1] = \
            gold_lines[gold_span[0]:gold_span[1] + 1]
        live.write_text("".join(live_lines))
        return True
