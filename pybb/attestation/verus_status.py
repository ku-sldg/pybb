"""
Per-crate Verus proof status — the Microkit/Rust workflow's progress
signal, derived from measured evidence.

The verus tier runs `cargo verus verify` once per contract-bearing
crate; each invocation is its own component, its appraiser
(run_command_verus_appr) judges `verification-results.errors == 0`, and
the retained output (ComponentResult.measured_b64) carries the
verification JSON. The checklist is one row per crate — the generated
Verus contracts must PROVE against the implemented behavior — rendered
with the same downgrade-only guardrails as proof_status:

  - a crate is only ever marked proved under its own component's PASS;
  - fail-closed: a protocol error, a missing component, or unparseable
    retained output downgrades to UNKNOWN, never up to proved;
  - column poisoning: a failed tool:: hash in the same verification
    term (the woven verus toolchain measurement) means no invocation's
    output can be trusted — every cell is UNKNOWN;
  - the checklist's ROWS come from the AM-owned verus protocol fixture
    (crate targets derived from the attestation report at provisioning),
    never from a live scan of the tree.
"""

from __future__ import annotations

import base64
import json
from typing import Dict, Optional

from .proof_status import (
    FAILING,
    PROVED,
    UNKNOWN,
    Checklist,
    ChecklistRow,
    DeclStatus,
    failed_tools,
    stale_files,
)


def _crate_of(args: dict) -> str:
    """The crate a run_command_cargo_verus target verifies: the cwd's
    basename (targets are built one-per-crate with cwd at the crate
    root)."""
    return (args.get("cwd") or "").rstrip("/").rsplit("/", 1)[-1] or "?"


def _verification_results(measured_b64: str) -> Optional[dict]:
    """The cargo-verus verification JSON from retained output, or None.
    Cold builds pollute stdout ahead of the JSON (the appraiser lesson),
    so scan for the first parseable object carrying the results key."""
    if not measured_b64:
        return None
    try:
        text = base64.b64decode(measured_b64).decode(errors="replace")
    except Exception:
        return None
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        try:
            d, _ = json.JSONDecoder().raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(d, dict) and "verification-results" in d:
            return d["verification-results"]
    return None


def verus_crate_checklist(verdict, crate_targets: Dict[str, dict]) -> Checklist:
    """
    One row per contract-bearing crate (the AM-owned verus fixture's
    run_command_cargo_verus targets), judged from the verus tier's
    verdict, downgrade-only per the module docstring.
    """
    rows = []
    poisoned = failed_tools(verdict) if not verdict.error else []

    for targ, args in sorted(crate_targets.items(),
                             key=lambda kv: _crate_of(kv[1])):
        crate = _crate_of(args)
        if verdict.error:
            status = DeclStatus(state=UNKNOWN,
                                detail=f"protocol run failed: {verdict.error}")
        elif poisoned:
            status = DeclStatus(
                state=UNKNOWN,
                detail="toolchain measurement failed: "
                       + ", ".join(poisoned))
        else:
            comp = next((c for c in verdict.components
                         if c.targ_id == targ), None)
            if comp is None:
                status = DeclStatus(state=UNKNOWN,
                                    detail=f"no component {targ} in the verdict")
            else:
                stale = stale_files(comp)
                results = _verification_results(comp.measured_b64)
                counts = ""
                if results is not None:
                    counts = (f"{results.get('verified', '?')} verified / "
                              f"{results.get('errors', '?')} errors")
                if stale:
                    status = DeclStatus(
                        state=UNKNOWN,
                        detail="measured file changed since the run")
                elif comp.passed:
                    status = DeclStatus(state=PROVED, detail=counts)
                else:
                    reason = " ".join((comp.reason or "").split())[:120]
                    status = DeclStatus(state=FAILING,
                                        detail=counts or reason
                                        or "verification failed")
        rows.append(ChecklistRow(label=crate, status=status))
    return Checklist(rows=rows)
