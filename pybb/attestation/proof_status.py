"""
Per-declaration proof status — the goal-directed workflow's progress
signal, derived from measured evidence.

The verification class's EXTEND appraiser retains the tool output it
judged, and the verified appraisal summary lifts it per component
(ComponentResult.measured_b64). For a lean target that output is the
`lake lean <file> -- --json` diagnostic stream: one JSON object per
line, each carrying fileName / pos{line, column} / severity / kind /
data. Mapping those positions onto the file's declaration spans
(targetmap.lean_decl_spans) refines a FAILED verdict into WHICH
declarations are refuted; joining witnesses onto the blessed Spec
conjuncts yields the goals checklist.

This is a DERIVED VIEW, downgrade-only by construction (the guardrails
agreed for per-contract joins):

  - decisions stay in ASPs: a declaration is only ever marked proved
    under the appraiser's PASS verdict, or — on a FAIL — when every
    refuting diagnostic mapped cleanly into some other declaration's
    span (labeled derived);
  - fail-closed: unmappable evidence (diagnostics in another file,
    outside every span, empty or unparseable output) downgrades every
    undiagnosed declaration to UNKNOWN, never up to proved;
  - column poisoning: a failed tool:: hash in the same verification
    term means the tool output cannot be trusted — every cell is
    UNKNOWN;
  - the checklist's ROWS come from the blessed bytes (the model
    protocol's signed readfile golden), never the live tree — the
    changed_decls principle: goldens are launderable, the blessing is
    not.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

from .targetmap import lean_decl_spans

# cell states
PROVED = "proved"
FAILING = "failing"
UNKNOWN = "unknown"
NO_WITNESS = "no-witness"

MARKS = {PROVED: "✓", FAILING: "✗", UNKNOWN: "?", NO_WITNESS: "–"}
_SEVERITY = {FAILING: 3, UNKNOWN: 2, PROVED: 1, NO_WITNESS: 0}


class DeclStatus(BaseModel):
    state: str
    detail: str = ""
    span: Optional[Tuple[int, int]] = None

    @property
    def mark(self) -> str:
        return MARKS[self.state]


def parse_diagnostics(raw: bytes) -> List[dict]:
    """The lean --json stream: one JSON diagnostic per line. Non-JSON
    lines are skipped (the cargo-verus cold-build lesson: never let
    pollution turn into a parse failure), as are JSON lines that do not
    look like diagnostics."""
    diags: List[dict] = []
    for line in raw.decode(errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and ("severity" in d or "kind" in d):
            diags.append(d)
    return diags


def _refuting(diags: List[dict]) -> List[dict]:
    return [d for d in diags
            if d.get("severity") == "error" or d.get("kind") == "hasSorry"]


def _first_line(text: str) -> str:
    return " ".join(text.split("\n", 1)[0].split())


def _all(spans, state: str, detail: str) -> Dict[str, DeclStatus]:
    return {name: DeclStatus(state=state, detail=detail, span=(s, e))
            for name, _kind, s, e in spans}


def _named_spans(text: str) -> List[tuple]:
    """(name, kind, start, end) with anonymous declarations given
    positional names, matching derive_targets_from_lean's convention."""
    return [(name if name else f"{kind}@{start}", kind, start, end)
            for kind, name, start, end in lean_decl_spans(text)]


def failed_tools(verdict) -> List[str]:
    """targ ids of failed tool-measurement components in a verdict —
    the poisoning condition: the term's own toolchain hashes did not
    verify, so its retained output cannot be trusted."""
    return [c.targ_id or c.description for c in verdict.components
            if not c.passed
            and (c.args.get("metadata") or "").startswith("tool::")]


def decl_status(verdict, targ_id: str, file_path: Path) -> Dict[str, DeclStatus]:
    """
    Per-declaration status of `file_path` from the verification
    verdict's component `targ_id`, per the downgrade-only model in the
    module docstring. Keys are declaration names (anonymous:
    `kind@line`); every declaration in the file gets a status.
    """
    file_path = Path(file_path)
    spans = _named_spans(file_path.read_text())

    if verdict.error:
        return _all(spans, UNKNOWN, f"protocol run failed: {verdict.error}")
    poisoned = failed_tools(verdict)
    if poisoned:
        return _all(spans, UNKNOWN,
                    f"toolchain measurement failed: {', '.join(poisoned)}")
    comp = next((c for c in verdict.components if c.targ_id == targ_id), None)
    if comp is None:
        return _all(spans, UNKNOWN, f"no component {targ_id} in the verdict")
    if comp.passed:
        return _all(spans, PROVED, "")

    refuting = _refuting(parse_diagnostics(
        base64.b64decode(comp.measured_b64) if comp.measured_b64 else b""))
    if not refuting:
        # failed, but the retained output names nothing we can map —
        # nothing may be presumed proved
        return _all(spans, UNKNOWN,
                    _first_line(comp.reason) or "failed without diagnostics")

    statuses = _all(spans, PROVED, "")
    unmapped = 0
    for diag in refuting:
        line = (diag.get("pos") or {}).get("line")
        hit = None
        if line is not None and Path(diag.get("fileName", "")) == file_path:
            hit = next((name for name, _k, s, e in spans if s <= line <= e),
                       None)
        if hit is None:
            unmapped += 1
            continue
        detail = _first_line(str(diag.get("data", "")))
        if diag.get("kind") == "hasSorry":
            detail = detail or "declaration uses 'sorry'"
        prev = statuses[hit]
        statuses[hit] = DeclStatus(
            state=FAILING,
            detail=prev.detail if prev.state == FAILING else detail,
            span=prev.span)
    if unmapped:
        # fail-closed: some refutation we could not attribute — the
        # undiagnosed declarations may be its victims
        for name, st in statuses.items():
            if st.state == PROVED:
                statuses[name] = DeclStatus(
                    state=UNKNOWN,
                    detail=f"{unmapped} unmappable diagnostic(s) in the run",
                    span=st.span)
    return statuses


# ── the goals checklist ───────────────────────────────────────────────────────

def spec_conjuncts(blessed_text: str) -> List[str]:
    """The goal properties, from the blessed bytes: the head identifier
    of each conjunct of the blessed `Spec` definition's body."""
    lines = blessed_text.splitlines()
    for kind, name, start, end in lean_decl_spans(blessed_text):
        if name == "Spec":
            body = "\n".join(lines[start - 1:end])
            _, sep, rhs = body.partition(":=")
            if not sep:
                return []
            heads = []
            for part in rhs.split("∧"):
                m = re.match(r"\s*\(?\s*([A-Za-z_][\w'.]*)", part)
                if m:
                    heads.append(m.group(1))
            return heads
    return []


class ChecklistRow(BaseModel):
    label: str
    status: DeclStatus
    witnesses: List[str] = []


class Checklist(BaseModel):
    rows: List[ChecklistRow] = []
    trusted: Optional[bool] = None  # None = quick view (no readiness run)

    def poison(self, detail: str) -> "Checklist":
        return Checklist(rows=[
            ChecklistRow(label=r.label,
                         status=DeclStatus(state=UNKNOWN, detail=detail),
                         witnesses=r.witnesses)
            for r in self.rows], trusted=False)


def _statement_part(decl_text: str) -> str:
    """The header of a declaration — everything before the first `:=`
    (witness matching must not see proof bodies, where `unfold <prop>`
    would false-positive)."""
    return decl_text.partition(":=")[0]


def goal_checklist(blessed_text: str, verdict, proofs_targ: str,
                   binding_targ: str, witness_file: Path) -> Checklist:
    """
    One row per blessed goal property (the Spec conjuncts, scanned from
    the SIGNED blessed bytes) plus the `Spec bound` row from the
    acceptance component's verdict. A property's witnesses are the live
    declarations in `witness_file` whose statement references it; its
    cell is the worst witness status. No witness at all is its own
    state (legal mid-synthesis) — the binding row still governs.
    """
    witness_file = Path(witness_file)
    statuses = decl_status(verdict, proofs_targ, witness_file)
    text = witness_file.read_text()
    lines = text.splitlines()
    spans = _named_spans(text)

    rows: List[ChecklistRow] = []
    for prop in spec_conjuncts(blessed_text):
        pattern = re.compile(rf"(?<![\w'.]){re.escape(prop)}(?![\w'])")
        witnesses = [
            name for name, _kind, s, e in spans
            if pattern.search(_statement_part("\n".join(lines[s - 1:e])))
        ]
        if not witnesses:
            status = DeclStatus(state=NO_WITNESS,
                                detail="no witness declaration yet")
        else:
            status = max((statuses[w] for w in witnesses),
                         key=lambda st: _SEVERITY[st.state])
        rows.append(ChecklistRow(label=prop, status=status,
                                 witnesses=witnesses))

    if verdict.error or failed_tools(verdict):
        binding = DeclStatus(
            state=UNKNOWN,
            detail=verdict.error or "toolchain measurement failed")
    else:
        comp = next((c for c in verdict.components
                     if c.targ_id == binding_targ), None)
        if comp is None:
            binding = DeclStatus(state=UNKNOWN,
                                 detail=f"no component {binding_targ}")
        elif comp.passed:
            binding = DeclStatus(state=PROVED)
        else:
            binding = DeclStatus(state=FAILING,
                                 detail=_first_line(comp.reason))
    rows.append(ChecklistRow(label="Spec bound (acceptance)", status=binding))
    return Checklist(rows=rows)


def render_checklist(checklist: Checklist) -> str:
    header = {
        None: "goal properties (derived progress view — quick: baselines "
              "not verified this run):",
        True: "goal properties (derived progress view — signed baselines "
              "verified):",
        False: "goal properties (derived progress view — BASELINES NOT "
               "TRUSTED):",
    }[checklist.trusted]
    width = max((len(r.label) for r in checklist.rows), default=0)
    out = [header]
    for r in checklist.rows:
        cell = f"  {r.label:<{width}}  {r.status.mark}"
        notes = []
        if r.status.state == PROVED and r.witnesses:
            notes.append(f"witness: {', '.join(r.witnesses)}")
        if r.status.detail:
            if r.status.state == FAILING and r.witnesses:
                notes.append(f"{', '.join(r.witnesses)}: {r.status.detail}")
            else:
                notes.append(r.status.detail)
        out.append(cell + (f"  ({'; '.join(notes)})" if notes else ""))
    return "\n".join(out)
