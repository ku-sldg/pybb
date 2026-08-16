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

import shutil
import subprocess
import re
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .proof_status import FAILING, PROVED, UNKNOWN, DeclStatus
from .rocq_status import (
    parse_audit_sections,
    parse_build_errors,
    rocq_audit_status,
    rocq_spec_conjuncts,
    statement_part_rocq,
)
from pydantic import BaseModel

from ..knowledge_source import KnowledgeSource
from .repair import OutOfBandRepairKS, SliceRestoreKS
from .synthesis import (
    BlackBoxRepairKS,
    GoalContext,
    ImplContext,
    LlmEngine,
    LlmImplEngine,
    RepairContext,
)
from .snapshot import mirror_path
from .targetmap import rocq_decl_spans

_TERMINATOR = re.compile(r"^\s*(Qed|Admitted|Defined)\s*\.\s*$")
_FILE_HEADER = re.compile(r"^\s*={3,}\s*FILE:\s*(\S+)\s*={3,}\s*$",
                          re.MULTILINE)


class PackageContext(BaseModel):
    """Everything a whole-package engine sees: the blessed statements,
    the current (stubbed) contents of both mutable files, and what the
    audit says is open. Deliberately blessed-first, like ImplContext:
    the goal properties are the specification; the file contents are
    skeletons (imports, statements) for the engine to fill."""

    impl_rel: str             # the implementation file to write
    proofs_rel: str           # the proofs file to write
    impl_name: str = ""       # the implementation the goals quantify over
    blessed_statement: str = ""   # the blessed Spec conjunction text
    context_files: Dict[str, str] = {}  # rel -> contents (blessed statements)
    files: Dict[str, str] = {}    # rel -> CURRENT contents of the two
                                  # mutable files (statement skeletons)
    audit_goals: List[str] = []   # every audited goal, audit order
    failing: List[str] = []       # goals currently open
    detail: str = ""              # why the tree currently fails
    rejections: List[Dict[str, str]] = []  # rejected candidates paired with
                                  # their refuting diagnostics (see
                                  # GoalContext.rejections)


def parse_file_blocks(text: str) -> Dict[str, str]:
    """Split an engine reply of `=== FILE: <rel> ===` headers into
    {rel: contents}. Markdown fences inside a block are stripped (LLMs
    add them despite instructions); text before the first header is
    ignored. Returns {} when no header is present."""
    matches = list(_FILE_HEADER.finditer(text))
    blocks: Dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = LlmEngine._strip_fences(text[m.end():end])
        blocks[m.group(1)] = body + "\n" if body else body
    return blocks


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


class RocqLlmPackageEngine:
    """The whole-package engine: ONE prompt asking for complete
    replacement contents of the implementation AND proofs files
    together, from the blessed properties. Candidates are
    {rel: contents} dicts, untrusted exactly like every other engine's —
    the package rung's local senses judge them and the attested episode
    is the final word.

    Same generator protocol as LlmEngine: the KS resumes the iterator
    only when the previous candidate was rejected, so each retry's
    prompt carries the accumulated rejections. A reply missing a file
    block is self-rejected here (with the parse failure as feedback)
    without costing the KS a judge run."""

    def __init__(self, complete=None, attempts: int = 1):
        self.complete = complete
        self.attempts = attempts

    def prompt(self, ctx: PackageContext, failed: list = None) -> str:
        lines = [
            "You are writing an implementation AND all of its proofs for "
            "the Rocq Prover (Rocq 9, formerly Coq; Stdlib only — no "
            "external libraries). Reply with the COMPLETE contents of "
            "both files below, each preceded by exactly one header line "
            "`=== FILE: <path> ===`. No explanations, no markdown fences, "
            "nothing outside the two blocks.",
        ]
        for rel, contents in ctx.context_files.items():
            lines.append(f"Context (blessed statements — do not restate "
                         f"or modify) — {rel}:\n```coq\n{contents}\n```")
        for rel in (ctx.impl_rel, ctx.proofs_rel):
            contents = ctx.files.get(rel, "")
            lines.append(f"File to write — {rel} (current contents; keep "
                         "the imports, every declaration name, and every "
                         "theorem statement exactly as given — replace "
                         f"only bodies and proof scripts):\n"
                         f"```coq\n{contents}\n```")
        if ctx.impl_name:
            lines.append(f"Implement '{ctx.impl_name}' (replace its "
                         "admitted body with a real term) and prove every "
                         "theorem over it.")
        if ctx.blessed_statement:
            lines.append("The implementation must satisfy every blessed "
                         f"property:\n{ctx.blessed_statement}")
        lines.append(
            "Every proof must end with `Qed.` — no `Admitted.`, no new "
            "`Axiom`/`Parameter`: each audited goal must come out 'Closed "
            "under the global context' under Print Assumptions."
            + (f"\nCurrently open goals: {', '.join(ctx.failing)}"
               if ctx.failing else ""))
        if ctx.detail:
            lines.append(f"Current failure: {ctx.detail}")
        rejected = (ctx.rejections or
                    [{"candidate": c} for c in (failed or [])])
        for i, rej in enumerate(rejected[-2:], 1):
            lines.append(
                f"Rejected attempt {i} (failed to check — do not repeat "
                f"it):\n{rej['candidate']}")
            if rej.get("errors"):
                lines.append(f"Why it failed:\n{rej['errors']}")
        return "\n\n".join(lines)

    def __call__(self, ctx: PackageContext) -> Iterable[Dict[str, str]]:
        if self.complete is None:
            return
        for _ in range(self.attempts):
            raw = LlmEngine._strip_fences(self.complete(self.prompt(ctx)) or "")
            if not raw:
                continue
            blocks = parse_file_blocks(raw)
            missing = [rel for rel in (ctx.impl_rel, ctx.proofs_rel)
                       if not blocks.get(rel, "").strip()]
            if missing:
                ctx.rejections.append({
                    "candidate": raw[:2000],
                    "errors": "- reply carried no `=== FILE: <path> ===` "
                              "block for: " + ", ".join(missing)})
                continue
            yield {rel: blocks[rel] for rel in (ctx.impl_rel, ctx.proofs_rel)}
            # resumed => the KS rejected this candidate (and appended the
            # refuting diagnostics to ctx.rejections)


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

    def _open_detail(self, sections) -> str:
        parts = []
        for goal, axioms in zip(self.audit_goals, sections):
            if axioms is None:
                continue
            foreign = [a for a in axioms if a != goal]
            parts.append(f"- {goal} depends on axioms: {', '.join(foreign)}"
                         if foreign else f"- {goal}: uses Admitted")
        return "\n".join(parts)

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


class RocqPackageSynthesisKS(BlackBoxRepairKS, _RocqSenses):
    """
    The whole-package rung: ONE black box generates the implementation
    and the proofs together, as complete replacement contents for both
    mutable files — the single-rung alternative to chaining
    RocqImplSynthesisKS ahead of RocqProofSynthesisKS.

    Engines are callables `engine(PackageContext) -> iterable of
    {rel: contents}` candidates. The trust story is unchanged — the
    engine owns the mutable files wholesale (statements, helper lemmas,
    everything), because nothing about those files was ever trusted on
    bytes: the always-run model/contracts sentinels catch any edit to
    blessed files, the blessed acceptance binding pins `spec_holds` to
    the blessed Spec type, and only the restarted episode's fresh
    measurement re-establishes standing.

    Acceptance is MONOTONE PROGRESS, judged by the local senses (bare
    dune + the assumptions audit, free): a candidate is kept iff the
    tree is auditable, no goal that was closed reopens, and the failing
    set strictly shrinks. Accepted trees are kept (the next candidate
    starts from them); rejected candidates are reverted and fed back to
    the engine with the refuting text. A restart is spent only when the
    whole audit is clean — attestation cost stays O(1) per accepted
    clean state, never O(candidates tried).
    """

    name: str = "synthesis:rocq-package"
    max_attempts: int = 2
    restart_policy: str = "on_local_clean"
    engines: object = None        # list of engine callables
    blessed: object = None        # callable() -> blessed model bytes (str)
    impl_rel: str = ""
    proofs_rel: str = ""
    impl_name: str = ""
    spec_rel: str = ""            # blessed statements file (engine context)
    theory_name: str = ""
    audit_rel: str = ""
    audit_goals: List[str] = []
    rocq: str = ""
    dune: str = ""

    def model_post_init(self, __context) -> None:
        self.tool = self._synthesize
        self.local_check = self._locally_clean

    def _locally_clean(self) -> bool:
        sections, _ = self._live_sections()
        return sections is not None and all(s is None for s in sections)

    def _synthesize(self, ctx: RepairContext) -> bool:
        impl_path = Path(self.package_root) / self.impl_rel
        proofs_path = Path(self.package_root) / self.proofs_rel
        sections, err = self._live_sections()
        if sections is not None:
            baseline = self._failing_goals(sections)
            if not baseline:
                # the verdict is stale and the tree is already clean:
                # ask for the fresh measurement rather than idling
                return True
            detail = self._open_detail(sections)
        else:
            baseline = set(self.audit_goals)
            detail = self._render_stderr(err)
        blessed_text = self.blessed()
        blessed_lines = blessed_text.splitlines()
        blessed_defs = {n: "\n".join(blessed_lines[s - 1:e])
                        for _k, n, s, e in rocq_decl_spans(blessed_text) if n}
        pctx = PackageContext(
            impl_rel=self.impl_rel, proofs_rel=self.proofs_rel,
            impl_name=self.impl_name,
            blessed_statement=blessed_defs.get("Spec", ""),
            context_files=({self.spec_rel: blessed_text}
                           if self.spec_rel else {}),
            files={self.impl_rel: impl_path.read_text(),
                   self.proofs_rel: proofs_path.read_text()},
            audit_goals=list(self.audit_goals),
            failing=sorted(baseline), detail=detail)
        acted = False
        for engine in (self.engines or []):
            for candidate in engine(pctx) or []:
                texts = {rel: candidate.get(rel)
                         for rel in (self.impl_rel, self.proofs_rel)}
                if not all(isinstance(t, str) and t.strip()
                           for t in texts.values()):
                    pctx.rejections.append({
                        "candidate": str(candidate)[:400],
                        "errors": "- candidate must map both file paths "
                                  "to non-empty contents"})
                    continue
                before = {impl_path: impl_path.read_text(),
                          proofs_path: proofs_path.read_text()}
                impl_path.write_text(texts[self.impl_rel])
                proofs_path.write_text(texts[self.proofs_rel])
                sections, err = self._live_sections()
                if sections is None:
                    errors = self._render_stderr(err)
                else:
                    failing_now = self._failing_goals(sections)
                    if failing_now < baseline:  # strict: shrinks, no reopen
                        acted = True
                        baseline = failing_now
                        pctx.failing = sorted(failing_now)
                        pctx.files = dict(texts)
                        closed = len(self.audit_goals) - len(failing_now)
                        print(f"  {self.name}: candidate accepted — "
                              f"{closed}/{len(self.audit_goals)} goals "
                              f"closed ({type(engine).__name__})")
                        if not failing_now:
                            return True
                        continue  # keep the tree; resume for the remainder
                    reopened = sorted(failing_now - baseline)
                    errors = ("- the candidate reopened previously-closed "
                              "goals: " + ", ".join(reopened) if reopened
                              else "- no progress:\n" +
                                   self._open_detail(sections))
                pctx.rejections.append({
                    "candidate": "\n".join(
                        f"=== FILE: {rel} ===\n{text}"
                        for rel, text in texts.items()),
                    "errors": errors})
                for path, text in before.items():
                    path.write_text(text)
        return acted


class RocqOutOfBandRepairKS(OutOfBandRepairKS, _RocqSenses):
    """
    The pause rung with the Rocq senses: the work order carries what the
    live audit says is still open (not just the stale verdict), and
    restart_policy defaults to "on_local_clean" with the audit as the
    gate — the operator (or an interactive agent session) iterates for
    free against bare dune + Print Assumptions, and a restart is spent
    only once the tree is locally clean. Claiming "repaired" while the
    audit is still dirty costs nothing but another look at the work
    order.
    """

    name: str = "repair:rocq-out-of-band"
    restart_policy: str = "on_local_clean"
    theory_name: str = ""
    audit_rel: str = ""
    audit_goals: List[str] = []
    rocq: str = ""
    dune: str = ""

    def model_post_init(self, __context) -> None:
        super().model_post_init(__context)  # installs the gate as tool
        self.local_check = self._locally_clean
        if self.report is None:
            self.report = self._live_report

    def _locally_clean(self) -> bool:
        sections, _ = self._live_sections()
        return sections is not None and all(s is None for s in sections)

    def _live_report(self) -> str:
        sections, err = self._live_sections()
        if sections is None:
            return "tree not auditable:\n" + self._render_stderr(err)
        detail = self._open_detail(sections)
        return ("still open (live audit):\n" + detail if detail
                else "audit locally clean — [r]e-attest spends a restart")


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


# ── isolation variants: per-goal verdicts from ONE proofs file ────────────────
#
# Rocq elaborates a file atomically and stops at the first error, so one
# broken proof in the monolithic proofs file destroys the audit's evidence
# for every goal in it (the checklist's build-failure `?` poisoning). Proof
# OPACITY is the escape: a proof consumes only the STATEMENTS of what it
# references, never their bodies — so goal k can be judged from a derived
# variant of the same file in which every other goal's proof body is
# `Admitted.` (statements byte-identical, order preserved). `Admitted.`
# compiles unconditionally, so the target's own body is the only possible
# failure point, and the kernel's `Print Assumptions` in the variant either
# certifies the target or NAMES the admitted siblings it leans on.
#
# The variants are DERIVED, never maintained: regenerated from the live
# file's bytes on demand (only when the full build has already failed),
# used for one judgment in a scratch copy of the package, and discarded —
# the same source-of-authority discipline as the blessed files' derived
# slices. This is a refinement of the checklist's derived view, not
# attested evidence: the full-tree build + audit measurement remains the
# authoritative system verdict.
#
# Helper lemmas (config `isolation_keep`) currently retain their REAL
# bodies in every variant, so a goal whose dependencies are healthy audits
# fully "Closed". Admitting the helpers too — degrading a broken helper
# into a named dependency instead of a variant-wide failure — is the
# documented follow-up.


def isolation_variant_text(text: str, target: str,
                           admit: Iterable[str]) -> str:
    """The isolation variant for `target`: every goal in `admit` except
    the target gets its proof body replaced by `Admitted.`; the target's
    body (and everything not named) is preserved byte-for-byte. Raises
    KeyError if an admit goal is missing from the file."""
    for other in admit:
        if other != target:
            text = splice_proof_rocq(text, other, "Admitted.")
    return text


def _isolated_status(target: str, axioms: Optional[List[str]],
                     admitted: Set[str]) -> DeclStatus:
    """One audit section from the target's variant -> its cell."""
    if axioms is None:
        return DeclStatus(state=PROVED, detail="isolated: proof intact")
    if not axioms:
        return DeclStatus(state=UNKNOWN,
                          detail="isolated: unparsed audit section")
    foreign = [a for a in axioms if a not in admitted and a != target]
    if target in axioms:
        detail = "isolated: uses Admitted"
        if foreign:
            detail += f"; depends on: {', '.join(foreign)}"
        return DeclStatus(state=FAILING, detail=detail)
    if foreign:
        label = "axioms" if len(foreign) > 1 else "axiom"
        return DeclStatus(state=FAILING,
                          detail=f"isolated: depends on {label}: "
                                 f"{', '.join(foreign)}")
    sibs = [a for a in axioms if a in admitted]
    return DeclStatus(state=PROVED,
                      detail="isolated: script intact; assumes "
                             f"{', '.join(sibs)} (judged separately)")


def make_isolation_status(package_root: Path, theory_name: str,
                          audit_goals: List[str], admit_goals: List[str],
                          witness_rel: str, audit_rel: str,
                          rocq: str, dune: str, timeout: float = 300.0):
    """An `isolate` callable for the checklist's build-failure fallback
    (rocq_audit_status/rocq_goal_checklist `isolate=`): judge every audit
    goal from its isolation variant in a scratch copy of the package.
    Returns goal -> DeclStatus, or None when the refinement itself is
    unavailable (fail-closed: the caller keeps the coarse fallback)."""
    package_root = Path(package_root)

    def isolate() -> Optional[Dict[str, DeclStatus]]:
        try:
            return _run(tempfile.mkdtemp(prefix="rocq_isolation_"))
        except Exception as exc:  # fail-closed to the coarse fallback
            print(f"  (isolation refinement unavailable: {exc})")
            return None

    def _run(workdir: str) -> Dict[str, DeclStatus]:
        scratch = Path(workdir) / package_root.name
        shutil.copytree(package_root, scratch,
                        ignore=shutil.ignore_patterns("_build", ".lia.cache",
                                                      ".git"))
        live_text = (package_root / witness_rel).read_text()
        audit_header = [
            l for l in (package_root / audit_rel).read_text().splitlines()
            if not re.match(r"\s*Print Assumptions\b", l)]
        witness_name = Path(witness_rel).name
        admitted = set(admit_goals)
        out: Dict[str, DeclStatus] = {}
        for target in audit_goals:
            variant = isolation_variant_text(live_text, target, admit_goals)
            (scratch / witness_rel).write_text(variant)
            try:
                build = subprocess.run(
                    [dune, "build"], cwd=scratch, capture_output=True,
                    text=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                out[target] = DeclStatus(state=UNKNOWN,
                                         detail="isolated: build timed out")
                continue
            if build.returncode != 0:
                out[target] = _variant_failure(target, variant, witness_name,
                                               build.stderr)
                continue
            check = scratch / f"IsolationCheck_{target}.v"
            check.write_text("\n".join(
                [*audit_header, f"Print Assumptions {target}."]) + "\n")
            try:
                audit = subprocess.run(
                    [rocq, "compile", "-R", f"_build/default/{theory_name}",
                     theory_name, check.name],
                    cwd=scratch, capture_output=True, text=True,
                    timeout=timeout)
            except subprocess.TimeoutExpired:
                out[target] = DeclStatus(state=UNKNOWN,
                                         detail="isolated: audit timed out")
                continue
            if audit.returncode != 0:
                out[target] = DeclStatus(
                    state=UNKNOWN, detail="isolated: audit failed: "
                    + (audit.stderr.strip().splitlines()[-1]
                       if audit.stderr.strip() else "no diagnostic"))
                continue
            sections = parse_audit_sections(audit.stdout)
            if len(sections) != 1:
                out[target] = DeclStatus(
                    state=UNKNOWN, detail=f"isolated: expected one audit "
                    f"section, got {len(sections)}")
                continue
            out[target] = _isolated_status(target, sections[0], admitted)
        shutil.rmtree(workdir, ignore_errors=True)
        return out

    def _variant_failure(target: str, variant: str, witness_name: str,
                         stderr: str) -> DeclStatus:
        spans = [(n, s, e) for _k, n, s, e in rocq_decl_spans(variant) if n]
        for path, line, msg in parse_build_errors(stderr):
            if Path(path).name != witness_name:
                continue
            hit = next((n for n, s, e in spans if s <= line <= e), None)
            if hit == target:
                first = msg.strip().splitlines()[0] if msg.strip() else ""
                return DeclStatus(state=FAILING,
                                  detail=f"isolated: {first or 'build error'}")
        first = next((f"{Path(p).name}:{ln}: {m.strip().splitlines()[0]}"
                      for p, ln, m in parse_build_errors(stderr) if m.strip()),
                     "no diagnostic")
        return DeclStatus(state=UNKNOWN,
                          detail="isolated: build failed outside the "
                                 f"target's proof ({first})")

    return isolate


# ── derived-artifact repair: the audit file is a RENDERING of config ──────────

class AuditRegenerateKS(KnowledgeSource):
    """
    The third repair species — neither restore-from-golden nor
    synthesis: REGENERATION FROM CONFIGURATION. The assumptions audit
    file is the rendering of AM config (audit_goals); a coverage tamper
    (a deleted or reordered `Print Assumptions` line) fails the
    appraiser's section count closed, and the honest repair is to
    re-render the file from the config that defines it. Header lines
    (comments, Requires) are preserved; the Print block is replaced by
    the canonical one-line-per-goal block in audit order.

    Declines when the file is already canonical — then the failure was
    not a coverage drift, and the chain hands off (escalation follows
    unless a later rung claims the key). Like every repair, the
    regeneration is judged by fresh measurement, never by its own claim.
    """

    name: str = "repair:audit-regenerate"
    partition: List[str] = []
    max_attempts: int = 1
    package_root: str
    audit_rel: str
    audit_goals: List[str] = []

    def execute(self, blackboard, keys) -> None:
        path = Path(self.package_root) / self.audit_rel
        text = path.read_text()
        header = [l for l in text.splitlines()
                  if not re.match(r"\s*Print Assumptions\b", l)]
        while header and not header[-1].strip():
            header.pop()
        canonical = "\n".join(
            [*header, "",
             *(f"Print Assumptions {g}." for g in self.audit_goals)]) + "\n"
        if canonical == text:
            print(f"  {self.name}: audit coverage already canonical — "
                  "nothing to regenerate")
            return
        path.write_text(canonical)
        print(f"  {self.name}: regenerated {self.audit_rel} from config "
              f"({len(self.audit_goals)} Print Assumptions, audit order)")
        for key in keys:
            entry = blackboard.get_entry(key)
            blackboard.write_entry(key=key, predicate=entry.predicate,
                                   measurement=entry.measurement, result=None)


# ── deterministic implementation candidates from the blessed statements ───────

class RocqSpecGuidedImplEngine:
    """
    Deterministic implementation candidates derived from the BLESSED
    statements ALONE — the keyless counterpart of the tactic portfolio,
    tuned to the guarded-step prop class (every committed scenario's
    Spec is derivable; pinned by test). Each conjunct of the blessed
    Spec whose statement has the shape

        forall <binders>, H1 -> ... -> Hn -> f x y z = C

    contributes a branch: a hypothesis `a < b` becomes the boolean
    guard `a <? b` (Z.ltb — the seed proofs bridge the gap with
    Z.ltb_spec); hypotheses that are not strict comparisons (validity
    preconditions like SetPoint_valid) narrow the PROPERTY, not the
    computation, and are ignored. A conjunct concluding
    `f x y z = <last-binder>` is the default branch; conjuncts whose
    conclusion is not an f-equation (safety implications) contribute
    nothing. A conclusion wrapped in a BLESSED helper relation whose
    own body is an f-equation (e.g. `commands f x y z C` with
    `commands ... := f x y z = C`) is resolved by one beta step —
    the engine follows the blessed definitions, so a restated spec
    (a sanctioned mid-demo blessing) derives the same implementation.
    Candidates: branches in Spec order, then reversed. The engine only
    proposes — the kernel (build + audit over the live proofs) judges
    every candidate.
    """

    _BINDER = re.compile(r"\(([\w\s]+?)\s*:\s*[\w.]+\)")

    @classmethod
    def _binder_names(cls, text: str) -> List[str]:
        """Flattened binder names — `(l c : FanCmd)` binds both."""
        return [n for m in cls._BINDER.finditer(text)
                for n in m.group(1).split()]

    def __call__(self, ctx: ImplContext) -> Iterable[str]:
        spec_text = next(iter(ctx.context_files.values()), "")
        impl_binders = self._binder_names(ctx.signature)
        if not spec_text or not impl_binders:
            return
        lines = spec_text.splitlines()
        spans = {n: (s, e) for _k, n, s, e in rocq_decl_spans(spec_text) if n}
        helpers = self._helper_equations(spec_text, lines, spans)
        branches, default = [], None
        for prop in rocq_spec_conjuncts(spec_text):
            if prop not in spans:
                continue
            s, e = spans[prop]
            parsed = self._parse_prop("\n".join(lines[s - 1:e]), impl_binders,
                                      helpers)
            if parsed is None:
                continue
            guards, rhs, is_default = parsed
            if is_default:
                default = default or rhs
            elif guards:
                branches.append((guards, rhs))
        if not branches or default is None:
            return

        def render(ordered):
            out = []
            for i, (guards, ctor) in enumerate(ordered):
                kw = "if" if i == 0 else "else if"
                out.append(f"{kw} {' && '.join(guards)} then {ctor}")
            out.append(f"else {default}")
            return "\n".join(out)

        yield render(branches)
        if len(branches) > 1:
            yield render(list(reversed(branches)))

    def _helper_equations(self, spec_text, lines, spans):
        """Blessed helper relations whose body is a bare equation:
        name -> (binder names, (lhs-head, lhs-args, rhs))."""
        helpers = {}
        for _k, name, s, e in rocq_decl_spans(spec_text):
            if not name:
                continue
            head, sep, body = "\n".join(lines[s - 1:e]).partition(":=")
            if not sep:
                continue
            eq = re.fullmatch(r"(\w+)((?:\s+\w+)+)\s*=\s*(\w+)",
                              body.strip().rstrip(".").replace("\n", " "))
            if eq is None:
                continue
            helpers[name] = (self._binder_names(head),
                             (eq.group(1), eq.group(2).split(), eq.group(3)))
        return helpers

    def _parse_prop(self, block: str, impl_binders: List[str],
                    helpers=None):
        head, sep, body = block.partition(":=")
        if not sep:
            return None
        body = body.strip().rstrip(".")
        m = re.match(r"forall\s+((?:\([^)]*\)\s*)+),\s*(.*)", body, re.S)
        if m is None:
            return None
        prop_binders = self._binder_names(head)
        fvar = prop_binders[0] if prop_binders else "f"
        segs = [s.strip().replace("\n", " ") for s in m.group(2).split("->")]
        conclusion = segs[-1]
        app = re.fullmatch(r"(\w+)((?:\s+\w+)+)", conclusion)
        if app is not None and (helpers or {}).get(app.group(1)) is not None:
            # one beta step through the blessed helper relation
            binders, (lhs_head, lhs_args, brhs) = helpers[app.group(1)]
            actual = app.group(2).split()
            if len(actual) == len(binders):
                sub = dict(zip(binders, actual))
                conclusion = (" ".join([sub.get(lhs_head, lhs_head),
                                        *(sub.get(a, a) for a in lhs_args)])
                              + " = " + sub.get(brhs, brhs))
        eq = re.fullmatch(rf"{re.escape(fvar)}((?:\s+\w+)+)\s*=\s*(\w+)",
                          conclusion)
        if eq is None:
            return None
        args = eq.group(1).split()
        rhs = eq.group(2)
        if len(args) != len(impl_binders):
            return None
        rename = dict(zip(args, impl_binders))

        def rn(text: str) -> str:
            return re.sub(r"\b(\w+)\b",
                          lambda mm: rename.get(mm.group(1), mm.group(1)),
                          text)

        if rhs in args and rename[rhs] == impl_binders[-1]:
            return ([], impl_binders[-1], True)
        guards = [f"{rn(cm.group(1).strip())} <? {rn(cm.group(2).strip())}"
                  for hyp in segs[:-1]
                  if (cm := re.fullmatch(r"([\w ]+?)\s*<\s*([\w ]+)",
                                         hyp)) is not None]
        return (guards, rhs, False)


# ── declaration-anchored slice restore ────────────────────────────────────────

class RocqSliceRestoreKS(SliceRestoreKS):
    """
    Slice restore for declaration-named Rocq contract slices: locate the
    violated DECLARATION BY NAME (the slice's `metadata` tail) in both
    the live file and its golden copy via the comment-aware syntax scan,
    and splice only that declaration's lines. Position-independent — an
    insertion elsewhere in the file moves the declaration, not the
    repair — and scope-disciplined: everything outside the violated
    declaration (benign drift included) is left untouched. Falls back to
    the marker-based splice for components without a named declaration.
    """

    name: str = "repair:slice"

    def _splice(self, args: dict) -> bool:
        meta = args.get("metadata") or ""
        filepath = args.get("filepath")
        if "::" not in meta or not filepath:
            return super()._splice(args)
        name = meta.rsplit("::", 1)[-1]
        live = Path(filepath)
        golden_copy = mirror_path(self.golden_root, live)
        if not (live.is_file() and golden_copy.is_file()):
            return False
        live_text = live.read_text()
        gold_text = golden_copy.read_text()
        live_span = next(((s, e) for _k, n, s, e in rocq_decl_spans(live_text)
                          if n == name), None)
        gold_span = next(((s, e) for _k, n, s, e in rocq_decl_spans(gold_text)
                          if n == name), None)
        if live_span is None or gold_span is None:
            return False
        live_lines = live_text.splitlines(keepends=True)
        gold_lines = gold_text.splitlines(keepends=True)
        live_lines[live_span[0] - 1:live_span[1]] = \
            gold_lines[gold_span[0] - 1:gold_span[1]]
        live.write_text("".join(live_lines))
        return True
