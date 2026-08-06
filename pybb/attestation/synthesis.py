"""
Synthesis / black-box repair knowledge sources — the goal-directed
workflow's workers (step 4).

Two layers:

**BlackBoxRepairKS** (ecosystem-agnostic): wraps an OPAQUE external
repair tool — e.g. AutoVerus for Verus/Rust proof repair — as a chain
rung. The tool gets a RepairContext (the entry's failing Verdict with
per-component reasons and retained measured output, the working file
set) and may mutate the working files however it likes; its claim of
success is worthless by design. Re-appraisal between repair attempts is
the BLACKBOARD'S: the KS requests a restart (per attempt, or only when
an optional untrusted local check passes), the fresh episode re-measures,
and the tool's next attempt sees the new failure context. A black box
needs ZERO trust: repair cannot mint trust — the fresh measurement
judges whatever it did, and the always-run model/contracts sentinels
catch even a rogue edit to blessed files.

**ProofSynthesisKS** (the Lean specialization): a BlackBoxRepairKS whose
tool is an ENGINE LADDER over the goals checklist. Engines are plain
callables `engine(GoalContext) -> iterable of candidate proof texts`;
the KS splices candidates into the mutable proofs file (statement kept,
proof replaced), judges each with a bare `lake lean` run (untrusted
senses — free iteration, per the step-3 commitments), keeps accepted
progress, and requests a restart only when the proofs file and the
acceptance binding are locally clean — attestation cost is O(1) per
accepted state, never O(candidates tried).

Bounds: KS max_attempts, RestartEpisodeKS budgets, and the controller's
max_restarts_per_key stay the halting law; end-of-route escalation is
the human rung, carrying the checklist of exactly what remains.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource
from .proof_status import FAILING, decl_status, parse_diagnostics, spec_conjuncts
from .targetmap import lean_decl_spans


# ── layer 1: the ecosystem-agnostic black-box shell ───────────────────────────

class RepairContext(BaseModel):
    """What an opaque repair tool is handed: attribution, not trust."""

    key: str                 # the blackboard entry under repair
    verdict: Any             # the failing Verdict: components (reasons,
                             # retained measured_b64 output), evidence_ref
    files: List[str] = []    # the working file set the tool may touch
    package_root: str = ""
    attempt: int = 0         # this KS's attempt count on the key (episode-local)


class BlackBoxRepairKS(KnowledgeSource):
    """
    A chain rung wrapping an opaque repair tool.

    tool(RepairContext) -> bool: may mutate the working files arbitrarily;
    returns whether it acted (a claim, never trusted). local_check() ->
    bool is an optional untrusted gate deciding whether an attempt is
    worth a restart. restart_policy:

      "per_attempt"    — every acted-upon attempt is re-appraised by a
                         fresh episode (opaque/self-checking tools; the
                         attested run IS the check)
      "on_local_clean" — spend a restart only when local_check passes
                         (cheap-check ecosystems)

    Either way the blackboard machinery does the re-appraisal: restart →
    fresh measurement → fresh verdict → the next attempt's context.
    """

    name: str = ""
    partition: List[str] = []
    max_attempts: int = 3
    tool: object = None            # callable(RepairContext) -> bool
    local_check: object = None     # callable() -> bool | None
    restart_policy: str = "per_attempt"
    files: List[str] = []
    package_root: str = ""

    def model_post_init(self, __context) -> None:
        if not self.name:
            self.name = "repair:black-box"

    def execute(self, blackboard: Blackboard, keys: List[str]) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            ctx = RepairContext(
                key=key, verdict=entry.result, files=list(self.files),
                package_root=str(self.package_root),
                attempt=entry.ks_history.get(self.name, 0))
            if not self.tool(ctx):
                continue  # nothing tried; handoff/escalation follows
            if self.restart_policy == "per_attempt":
                blackboard.request_restart(key, f"{self.name}: re-appraise")
            elif self.local_check is None or self.local_check():
                blackboard.request_restart(key, f"{self.name}: locally clean")


# ── layer 2: Lean proof synthesis ─────────────────────────────────────────────

class GoalContext(BaseModel):
    """Everything an engine sees for one failing declaration."""

    name: str                 # the declaration to prove
    statement: str            # its statement part (before :=)
    seed: str = ""            # its current proof text (guidance, mutable)
    detail: str = ""          # failure detail from the verdict's diagnostics
    prop: str = ""            # the blessed goal property it witnesses ("" = none)
    blessed_statement: str = ""  # the prop's blessed definition text
    binding: bool = False     # the spec_holds obligation binding
    witnesses: List[str] = [] # binding: the goal witnesses, checklist order
    helpers: List[str] = []   # blessed Prop-valued helper defs (e.g. .valid)
    impl_name: str = ""


class TacticPortfolioEngine:
    """Deterministic candidate tactic scripts over core Lean, tuned
    against the goals scenario (every committed goal is solvable by at
    least one candidate — enforced by test). Cheap shapes first."""

    _VARS = "a b c d e"

    def __call__(self, ctx: GoalContext) -> Iterable[str]:
        if ctx.binding:
            if ctx.witnesses:
                names = ", ".join(ctx.witnesses)
                yield ("by\n  unfold Spec\n  exact ⟨" + names + "⟩")
            return
        helpers = " ".join(ctx.helpers)
        impl = ctx.impl_name
        if ctx.prop:
            targets = f"{ctx.prop} {impl}".strip()
            yield f"by\n  unfold {targets}\n  intros\n  split <;> simp_all <;> omega"
            if helpers:
                yield (f"by\n  unfold {ctx.prop} {helpers} {impl}\n  intros\n"
                       "  split <;> simp_all <;> omega")
            for arity in (3, 2, 4, 1):
                intro = " ".join(self._VARS.split()[:arity])
                yield (f"by\n  unfold {targets}\n  intro {intro}\n"
                       "  split <;> intro h <;> first\n"
                       "    | (split at h <;> simp_all)\n"
                       "    | simp_all")
            yield f"by\n  unfold {ctx.prop}\n  intros\n  simp_all [{impl}] <;> omega"
        else:
            if helpers:
                yield f"by\n  unfold {helpers} at *\n  intros\n  omega"
                yield f"by\n  unfold {helpers} at *\n  intros\n  simp_all <;> omega"
            yield "by\n  intros\n  simp_all <;> omega"
        yield "by\n  decide"


class LlmEngine:
    """The pluggable LLM slot: builds a prompt from the goal context
    (blessed statement, diagnostics, the seed proof as guidance) and
    calls `complete(prompt) -> str` for candidate proofs. Ships with no
    backend (complete=None yields nothing); candidates are judged
    exactly like any other engine's — the LLM is an untrusted sense."""

    def __init__(self, complete=None, attempts: int = 1):
        self.complete = complete
        self.attempts = attempts

    def prompt(self, ctx: GoalContext) -> str:
        lines = [
            "Complete this Lean 4 proof. Reply with ONLY the proof term "
            "or tactic block (the text after `:=`).",
            f"Declaration to prove:\n{ctx.statement.strip()} := ...",
        ]
        if ctx.blessed_statement:
            lines.append(f"The blessed goal property:\n{ctx.blessed_statement}")
        if ctx.detail:
            lines.append(f"Current failure: {ctx.detail}")
        if ctx.seed.strip():
            lines.append(f"Previous attempt (may be wrong):\n{ctx.seed}")
        return "\n\n".join(lines)

    def __call__(self, ctx: GoalContext) -> Iterable[str]:
        if self.complete is None:
            return
        for _ in range(self.attempts):
            candidate = self.complete(self.prompt(ctx))
            if candidate and candidate.strip():
                yield candidate.strip()


def splice_proof(text: str, name: str, candidate: str) -> str:
    """Replace `name`'s proof with `candidate`, keeping the statement
    (everything before the declaration's first `:=`). Raises KeyError
    if the declaration is not found or has no proof separator."""
    lines = text.splitlines()
    for kind, decl, start, end in lean_decl_spans(text):
        if decl != name:
            continue
        block = "\n".join(lines[start - 1:end])
        stmt, sep, _ = block.partition(":=")
        if not sep:
            raise KeyError(f"declaration '{name}' has no ':=' separator")
        lines[start - 1:end] = (stmt.rstrip() + " := " + candidate).splitlines()
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise KeyError(f"declaration '{name}' not found")


def _statement_part(block: str) -> str:
    return block.partition(":=")[0]


def _prop_helpers(blessed_text: str, conjuncts: List[str]) -> List[str]:
    """Blessed Prop-valued helper defs (e.g. SetPoint.valid): every def
    whose statement mentions ': Prop', minus the goal conjuncts and the
    Spec bundle itself."""
    helpers = []
    lines = blessed_text.splitlines()
    for kind, name, start, end in lean_decl_spans(blessed_text):
        if kind != "def" or name in conjuncts or name == "Spec" or not name:
            continue
        if ": Prop" in _statement_part("\n".join(lines[start - 1:end])):
            helpers.append(name)
    return helpers


class ProofSynthesisKS(BlackBoxRepairKS):
    """
    The Lean worker: engines over the goals checklist, spliced and
    locally judged with bare `lake lean` (untrusted, free), restart
    requested only when the proofs file AND the acceptance binding are
    locally clean. Accepted progress is kept across attempts — a
    half-proved file is progress, not failure.
    """

    name: str = "synthesis:proofs"
    max_attempts: int = 2
    restart_policy: str = "on_local_clean"
    engines: object = None        # list of engine callables (the ladder)
    blessed: object = None        # callable() -> blessed model bytes (str)
    proofs_rel: str = ""
    acceptance_rel: str = ""
    proofs_targ: str = ""
    binding_witness: str = "spec_holds"
    impl_name: str = ""
    lake: str = ""

    def model_post_init(self, __context) -> None:
        self.tool = self._synthesize
        self.local_check = self._locally_clean

    # bare-tool senses (untrusted; trust arrives via the restart's episode)
    def _refuting(self, rel: str) -> List[dict]:
        out = subprocess.run(
            [self.lake, "lean", rel, "--", "--json"],
            cwd=self.package_root, capture_output=True, text=True)
        return [d for d in parse_diagnostics(out.stdout.encode())
                if d.get("severity") == "error" or d.get("kind") == "hasSorry"]

    def _locally_clean(self) -> bool:
        return not self._refuting(self.proofs_rel) \
            and not self._refuting(self.acceptance_rel)

    def _decl_refutations(self, rel: str, name: str):
        """(refutations inside `name`'s span, total refutation count)."""
        text = (Path(self.package_root) / rel).read_text()
        spans = {n: (s, e) for _k, n, s, e in lean_decl_spans(text) if n}
        bad = self._refuting(rel)
        if name not in spans:
            return bad, len(bad)
        s, e = spans[name]
        return [d for d in bad
                if s <= (d.get("pos") or {}).get("line", 0) <= e], len(bad)

    def _synthesize(self, ctx: RepairContext) -> bool:
        proofs_path = Path(self.package_root) / self.proofs_rel
        statuses = decl_status(ctx.verdict, self.proofs_targ, proofs_path)
        failing = [n for n, st in statuses.items() if st.state == FAILING]
        if not failing:
            return False
        blessed_text = self.blessed()
        conjuncts = spec_conjuncts(blessed_text)
        helpers = _prop_helpers(blessed_text, conjuncts)
        blessed_lines = blessed_text.splitlines()
        blessed_defs = {n: "\n".join(blessed_lines[s - 1:e])
                        for _k, n, s, e in lean_decl_spans(blessed_text) if n}

        def prop_of(statement: str) -> str:
            for prop in conjuncts:
                if re.search(rf"(?<![\w'.]){re.escape(prop)}(?![\w'])",
                             statement):
                    return prop
            return ""

        text = proofs_path.read_text()
        lines = text.splitlines()
        decls = {n: "\n".join(lines[s - 1:e])
                 for _k, n, s, e in lean_decl_spans(text) if n}

        def witnesses() -> List[str]:
            found = []
            for prop in conjuncts:
                hit = next((n for n, block in decls.items()
                            if n != self.binding_witness
                            and re.search(rf"(?<![\w'.]){re.escape(prop)}(?![\w'])",
                                          _statement_part(block))), None)
                if hit:
                    found.append(hit)
            return found

        # the binding last: its candidate cites the other witnesses
        ordered = sorted(failing, key=lambda n: n == self.binding_witness)
        acted = False
        for name in ordered:
            block = decls.get(name)
            if block is None:
                continue  # anonymous declarations: escalation's problem
            statement = _statement_part(block)
            prop = prop_of(statement)
            gctx = GoalContext(
                name=name, statement=statement,
                seed=block.partition(":=")[2],
                detail=statuses[name].detail, prop=prop,
                blessed_statement=blessed_defs.get(prop, ""),
                binding=(name == self.binding_witness),
                witnesses=witnesses() if name == self.binding_witness else [],
                helpers=helpers, impl_name=self.impl_name)
            before = proofs_path.read_text()
            _, baseline_total = self._decl_refutations(self.proofs_rel, name)
            accepted = False
            for engine in (self.engines or []):
                for candidate in engine(gctx) or []:
                    proofs_path.write_text(
                        splice_proof(before, name, candidate))
                    mine, total = self._decl_refutations(self.proofs_rel, name)
                    # accept iff this declaration is clean AND nothing else
                    # broke (no new refutations elsewhere)
                    if not mine and total <= baseline_total:
                        accepted = True
                        acted = True
                        print(f"  {self.name}: '{name}' proved "
                              f"({type(engine).__name__})")
                        break
                    proofs_path.write_text(before)
                if accepted:
                    break
            if accepted:
                text = proofs_path.read_text()
                lines = text.splitlines()
                decls = {n: "\n".join(lines[s - 1:e])
                         for _k, n, s, e in lean_decl_spans(text) if n}
        return acted
