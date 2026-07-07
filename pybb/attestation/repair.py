"""
Repair: HEAL-demo's attest→repair→re-attest loop as blackboard control.

A Repairer fixes a failing measured component; RepairKS (priority 12) reacts
to failing verdicts BEFORE escalation (priority 10) can trigger the expensive
semantic tier, then re-posts attestation requests so the pipeline re-verifies
the repaired state. Attempts are bounded via a blackboard counter; when they
exhaust (or nothing is repairable), RepairKS's guard goes false and the
starved EscalationKS finally fires — repair-first-then-diagnose, expressed
entirely by two priorities.

GoldenRestoreRepairer restores tampered content from the provisioned
readfile_range / readfile_marker_range goldens. Those ASPs measure the range
FLATTENED (newlines stripped, 1-based inclusive lines), so the golden cannot
be spliced back verbatim. Instead the repairer diffs the flattened current
content against the golden (common prefix/suffix), maps the differing span
back into real file offsets, and splices only that span — byte-exact for any
tamper confined within lines. It refuses (leaving the file untouched) when
the span would cross a newline or the result does not re-flatten to the
golden, so line counts (and therefore all other measured ranges) are always
preserved.

Repair modifies the measured tree only; it never writes golden state — that
remains provisioning, owned out-of-band.
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from ..blackboard import Blackboard
from ..knowledge_source import KnowledgeSource
from .appraisal import ComponentResult
from .knowledge_sources import (
    REPAIR_ACTION_PREFIX,
    REPAIR_ATTEMPTS_PREFIX,
    component_key,
    request_key,
    verdict_key,
)


def attempts_key(rid: str) -> str:
    return REPAIR_ATTEMPTS_PREFIX + rid


def action_key(rid: str, n: int, cid: str) -> str:
    return f"{REPAIR_ACTION_PREFIX}{rid}/{n}/{cid}"


class RepairAction(BaseModel):
    """Audit record of one repair attempt on one component."""

    targ_id: Optional[str] = None
    component: str
    filepath: str = ""
    success: bool
    description: str


class Repairer(ABC):
    """Fixes failing measured components; registered with RepairKS."""

    @abstractmethod
    def can_repair(self, component: ComponentResult) -> bool: ...

    @abstractmethod
    def repair(self, component: ComponentResult) -> RepairAction: ...


def _marker_matches(line: str, marker: str) -> bool:
    """Mirror of asp-libs readfile_marker_range marker matching."""
    content = line.strip()
    if content.startswith("//"):
        content = content[2:].strip()
    return content == marker


def _splice_flattened(block: str, golden_flat: str) -> Optional[str]:
    """
    Return block with its tampered line restored so the block re-flattens
    to golden_flat, or None if that cannot be done safely.

    Line-wise: consume block lines whose content prefixes the golden from
    the top and suffixes it from the bottom. If exactly one line remains,
    its original content is whatever golden text is left — restore it and
    the line count (hence every other measured range) is preserved. If the
    tamper spans multiple lines (or changed the line count), refuse.
    """
    lines = block.splitlines(keepends=True)
    contents = [l.rstrip("\n") for l in lines]
    endings = ["\n" if l.endswith("\n") else "" for l in lines]
    if "".join(contents) == golden_flat:
        return block  # nothing to repair

    g = golden_flat
    k = 0
    while k < len(contents) and g.startswith(contents[k]):
        g = g[len(contents[k]):]
        k += 1
    m = len(contents) - 1
    while m > k and g.endswith(contents[m]):
        g = g[: len(g) - len(contents[m])] if contents[m] else g
        m -= 1
    if k != m:
        return None  # tamper spans multiple lines or changed line count
    contents[k] = g
    repaired = "".join(c + e for c, e in zip(contents, endings))
    if "".join(contents) != golden_flat:
        return None
    return repaired


class GoldenRestoreRepairer(Repairer):
    """
    Restores failing readfile_range / readfile_marker_range components from
    their provisioned golden content.
    """

    def __init__(self, protocols: Dict[str, Any]):
        # targ_id -> golden args (original, un-rewritten; golden_b64 included)
        self._golden: Dict[str, dict] = {}
        for proto in protocols.values():
            for rec in proto.target_records():
                if rec["args"].get("golden_b64"):
                    self._golden[rec["targ_id"]] = rec["args"]

    def can_repair(self, component: ComponentResult) -> bool:
        if not component.targ_id or component.targ_id not in self._golden:
            return False
        args = component.args
        has_range = "start_index" in args and "end_index" in args
        has_markers = "begin_marker" in args and "end_marker" in args
        return bool(args.get("filepath")) and (has_range or has_markers)

    def repair(self, component: ComponentResult) -> RepairAction:
        args = component.args  # evidence args: filepath is the attested tree
        golden_flat = base64.b64decode(
            self._golden[component.targ_id]["golden_b64"]
        ).decode()
        path = Path(args["filepath"])

        def fail(reason: str) -> RepairAction:
            return RepairAction(
                targ_id=component.targ_id,
                component=component.description or component.targ_id,
                filepath=str(path),
                success=False,
                description=f"golden restore refused: {reason}",
            )

        if not path.is_file():
            return fail("file not found")
        lines = path.read_text().splitlines(keepends=True)

        if "start_index" in args:
            lo, hi = args["start_index"] - 1, args["end_index"]  # 1-based incl
            where = f"lines {args['start_index']}-{args['end_index']}"
        else:
            begin = [i for i, l in enumerate(lines) if _marker_matches(l, args["begin_marker"])]
            if not begin:
                return fail("begin_marker not found")
            lo = begin[0]
            end = [i for i in range(lo, len(lines)) if _marker_matches(lines[i], args["end_marker"])]
            if not end:
                return fail("end_marker not found")
            hi = end[0] + 1
            where = f"marker block [{args['begin_marker']}]"
        if not (0 <= lo < hi <= len(lines)):
            return fail("range outside file")

        block = "".join(lines[lo:hi])
        repaired = _splice_flattened(block, golden_flat)
        if repaired is None:
            return fail("tamper span crosses line boundaries")
        if repaired != block:
            path.write_text("".join(lines[:lo]) + repaired + "".join(lines[hi:]))
        return RepairAction(
            targ_id=component.targ_id,
            component=component.description or component.targ_id,
            filepath=str(path),
            success=True,
            description=f"restored {where} from provisioned golden",
        )


class RepairKS(KnowledgeSource):
    """
    Repairs failing components of watched verdicts and re-posts attestation
    requests. Bounded by max_attempts per verdict id.
    """

    name: str = "RepairKS"
    priority: int = 12
    repairers: List[Any]  # List[Repairer]
    watch: List[str]
    reattest: List[str] = []  # defaults to the repaired verdict id
    max_attempts: int = 3

    def _last_action_ts(self, bb: Blackboard, rid: str):
        prefix = f"{REPAIR_ACTION_PREFIX}{rid}/"
        stamps = [e.timestamp for k, e in bb.entries.items() if k.startswith(prefix)]
        return max(stamps) if stamps else None

    def _repairable(self, bb: Blackboard, rid: str) -> List[ComponentResult]:
        verdict = bb.read(verdict_key(rid))
        if verdict is None or verdict.get("passed"):
            return []
        out = []
        for cid, ok in verdict.get("components", {}).items():
            if ok:
                continue
            raw = bb.read(component_key(rid, cid))
            if raw is None:
                continue
            component = ComponentResult(**raw)
            if any(r.can_repair(component) for r in self.repairers):
                out.append(component)
        return out

    def _eligible(self, bb: Blackboard) -> List[str]:
        out = []
        for rid in self.watch:
            entry = bb.entries.get(verdict_key(rid))
            if entry is None:
                continue
            attempts = bb.read(attempts_key(rid)) or 0
            if attempts >= self.max_attempts:
                continue
            last = self._last_action_ts(bb, rid)
            if last is not None and entry.timestamp <= last:
                continue  # this failing verdict predates the last repair
            if self._repairable(bb, rid):
                out.append(rid)
        return out

    def can_contribute(self, blackboard: Blackboard) -> bool:
        return bool(self._eligible(blackboard))

    def execute(self, blackboard: Blackboard) -> None:
        rid = self._eligible(blackboard)[0]
        attempt = (blackboard.read(attempts_key(rid)) or 0) + 1
        for component in self._repairable(blackboard, rid):
            repairer = next(r for r in self.repairers if r.can_repair(component))
            action = repairer.repair(component)
            blackboard.write(
                key=action_key(rid, attempt, component.targ_id or component.description),
                value=action.model_dump(),
                source=self.name,
                confidence=1.0 if action.success else 0.0,
                tags=["attestation", "repair"],
            )
        blackboard.write(
            key=attempts_key(rid),
            value=attempt,
            source=self.name,
            tags=["attestation", "repair"],
        )
        # re-attest: fresh evidence for every protocol we are told to
        # re-verify (falling back to the repaired one), preserving each
        # request's original value (protocol id, path_map) when present
        for target in (self.reattest or [rid]):
            existing = blackboard.read(request_key(target)) or {"protocol": target}
            blackboard.write(
                key=request_key(target),
                value={**existing, "repair_attempt": attempt},
                source=self.name,
                tags=["attestation", "request", "repair"],
            )
