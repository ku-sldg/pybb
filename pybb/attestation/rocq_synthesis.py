"""
Rocq proof / implementation synthesis — the goal-directed workflow's
workers for the Rocq ecosystem, mirroring the Lean layer in synthesis.py
on top of the same BlackBoxRepairKS shell and the same trust story:
engines are untrusted senses, bare rocq/dune runs judge locally for
free, and a restart is spent only on a locally-clean state so the
attested episode (build + assumptions audit) is what re-establishes
standing.

What the Rocq toolchain changes:

  - candidates are INNER TACTIC SCRIPTS (the text between `Proof.` and
    `Qed.`), spliced by `splice_proof_rocq` with the statement preserved
    byte-identically through the `Proof.` line;
  - the local judge is the kernel's assumptions audit, not a diagnostic
    stream: a candidate is accepted iff `dune build` is clean AND the
    audit compiles AND the goal's own Print Assumptions section is
    closed AND no section that was closed before is failing now (the
    baseline guard) — `Admitted.` elaborates cleanly, so a green build
    alone accepts nothing;
  - "unimplemented" and "unprovable" are the same kernel judgment: the
    impl-first stub is `Definition <impl> ... : T. Proof. Admitted.` —
    a well-formed declaration whose body is an axiom. The goals are
    then genuinely unprovable (the audit refuses to close over an
    opaque, admitted constant), and the implementation rung's local
    sense is its own Print Assumptions of the impl constant (a scratch
    audit file), closed iff the implementation is real.
"""

from __future__ import annotations

import subprocess
import re
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .proof_status import FAILING
from .rocq_status import (
    parse_audit_sections,
    parse_build_errors,
    rocq_audit_status,
    rocq_spec_conjuncts,
    statement_part_rocq,
)
from .synthesis import (
    BlackBoxRepairKS,
    GoalContext,
    ImplContext,
    LlmEngine,
    LlmImplEngine,
    RepairContext,
)
from .targetmap import rocq_decl_spans

_TERMINATOR = re.compile(r"^\s*(Qed|Admitted|Defined)\s*\.\s*$")


# ── splicing ──────────────────────────────────────────────────────────────────

def _strip_frame(candidate: str) -> str:
    """Strip a `Proof.` / `Qed.`|`Defined.` frame an engine (typically an
    LLM) wrapped around the inner script, preserving the script's own
    indentation. `Admitted.` is NOT stripped — it is a legal inner body
    (the stub) and doubles as the terminator."""
    lines = candidate.strip("\n").splitlines()
    if lines and lines[0].lstrip().startswith("Proof."):
        rest = lines[0].lstrip()[len("Proof."):].lstrip()
        lines = ([rest] if rest else []) + lines[1:]
    if lines:
        tail = lines[-1].rstrip()
        for frame in ("Qed.", "Defined."):
            if tail.endswith(frame) and tail.strip() != "Admitted.":
                tail = tail[:-len(frame)].rstrip()
                lines[-1] = tail
                if not tail.strip():
                    lines = lines[:-1]
                break
    return "\n".join(lines)


def splice_proof_rocq(text: str, name: str, candidate: str) -> str:
    """Replace `name`'s proof body (the lines between `Proof.` and the
    terminator) with `candidate`, an inner tactic script. The statement
    through the `Proof.` line is preserved byte-identically; the
    terminator is `Qed.` unless the candidate itself ends in
    `Admitted.`. Raises KeyError if the declaration is not found or has
    no `Proof.` block (term-style `:=` proofs are refused — there is no
    tactic script to replace)."""
    lines = text.splitlines()
    for _kind, decl, start, end in rocq_decl_spans(text):
        if decl != name:
            continue
        block = lines[start - 1:end]
        proof_at = next((i for i, l in enumerate(block)
                         if l.strip().startswith("Proof.")), None)
        if proof_at is None:
            term = " (term-style ':=' proof)" if \
                any(":=" in l for l in block) else ""
            raise KeyError(f"declaration '{name}' has no 'Proof.' block{term}")
        inner = _strip_frame(candidate)
        body = inner.splitlines()
        tail = [] if inner.rstrip().endswith("Admitted.") else ["Qed."]
        lines[start - 1:end] = [*block[:proof_at], "Proof.", *body, *tail]
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise KeyError(f"declaration '{name}' not found")


def splice_impl_rocq(text: str, name: str, term: str) -> str:
    """Replace `name`'s body with `:= term.`, keeping the signature.
    Accepts both the ordinary `:=` form and the impl-as-axiom stub form
    (`Definition <name> ... : T. Proof. Admitted.`). Raises KeyError if
    the declaration is not found or has no body to replace."""
    lines = text.splitlines()
    for _kind, decl, start, end in rocq_decl_spans(text):
        if decl != name:
            continue
        block = lines[start - 1:end]
        proof_at = next((i for i, l in enumerate(block)
                         if l.strip().startswith("Proof.")), None)
        if proof_at is not None:
            sig = "\n".join(block[:proof_at]).rstrip()
            if not sig.endswith("."):
                raise KeyError(f"'{name}': signature terminator not found")
            sig = sig[:-1].rstrip()
        else:
            blk = "\n".join(block)
            sig, sep, _ = blk.partition(":=")
            if not sep:
                raise KeyError(f"declaration '{name}' has no body to replace")
            sig = sig.rstrip()
        body = term.strip()
        if body.startswith(":="):
            body = body[2:].strip()
        if not body.endswith("."):
            body += "."
        sig_lines = sig.splitlines()
        sig_lines[-1] = sig_lines[-1] + " :="
        lines[start - 1:end] = [*sig_lines,
                                *["  " + l for l in body.splitlines()]]
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise KeyError(f"declaration '{name}' not found")


def stub_impl_axiom(text: str, name: str) -> str:
    """The impl-as-axiom stub: rewrite `name` from its `:=` form to
    `Definition <name> ... : T.` + `Proof. Admitted.` — a well-formed
    declaration whose body is an axiom ("unimplemented" and
    "unprovable" are the same kernel judgment)."""
    lines = text.splitlines()
    for _kind, decl, start, end in rocq_decl_spans(text):
        if decl != name:
            continue
        block = "\n".join(lines[start - 1:end])
        sig, sep, _ = block.partition(":=")
        if not sep:
            raise KeyError(f"declaration '{name}' has no ':=' body to stub")
        lines[start - 1:end] = [*(sig.rstrip() + ".").splitlines(),
                                "Proof.", "Admitted."]
        return "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    raise KeyError(f"declaration '{name}' not found")


# ── engines ───────────────────────────────────────────────────────────────────

class RocqTacticPortfolioEngine:
    """Deterministic candidate tactic scripts (INNER scripts — between
    `Proof.` and `Qed.`) over Rocq 9 Stdlib, tuned against the
    temp-control goals scenario (every committed goal is solvable by at
    least one candidate — enforced by the RUN_ROCQ headline test).
    Cheap shapes first; the Z.ltb destruction is name-agnostic (`repeat
    match goal`), so the shapes survive renamed variables and reshaped
    implementations that keep the boolean-guard style."""

    _GOAL_LTB = ("  repeat match goal with |- context [?a <? ?b] => "
                 "destruct (Z.ltb_spec a b) end;")
    _HYP_LTB = ("  repeat match goal with H : context [?a <? ?b] |- _ => "
                "destruct (Z.ltb_spec a b) end;")
    _CLOSERS = "  first [ reflexivity | discriminate | lia ]."
    _HYP_CLOSERS = ("  first [ assumption | left; assumption | "
                    "right; assumption | discriminate | lia ].")

    def __call__(self, ctx: GoalContext) -> Iterable[str]:
        if ctx.binding:
            if ctx.witnesses:
                nested = ctx.witnesses[-1]
                for w in reversed(ctx.witnesses[:-1]):
                    nested = f"(conj {w} {nested})"
                yield f"  exact {nested}."
            return
        helpers = list(ctx.helpers)
        impl = ctx.impl_name
        if ctx.prop:
            plain = ", ".join(n for n in (ctx.prop, impl) if n)
            full = ", ".join(n for n in (ctx.prop, *helpers, impl) if n)
            yield f"  unfold {plain}. intros.\n{self._GOAL_LTB}\n{self._CLOSERS}"
            if helpers:
                yield (f"  unfold {full}. intros.\n{self._GOAL_LTB}\n"
                       f"{self._CLOSERS}")
            # the hypothesis-side variant: safety-direction goals carry
            # the boolean guards in a hypothesis, not the goal
            yield (f"  unfold {full}. intros.\n{self._HYP_LTB}\n"
                   f"{self._HYP_CLOSERS}")
            yield (f"  unfold {full}. intros.\n{self._GOAL_LTB}\n"
                   f"{self._HYP_LTB}\n{self._CLOSERS}")
        else:
            if helpers:
                hs = ", ".join(helpers)
                yield f"  unfold {hs}. intros. lia."
                yield f"  unfold {hs} in *. intros. lia."
            yield "  intros. lia."


class RocqLlmEngine(LlmEngine):
    """The Lean LlmEngine with a Rocq prompt header and stub detection;
    the generator protocol (resume = the previous candidate was
    rejected, prompt carries the refuting feedback) is inherited."""

    @staticmethod
    def _is_stub(seed: str) -> bool:
        return "".join(seed.split()) in ("", "Admitted.", "Proof.Admitted.")

    def prompt(self, ctx: GoalContext, failed: list = None) -> str:
        lines = [
            "You are completing a proof for the Rocq Prover (Rocq 9, "
            "formerly Coq; Stdlib only — no external libraries). Reply "
            "with ONLY the tactic script that goes between `Proof.` and "
            "`Qed.`. No `Proof.`/`Qed.` frame, no explanations, no "
            "markdown fences.",
        ]
        for rel, contents in ctx.context_files.items():
            lines.append(f"Context — {rel}:\n```coq\n{contents}\n```")
        lines.append(f"Declaration to prove:\n{ctx.statement.strip()}")
        if ctx.blessed_statement:
            lines.append(
                f"The blessed goal property:\n{ctx.blessed_statement}")
        if ctx.detail:
            lines.append(f"Current failure: {ctx.detail}")
        if not self._is_stub(ctx.seed):
            lines.append(f"Previous attempt (may be wrong):\n{ctx.seed}")
        rejected = (ctx.rejections or
                    [{"candidate": c} for c in (failed or [])])
        for i, rej in enumerate(rejected[-4:], 1):
            lines.append(
                f"Rejected attempt {i} (failed to check — do not repeat "
                f"it):\n{rej['candidate']}")
            if rej.get("errors"):
                lines.append(f"Why it failed:\n{rej['errors']}")
        return "\n\n".join(lines)


class RocqLlmImplEngine(LlmImplEngine):
    """The Lean LlmImplEngine with a Rocq prompt header; candidates are
    untrusted exactly the same way — an implementation that builds has
    proved nothing until the goals close over it."""

    def prompt(self, ctx: ImplContext, failed: list = None) -> str:
        lines = [
            "You are writing an implementation for the Rocq Prover "
            "(Rocq 9, formerly Coq; Stdlib only — no external "
            "libraries). Reply with ONLY the term that replaces the "
            "text after `:=`. No explanations, no markdown fences, no "
            "restatement of the signature.",
        ]
        for rel, contents in ctx.context_files.items():
            lines.append(f"Context — {rel}:\n```coq\n{contents}\n```")
        lines.append(
            f"Declaration to implement:\n{ctx.signature.strip()} := ...")
        if ctx.blessed_statement:
            lines.append(
                "It must satisfy every one of these blessed properties "
                f"(they will be proved against it):\n{ctx.blessed_statement}")
        if ctx.detail:
            lines.append(f"Current failure: {ctx.detail}")
        rejected = (ctx.rejections or
                    [{"candidate": c} for c in (failed or [])])
        for i, rej in enumerate(rejected[-4:], 1):
            lines.append(
                f"Rejected attempt {i} (did not survive the kernel — do "
                f"not repeat it):\n{rej['candidate']}")
            if rej.get("errors"):
                lines.append(f"Why it failed:\n{rej['errors']}")
        return "\n\n".join(lines)


# ── the toolchain senses (untrusted, free) ────────────────────────────────────

class _RocqSenses:
    """Bare rocq/dune runs shared by both KS rungs. Untrusted by design:
    they gate restarts and reject candidates; the attested episode is
    the judge."""

    def _dune_build(self):
        return subprocess.run(
            [self.dune, "build"], cwd=self.package_root,
            capture_output=True, text=True)

    def _audit_run(self):
        return subprocess.run(
            [self.rocq, "compile",
             "-R", f"_build/default/{self.theory_name}", self.theory_name,
             self.audit_rel],
            cwd=self.package_root, capture_output=True, text=True)

    def _live_sections(self) -> Tuple[Optional[List[Optional[List[str]]]], str]:
        """(sections, error): sections is None when the tree cannot be
        audited (build failure, audit compile failure, section-count
        mismatch), with the refuting text in error."""
        build = self._dune_build()
        if build.returncode != 0:
            return None, build.stderr
        audit = self._audit_run()
        if audit.returncode != 0:
            return None, audit.stderr
        sections = parse_audit_sections(audit.stdout)
        if len(sections) != len(self.audit_goals):
            return None, (f"audit mismatch: {len(self.audit_goals)} goals "
                          f"but {len(sections)} sections")
        return sections, ""

    def _failing_goals(self, sections) -> Set[str]:
        return {g for g, s in zip(self.audit_goals, sections) if s is not None}

    @staticmethod
    def _render_stderr(stderr: str, limit: int = 3) -> str:
        errs = parse_build_errors(stderr)
        if not errs:
            text = " ".join(stderr.split())
            return f"- {text[:600]}" if text else "- failed without output"
        parts = [f"- {Path(p).name}:{ln}: {' '.join(m.split())[:600]}"
                 for p, ln, m in errs[:limit]]
        if len(errs) > limit:
            parts.append(f"- (+{len(errs) - limit} more)")
        return "\n".join(parts)


# ── the KS rungs ──────────────────────────────────────────────────────────────

class RocqImplSynthesisKS(BlackBoxRepairKS, _RocqSenses):
    """
    The impl-first rung for Rocq: fills an impl-as-axiom stub from the
    BLESSED STATEMENTS ALONE, then steps aside.

    The local sense is the kernel's own judgment: a scratch
    `Print Assumptions <impl>` audit — an admitted implementation is an
    axiom (open), a real one is closed. A candidate is kept iff the
    package builds AND that audit closes; whether it is the RIGHT
    implementation is decided downstream, by the goal proofs and the
    attested episode.
    """

    name: str = "synthesis:rocq-impl"
    max_attempts: int = 2
    restart_policy: str = "on_local_clean"
    engines: object = None        # list of engine callables (impl ladder)
    blessed: object = None        # callable() -> blessed model bytes (str)
    impl_rel: str = ""
    impl_name: str = ""
    spec_rel: str = ""
    theory_name: str = ""
    audit_rel: str = ""
    audit_goals: List[str] = []
    rocq: str = ""
    dune: str = ""

    def model_post_init(self, __context) -> None:
        self.tool = self._synthesize
        self.local_check = self._locally_clean

    def _impl_module(self) -> str:
        return ".".join(Path(self.impl_rel).with_suffix("").parts)

    def _impl_axioms(self) -> Optional[List[str]]:
        """The scratch audit: axioms beneath the impl constant (None =
        the audit could not run; [] = closed, implemented)."""
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "ImplAudit.v"
            f.write_text(f"Require Import {self._impl_module()}.\n"
                         f"Print Assumptions {self.impl_name}.\n")
            out = subprocess.run(
                [self.rocq, "compile",
                 "-R", f"_build/default/{self.theory_name}", self.theory_name,
                 str(f)],
                cwd=self.package_root, capture_output=True, text=True)
        if out.returncode != 0:
            return None
        sections = parse_audit_sections(out.stdout)
        if len(sections) != 1:
            return None
        return sections[0] or []

    def _locally_clean(self) -> bool:
        if self._dune_build().returncode != 0:
            return False
        axioms = self._impl_axioms()
        return axioms is not None and self.impl_name not in axioms

    def _synthesize(self, ctx: RepairContext) -> bool:
        impl_path = Path(self.package_root) / self.impl_rel
        build = self._dune_build()
        axioms = self._impl_axioms() if build.returncode == 0 else None
        if build.returncode == 0 and axioms is not None \
                and self.impl_name not in axioms:
            return False  # already implemented — hand off to the proof rung
        blessed_text = self.blessed()
        blessed_lines = blessed_text.splitlines()
        blessed_defs = {n: "\n".join(blessed_lines[s - 1:e])
                        for _k, n, s, e in rocq_decl_spans(blessed_text) if n}
        before = impl_path.read_text()
        lines = before.splitlines()
        spans = {n: (s, e) for _k, n, s, e in rocq_decl_spans(before) if n}
        if self.impl_name not in spans:
            return False  # nothing to fill; escalation's problem
        start, end = spans[self.impl_name]
        signature = statement_part_rocq("\n".join(lines[start - 1:end]))
        detail = (self._render_stderr(build.stderr)
                  if build.returncode != 0
                  else f"'{self.impl_name}' is an admitted axiom — "
                       "the goals cannot close over it")
        # the blessed statements ONLY — no proofs, no prior impl body
        context_files = {self.spec_rel: blessed_text} if self.spec_rel else {}
        ictx = ImplContext(
            name=self.impl_name, signature=signature,
            blessed_statement=blessed_defs.get("Spec", ""), detail=detail,
            context_files=context_files)
        for engine in (self.engines or []):
            for candidate in engine(ictx) or []:
                try:
                    impl_path.write_text(
                        splice_impl_rocq(before, self.impl_name, candidate))
                except KeyError:
                    continue
                build = self._dune_build()
                if build.returncode == 0:
                    axioms = self._impl_axioms()
                    if axioms is not None and self.impl_name not in axioms:
                        print(f"  {self.name}: '{self.impl_name}' implemented "
                              f"({type(engine).__name__})")
                        return True
                    errors = ("- the candidate still leaves "
                              f"'{self.impl_name}' an axiom")
                else:
                    errors = self._render_stderr(build.stderr)
                ictx.rejections.append({"candidate": candidate,
                                        "errors": errors})
                impl_path.write_text(before)
        return False


class RocqProofSynthesisKS(BlackBoxRepairKS, _RocqSenses):
    """
    The Rocq proof worker: engines over the audited goals, spliced as
    inner tactic scripts and locally judged by bare dune + the
    assumptions audit (untrusted, free); a restart is spent only when
    the whole audit is clean. Accepted progress is kept across attempts.

    A candidate for goal G is accepted iff the package builds, the
    audit compiles, G's own section is closed, and no section outside
    the pre-candidate failing set is failing now (the baseline guard —
    a "proof" that admits a neighbor to close its own goal is refused).
    """

    name: str = "synthesis:rocq-proofs"
    max_attempts: int = 2
    restart_policy: str = "on_local_clean"
    engines: object = None        # list of engine callables (the ladder)
    blessed: object = None        # callable() -> blessed model bytes (str)
    proofs_rel: str = ""
    theory_name: str = ""
    audit_rel: str = ""
    audit_goals: List[str] = []
    build_targ: str = ""
    audit_targ: str = ""
    binding_witness: str = "spec_holds"
    impl_name: str = ""
    rocq: str = ""
    dune: str = ""
    context_rels: List[str] = []  # source files handed to engines as
                                  # context (blessed statements + impl)

    def model_post_init(self, __context) -> None:
        self.tool = self._synthesize
        self.local_check = self._locally_clean

    def _locally_clean(self) -> bool:
        sections, _ = self._live_sections()
        return sections is not None and all(s is None for s in sections)

    def _live_failing(self) -> Set[str]:
        """Goals actually open RIGHT NOW — the verdict handed to the KS
        goes stale the moment a candidate is accepted (a restart is only
        spent once the whole audit is clean), so without this
        intersection the engines re-prove solved goals."""
        sections, err = self._live_sections()
        if sections is not None:
            return self._failing_goals(sections)
        # tree not auditable: attribute by build error position, else
        # keep every audited goal on the table
        proofs_path = Path(self.package_root) / self.proofs_rel
        try:
            text = proofs_path.read_text()
        except OSError:
            return set(self.audit_goals)
        spans = [(n, s, e) for _k, n, s, e in rocq_decl_spans(text) if n]
        names: Set[str] = set()
        for path, line, _msg in parse_build_errors(err):
            if Path(path).name != proofs_path.name:
                continue
            names.update(n for n, s, e in spans if s <= line <= e)
        return names or set(self.audit_goals)

    def _synthesize(self, ctx: RepairContext) -> bool:
        proofs_path = Path(self.package_root) / self.proofs_rel
        audit_file = Path(self.package_root) / self.audit_rel
        statuses = rocq_audit_status(
            ctx.verdict, self.build_targ, self.audit_targ, self.audit_goals,
            proofs_path, audit_file)
        failing = [n for n, st in statuses.items() if st.state == FAILING]
        if not failing:
            return False
        live = self._live_failing()
        already = [n for n in failing if n not in live]
        failing = [n for n in failing if n in live]
        if already:
            print(f"  {self.name}: {len(already)} already closed this "
                  f"episode, not re-attempted ({', '.join(sorted(already))})")
        if not failing:
            # the verdict is stale and nothing is left to prove: ask for a
            # fresh measurement rather than idling into escalation
            return self._locally_clean()
        blessed_text = self.blessed()
        conjuncts = rocq_spec_conjuncts(blessed_text)
        helpers = _rocq_prop_helpers(blessed_text, conjuncts)
        context_files: Dict[str, str] = {}
        for rel in self.context_rels:
            source = Path(self.package_root) / rel
            if source.is_file():
                context_files[rel] = source.read_text()
        blessed_lines = blessed_text.splitlines()
        blessed_defs = {n: "\n".join(blessed_lines[s - 1:e])
                        for _k, n, s, e in rocq_decl_spans(blessed_text) if n}

        def prop_of(statement: str) -> str:
            for prop in conjuncts:
                if re.search(rf"(?<![\w'.]){re.escape(prop)}(?![\w'])",
                             statement):
                    return prop
            return ""

        def scan() -> Dict[str, str]:
            text = proofs_path.read_text()
            lines = text.splitlines()
            return {n: "\n".join(lines[s - 1:e])
                    for _k, n, s, e in rocq_decl_spans(text) if n}

        decls = scan()

        def witnesses() -> List[str]:
            found = []
            for prop in conjuncts:
                hit = next(
                    (n for n, block in decls.items()
                     if n != self.binding_witness
                     and re.search(rf"(?<![\w'.]){re.escape(prop)}(?![\w'])",
                                   statement_part_rocq(block))), None)
                if hit:
                    found.append(hit)
            return found

        # audit order (dependencies first), the binding witness last:
        # its candidate cites the other witnesses
        order = {g: i for i, g in enumerate(self.audit_goals)}
        ordered = sorted(failing, key=lambda n: (n == self.binding_witness,
                                                 order.get(n, len(order)), n))
        acted = False
        for name in ordered:
            block = decls.get(name)
            if block is None:
                continue  # no such declaration live: escalation's problem
            statement = statement_part_rocq(block)
            prop = prop_of(statement)
            seed = _proof_body(block)
            gctx = GoalContext(
                name=name, statement=statement, seed=seed,
                detail=statuses[name].detail, prop=prop,
                blessed_statement=blessed_defs.get(prop, ""),
                binding=(name == self.binding_witness),
                witnesses=witnesses() if name == self.binding_witness else [],
                helpers=helpers, impl_name=self.impl_name,
                context_files=context_files)
            before = proofs_path.read_text()
            base_sections, _ = self._live_sections()
            baseline = (self._failing_goals(base_sections)
                        if base_sections is not None
                        else set(self.audit_goals))
            accepted = False
            for engine in (self.engines or []):
                for candidate in engine(gctx) or []:
                    try:
                        proofs_path.write_text(
                            splice_proof_rocq(before, name, candidate))
                    except KeyError:
                        continue
                    sections, err = self._live_sections()
                    if sections is None:
                        errors = self._render_stderr(err)
                    else:
                        failing_now = self._failing_goals(sections)
                        ok_self = name not in failing_now
                        if ok_self and failing_now <= (baseline - {name}):
                            accepted = True
                            acted = True
                            print(f"  {self.name}: '{name}' closed "
                                  f"({type(engine).__name__})")
                            break
                        if not ok_self:
                            idx = self.audit_goals.index(name) \
                                if name in self.audit_goals else -1
                            axioms = sections[idx] if idx >= 0 else None
                            errors = ("- the goal still depends on axioms: "
                                      + ", ".join(axioms or ["(unparsed)"]))
                        else:
                            broke = sorted(failing_now - baseline)
                            errors = ("- the candidate closed the goal but "
                                      "opened other sections: "
                                      + ", ".join(broke))
                    gctx.rejections.append({"candidate": candidate,
                                            "errors": errors})
                    proofs_path.write_text(before)
                if accepted:
                    break
            if accepted:
                decls = scan()
        return acted


def _proof_body(block: str) -> str:
    """The inner tactic script of a declaration block: the lines between
    `Proof.` and the terminator ('' when there is none)."""
    lines = block.splitlines()
    proof_at = next((i for i, l in enumerate(lines)
                     if l.strip().startswith("Proof.")), None)
    if proof_at is None:
        return ""
    inner = lines[proof_at:]
    inner[0] = inner[0].strip()[len("Proof."):].strip()
    if inner and _TERMINATOR.match(inner[-1]):
        inner = inner[:-1]
    return "\n".join(l for l in inner if l.strip())


def _rocq_prop_helpers(blessed_text: str, conjuncts: List[str]) -> List[str]:
    """Blessed Prop-valued helper definitions (e.g. SetPoint_valid):
    every Definition whose statement mentions ': Prop', minus the goal
    conjuncts and the Spec bundle itself."""
    helpers = []
    lines = blessed_text.splitlines()
    for kind, name, start, end in rocq_decl_spans(blessed_text):
        if kind != "Definition" or name in conjuncts or name == "Spec" \
                or not name:
            continue
        if ": Prop" in statement_part_rocq("\n".join(lines[start - 1:end])):
            helpers.append(name)
    return helpers
