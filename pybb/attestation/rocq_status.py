"""
Per-goal proof status for the Rocq verification class — the Rocq
counterpart of proof_status.py, sharing its cell model (DeclStatus,
Checklist, render_checklist) and downgrade-only rules.

Where Lean's progress signal is a positional join (diagnostic line ->
declaration span), Rocq's is NOMINAL: the verification term retains the
assumptions audit's output ({status, stdout, stderr} JSON in
ComponentResult.measured_b64), and that output is one Print Assumptions
section per audited goal, in audit-file order — section k judges
audit_goals[k] by NAME. The derived view refines a failing verdict into
WHICH goals are refuted and WHY:

  - `Closed under the global context`    -> proved
  - `Axioms:` listing the goal itself    -> failing ("uses Admitted" —
    an admitted constant is its own axiom)
  - `Axioms:` listing another name       -> failing ("depends on
    axiom(s): ..." — the smuggled-postulate attribution)

Fail-closed tiers, in order of trust lost:

  - a failed tool:: hash or a protocol error poisons every cell (the
    retained output cannot be trusted);
  - a FAILED build target means the audit ran against an incomplete
    _build tree (dune removes the failed file's .vo, so the audit
    errors out or judges a tree that is gone): the build stderr's
    `File "...", line N` markers are mapped into the witness file's
    declaration spans (the fallback tier) and everything unmapped is
    UNKNOWN;
  - an audit COMPILE failure (nonzero status with the build green) is
    a missing witness: the failing `Print Assumptions <goal>.` line in
    the audit file names the goal; sections already printed keep their
    verdicts, goals after the stop are UNKNOWN;
  - a section-count mismatch is UNKNOWN everywhere (output the audit
    cannot account for);
  - checklist rows come from the blessed bytes (the signed Spec
    conjunction), never the live tree; witnesses are matched on the
    STATEMENT part only (a prop named inside a proof body is not a
    witness), and a witness outside the audited goal set is UNKNOWN,
    never presumed proved.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .proof_status import (
    FAILING,
    NO_WITNESS,
    PROVED,
    UNKNOWN,
    Checklist,
    ChecklistRow,
    DeclStatus,
    _SEVERITY,
    _first_line,
    _stale_detail,
    failed_tools,
    stale_files,
)
from .targetmap import rocq_decl_spans

CLOSED = "Closed under the global context"
AXIOMS = "Axioms:"


# ── parsing the toolchain's output shapes ─────────────────────────────────────

def parse_audit_sections(stdout: str) -> List[Optional[List[str]]]:
    """stdout of a Print Assumptions audit -> one entry per section:
    None (closed under the global context) or the list of axiom names.
    Mirrors run_command_rocq_appr's parser exactly — axiom entries are
    `name : type` lines, type continuations (indented) are skipped."""
    sections: List[Optional[List[str]]] = []
    for line in stdout.splitlines():
        trimmed = line.rstrip()
        if trimmed == CLOSED:
            sections.append(None)
        elif trimmed == AXIOMS:
            sections.append([])
        elif sections and sections[-1] is not None:
            if line[:1].isspace() or not line:
                continue
            name, sep, _ = trimmed.partition(":")
            if sep and name.strip():
                sections[-1].append(name.strip())
    return sections


_FILE_LINE = re.compile(r'^File "([^"]+)", line (\d+)')


def parse_build_errors(stderr: str) -> List[Tuple[str, int, str]]:
    """rocq/dune error output -> [(path, line, message)]. Errors arrive
    as `File "./X.v", line N, characters a-b:` followed by the message
    lines (which may wrap); everything until the next File marker is the
    message."""
    errors: List[list] = []
    for line in stderr.splitlines():
        m = _FILE_LINE.match(line)
        if m:
            errors.append([m.group(1), int(m.group(2)), ""])
        elif errors and line.strip():
            errors[-1][2] = (errors[-1][2] + " " + line.strip()).strip()
    return [tuple(e) for e in errors]


def command_evidence(comp) -> Optional[dict]:
    """The retained {status, stdout, stderr} JSON of a run_command_rocq /
    run_command_dune component, or None when absent/unparseable."""
    if not getattr(comp, "measured_b64", ""):
        return None
    try:
        blob = json.loads(base64.b64decode(comp.measured_b64))
    except (ValueError, TypeError):
        return None
    return blob if isinstance(blob, dict) else None


# ── the per-goal status join ──────────────────────────────────────────────────

def _all(goals: List[str], state: str, detail: str) -> Dict[str, DeclStatus]:
    return {g: DeclStatus(state=state, detail=detail) for g in goals}


def statement_part_rocq(block: str) -> str:
    """The statement of a Rocq declaration: everything before its
    `Proof.` line or, for term-style bodies, before the first `:=`.
    Witness matching must never see proof bodies."""
    out: List[str] = []
    for line in block.splitlines():
        if line.strip().startswith("Proof."):
            break
        if ":=" in line:
            out.append(line.partition(":=")[0])
            break
        out.append(line)
    return "\n".join(out)


def _section_status(goal: str, axioms: Optional[List[str]]) -> DeclStatus:
    if axioms is None:
        return DeclStatus(state=PROVED)
    if not axioms:
        return DeclStatus(state=FAILING, detail="depends on unparsed axioms")
    if goal in axioms:
        others = [a for a in axioms if a != goal]
        detail = "uses Admitted" + (
            f"; depends on axioms: {', '.join(others)}" if others else "")
        return DeclStatus(state=FAILING, detail=detail)
    label = "axioms" if len(axioms) > 1 else "axiom"
    return DeclStatus(state=FAILING,
                      detail=f"depends on {label}: {', '.join(axioms)}")


def _audit_print_lines(audit_file: Optional[Path]) -> Dict[str, int]:
    """goal -> 1-based line of its `Print Assumptions <goal>.` statement
    in the audit file ({} when the file is unavailable)."""
    if audit_file is None or not Path(audit_file).is_file():
        return {}
    lines = Path(audit_file).read_text().splitlines()
    out: Dict[str, int] = {}
    for i, line in enumerate(lines, 1):
        m = re.match(r"\s*Print Assumptions\s+([A-Za-z_][\w']*)\s*\.", line)
        if m:
            out[m.group(1)] = i
    return out


def rocq_audit_status(verdict, build_targ: str, audit_targ: str,
                      audit_goals: List[str], witness_file: Path,
                      audit_file: Optional[Path] = None,
                      isolate=None) -> Dict[str, DeclStatus]:
    """
    Per-goal status from the verification verdict's build + audit
    components, per the fail-closed tiers in the module docstring. Keys
    are the audited goal names; a failed build may add extra FAILING
    keys for witness-file declarations its stderr names.

    `isolate` (optional, callable() -> Dict[str, DeclStatus] | None)
    refines the build-failure fallback: per-goal verdicts from isolation
    variants of the proofs file (see rocq_synthesis.make_isolation_status)
    replace the coarse `?` poisoning for every goal they judge. It runs
    ONLY when the full build failed, and a refusal (None) keeps the
    coarse fallback — the refinement can downgrade precision, never
    upgrade a verdict the measurement did not support.
    """
    goals = list(audit_goals)
    witness_file = Path(witness_file)

    if verdict.error:
        return _all(goals, UNKNOWN, f"protocol run failed: {verdict.error}")
    poisoned = failed_tools(verdict)
    if poisoned:
        return _all(goals, UNKNOWN,
                    f"toolchain measurement failed: {', '.join(poisoned)}")
    build = next((c for c in verdict.components if c.targ_id == build_targ),
                 None)
    audit = next((c for c in verdict.components if c.targ_id == audit_targ),
                 None)
    if build is None or audit is None:
        missing = build_targ if build is None else audit_targ
        return _all(goals, UNKNOWN, f"no component {missing} in the verdict")
    stale = stale_files(audit)
    if stale:
        return _all(goals, UNKNOWN, _stale_detail(stale))

    if not build.passed:
        # the fallback tier: the audit judged an incomplete _build tree,
        # so only the build's own error attribution is meaningful
        ev = command_evidence(build)
        errs = parse_build_errors((ev or {}).get("stderr", ""))
        statuses = _all(goals, UNKNOWN, "build failed: the audit judged an "
                                        "incomplete tree")
        try:
            text = witness_file.read_text()
        except OSError:
            text = ""
        spans = [(n, s, e) for _k, n, s, e in rocq_decl_spans(text) if n]
        mapped = 0
        for path, line, msg in errs:
            if Path(path).name != witness_file.name:
                continue
            hit = next((n for n, s, e in spans if s <= line <= e), None)
            if hit is None:
                continue
            mapped += 1
            statuses[hit] = DeclStatus(state=FAILING,
                                       detail=_first_line(msg) or "build error")
        if isolate is not None:
            refined = isolate()
            if refined:
                statuses.update({g: st for g, st in refined.items()
                                 if g in statuses})
                return statuses
        if not mapped:
            reason = _first_line(build.reason) or "build failed"
            return _all(goals, UNKNOWN, f"build failed, unmappable: {reason}")
        return statuses

    # build green: the audit's own evidence is the judgment
    ev = command_evidence(audit)
    if ev is None:
        if audit.passed:
            return _all(goals, PROVED, "")
        return _all(goals, UNKNOWN,
                    _first_line(audit.reason) or "failed without evidence")
    sections = parse_audit_sections(str(ev.get("stdout", "")))
    if ev.get("status") != 0:
        # audit compile failure with a green build: a missing witness —
        # the failing Print Assumptions line names the goal
        errs = parse_build_errors(str(ev.get("stderr", "")))
        print_lines = _audit_print_lines(audit_file)
        failed_goal = None
        detail = ""
        for path, line, msg in errs:
            hit = next((g for g, ln in print_lines.items() if ln == line), None)
            if hit is not None:
                failed_goal, detail = hit, _first_line(msg)
                break
        statuses: Dict[str, DeclStatus] = {}
        for k, goal in enumerate(goals):
            if k < len(sections):
                statuses[goal] = _section_status(goal, sections[k])
            elif goal == failed_goal:
                statuses[goal] = DeclStatus(
                    state=FAILING,
                    detail="witness missing: " + (detail or "audit could "
                                                  "not resolve the goal"))
            else:
                statuses[goal] = DeclStatus(
                    state=UNKNOWN, detail="audit stopped before this goal")
        return statuses
    if len(sections) != len(goals):
        return _all(goals, UNKNOWN,
                    f"audit mismatch: {len(goals)} goals but "
                    f"{len(sections)} Print Assumptions sections")
    return {goal: _section_status(goal, section)
            for goal, section in zip(goals, sections)}


# ── the goals checklist ───────────────────────────────────────────────────────

def rocq_spec_conjuncts(blessed_text: str) -> List[str]:
    """The goal properties, from the blessed bytes: the head identifier
    of each `/\\`-conjunct of the blessed `Spec` definition's body."""
    lines = blessed_text.splitlines()
    for _kind, name, start, end in rocq_decl_spans(blessed_text):
        if name == "Spec":
            body = "\n".join(lines[start - 1:end])
            _, sep, rhs = body.partition(":=")
            if not sep:
                return []
            heads = []
            for part in rhs.split("/\\"):
                m = re.match(r"\s*\(?\s*([A-Za-z_][\w']*)", part)
                if m:
                    heads.append(m.group(1))
            return heads
    return []


def rocq_goal_checklist(blessed_text: str, verdict, build_targ: str,
                        audit_targ: str, audit_goals: List[str],
                        binding_goal: str, witness_file: Path,
                        audit_file: Optional[Path] = None,
                        isolate=None) -> Checklist:
    """
    One row per blessed goal property (the Spec `/\\`-conjuncts, scanned
    from the SIGNED blessed bytes) plus the `Spec bound` row from the
    audit's binding-goal section. A property's witnesses are the live
    declarations in `witness_file` whose STATEMENT references it; its
    cell is the worst witness status; a witness outside the audited goal
    set stays UNKNOWN (never presumed proved). No witness at all is its
    own state (legal mid-synthesis) — the binding row still governs.
    """
    witness_file = Path(witness_file)
    statuses = rocq_audit_status(verdict, build_targ, audit_targ,
                                 audit_goals, witness_file, audit_file,
                                 isolate=isolate)
    text = witness_file.read_text()
    lines = text.splitlines()
    spans = [(n, k, s, e) for k, n, s, e in rocq_decl_spans(text) if n]

    rows: List[ChecklistRow] = []
    for prop in rocq_spec_conjuncts(blessed_text):
        pattern = re.compile(rf"(?<![\w'.]){re.escape(prop)}(?![\w'])")
        witnesses = [
            name for name, _kind, s, e in spans
            if pattern.search(statement_part_rocq("\n".join(lines[s - 1:e])))
        ]
        if not witnesses:
            status = DeclStatus(state=NO_WITNESS,
                                detail="no witness declaration yet")
        else:
            cells = [statuses.get(w) or DeclStatus(
                state=UNKNOWN, detail=f"{w} is not in the audited goal set")
                for w in witnesses]
            status = max(cells, key=lambda st: _SEVERITY[st.state])
        rows.append(ChecklistRow(label=prop, status=status,
                                 witnesses=witnesses))

    binding = statuses.get(binding_goal) or DeclStatus(
        state=UNKNOWN, detail=f"goal '{binding_goal}' not audited")
    rows.append(ChecklistRow(label="Spec bound (acceptance)", status=binding))
    return Checklist(rows=rows)
