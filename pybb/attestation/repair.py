"""
Repair on the routed blackboard: converge live targets back to gold.

Repair unit = measurement unit. `WholeFileRestoreKS` pairs with whole-file
hash tiers (temp_control_aadl_slang_l1a): it restores entire files — the only repair that
can return a whole-file hash to its golden value. `SliceRestoreKS` pairs
with block tiers (temp_control_aadl_slang_l1b): it splices only the violated BEGIN/END
block, mandatory in developer-owned files where everything around the
block is legitimately in motion.

Scope discipline: whole-file repair restores only files the refinement
tier (temp_control_aadl_slang_l2) confirmed violated — benign drift (l1a failed, every l2
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
from .synthesis import BlackBoxRepairKS, RepairContext


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
    refined_by: str = "temp_control_aadl_slang_l2"

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


def console_gate(work_order: str) -> bool:
    """The default operator gate: block on stdin until the operator says
    what happened out-of-band. 'r' (or bare Enter) claims the repair is
    done — the claim is worthless by design, it only buys the fresh
    measurement that judges it; 's' declines, so ordinary chain
    handoff/escalation follows. EOF (a non-interactive session with no
    piped answer) declines."""
    while True:
        try:
            answer = input(
                "  out-of-band repair done? [r]e-attest / [s]kip: ")
        except EOFError:
            print("  (stdin closed - skipping)")
            return False
        answer = answer.strip().lower()
        if answer in ("", "r", "re-attest"):
            return True
        if answer in ("s", "skip"):
            return False


class OutOfBandRepairKS(BlackBoxRepairKS):
    """
    The pause rung: a black-box repair whose tool is the world outside
    the process. It renders the failing verdict as a work order, then
    BLOCKS on an operator gate while the repair happens out-of-band —
    a hand edit, an interactive LLM code-agent session, anything.

    The trust story is the ordinary BlackBoxRepairKS one, verbatim: the
    operator's "done" is a claim, never trusted; only the restart's
    fresh measurement re-establishes standing, the always-run sentinels
    catch edits to blessed files, and max_attempts plus the controller's
    restart law bound the loop. Declining ('skip') returns the key to
    ordinary handoff/escalation.

    `gate(work_order) -> bool` is injectable (console prompt by
    default) — a gate that shells out to an agent with the work order
    is the scripted variant, and belongs behind an explicit arming
    flag exactly like --llm. `report() -> str` optionally appends live
    state (e.g. what a local sense says is still open) to each work
    order. restart_policy applies as usual: "per_attempt" re-attests
    every claimed repair; "on_local_clean" (with a local_check) gives
    the operator free local iterations before a restart is spent.

    A DECLINE IS FINAL: max_attempts budgets the repair loop (claim ->
    fresh measurement refutes -> ask again), but an operator who
    answered [s]kip has ruled — the remaining attempts auto-decline
    without re-prompting and the key falls through to escalation.
    """

    name: str = "repair:out-of-band"
    max_attempts: int = 3
    gate: object = None            # callable(work_order: str) -> bool
    report: object = None          # callable() -> str (live-state lines)
    declined: set = set()          # keys whose operator already ruled skip

    def model_post_init(self, __context) -> None:
        self.tool = self._await_repair

    def _work_order(self, ctx: RepairContext) -> str:
        # ctx.attempt is already 1-based when the rung runs (the
        # controller counts the attempt before execute)
        lines = [f"  {self.name}: '{ctx.key}' paused for out-of-band "
                 f"repair (attempt {ctx.attempt}/{self.max_attempts})"]
        verdict = ctx.verdict
        if isinstance(verdict, Verdict):
            for comp in verdict.failing():
                label = comp.targ_id or comp.description or comp.target_asp
                where = (comp.args or {}).get("filepath", "")
                lines.append(f"    - {label}"
                             + (f" [{where}]" if where else "")
                             + (f": {comp.reason}" if comp.reason else ""))
            if verdict.error:
                lines.append(f"    protocol error: {verdict.error}")
        if self.report is not None:
            extra = self.report()
            if extra:
                lines.extend("    " + l for l in extra.splitlines())
        lines.append("    nothing done out-of-band counts until fresh "
                     "measurement judges it")
        return "\n".join(lines)

    def _await_repair(self, ctx: RepairContext) -> bool:
        if ctx.key in self.declined:
            print(f"  {self.name}: '{ctx.key}' declined earlier — skipping")
            return False
        order = self._work_order(ctx)
        print(order)
        answer = bool((self.gate or console_gate)(order))
        if not answer:
            self.declined.add(ctx.key)
        return answer
