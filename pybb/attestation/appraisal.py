"""
Appraisal-result extraction from CVM responses.

After an APPR step, each appraiser's verdict is one entry in the flat RawEv
list, consumed in the same DFS order in which the evidence tree was built:
base64 of "" means the appraisal passed, anything else is a failure reason.
The tree walk is adapted from cvm-mcp's server._parse_appraisal_tree, the
reference implementation for this CVM build.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel


class ComponentResult(BaseModel):
    """Verdict for one appraised measurement target."""

    appr_asp: str
    target_asp: str
    targ_id: Optional[str] = None
    passed: bool
    reason: str = ""
    args: dict = {}
    description: str = ""


def _decode_verdict(raw: str) -> tuple[bool, str]:
    try:
        decoded = base64.b64decode(raw).decode()
    except Exception:
        decoded = raw
    return (True, "") if decoded == "" else (False, decoded)


def _find_target_asp_id(et_node, prefer_right: bool = False) -> str:
    if not isinstance(et_node, dict):
        return "unknown"
    ctor = et_node.get("EvidenceT_CONSTRUCTOR", "")
    body = et_node.get("EvidenceT_BODY", [])
    if ctor == "asp_evt":
        _, params, _ = body
        return params.get("ASP_ID", "unknown")
    elif ctor == "split_evt":
        child = body[1] if prefer_right else body[0]
        return _find_target_asp_id(child)
    elif ctor == "left_evt":
        inner = body if isinstance(body, dict) else (body[0] if body else None)
        return _find_target_asp_id(inner)
    elif ctor == "right_evt":
        inner = body if isinstance(body, dict) else (body[0] if body else None)
        return _find_target_asp_id(inner, prefer_right=True)
    return "unknown"


_MATCH_KEYS = (
    "filepath", "start_index", "end_index", "begin_marker", "end_marker",
    "exe_args", "cwd",
)


def _match_targ_id(args: dict, target_records: List[dict]) -> Optional[str]:
    """Match appraisal args back to a provisioned target id."""
    for rec in target_records:
        rec_args = rec.get("args", {})
        keys = [k for k in _MATCH_KEYS if k in rec_args]
        if keys and all(args.get(k) == rec_args.get(k) for k in keys):
            return rec["targ_id"]
    return None


def _describe_exe_args(exe_args: list) -> str:
    """
    Label a command ASP by its subcommand plus the most specific argument:
    a --classes value beats a file path beats the project directory.
    """
    label = " ".join(str(a) for a in exe_args[:2])
    disc = None
    for i, a in enumerate(exe_args):
        if a == "--classes" and i + 1 < len(exe_args):
            disc = str(exe_args[i + 1]).split(".")[-1]
    if disc is None:
        paths = [str(a) for a in exe_args if "/" in str(a)]
        if paths:
            disc = Path(paths[-1]).name
    return f"{label} {disc}" if disc else label


def _describe(args: dict) -> str:
    if isinstance(args.get("exe_args"), list) and args["exe_args"]:
        return _describe_exe_args(args["exe_args"])
    fp = args.get("filepath", "")
    if not fp:
        return ""
    name = Path(fp).name
    if "start_index" in args:
        return f"{name}:{args['start_index']}-{args.get('end_index', '?')}"
    if "begin_marker" in args:
        return f"{name}[{args['begin_marker']}]"
    return name


def parse_appsumm(response: dict) -> List[ComponentResult]:
    """
    Extract results from a rodeo AppraisalSummaryResponse:
    PAYLOAD = {asp_id: {targ_id: {meta, result}}}.
    """
    if not response.get("SUCCESS"):
        return []
    results = []
    for asp_id, targets in (response.get("PAYLOAD") or {}).items():
        for targ_id, report in targets.items():
            results.append(
                ComponentResult(
                    appr_asp=asp_id,
                    target_asp=asp_id.removesuffix("_appr"),
                    targ_id=targ_id,
                    passed=bool(report.get("result")),
                    reason="" if report.get("result") else (report.get("meta") or "appraisal failed"),
                    description=targ_id,
                )
            )
    return results


def parse_appraisal(
    response: dict, target_records: List[dict] | None = None
) -> List[ComponentResult]:
    """
    Extract per-component appraisal results from a ProtocolRunResponse dict
    (CVM evidence walk) or an APPSUMM response (rodeo transport).
    Returns [] when the response has no appraisal evidence (including
    SUCCESS=false runs, which the caller must treat as failure).
    """
    if response.get("ACTION") == "APPSUMM":
        return parse_appsumm(response)
    if not response.get("SUCCESS"):
        return []
    payload = response.get("PAYLOAD")
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    raw_ev: List[str] = payload[0].get("RawEv", [])
    records = target_records or []
    results: List[ComponentResult] = []
    idx = [0]

    def _walk(et_node) -> None:
        if not isinstance(et_node, dict):
            return
        ctor = et_node.get("EvidenceT_CONSTRUCTOR", "")
        body = et_node.get("EvidenceT_BODY", [])
        if ctor == "split_evt":
            _walk(body[0])
            _walk(body[1])
        elif ctor == "asp_evt":
            _, params, sub_et = body
            asp_id = params.get("ASP_ID", "")
            args = params.get("ASP_ARGS") or {}
            is_appraiser = "appr" in asp_id or asp_id in ("check_nonce",)
            if is_appraiser:
                raw = raw_ev[idx[0]] if idx[0] < len(raw_ev) else ""
                idx[0] += 1
                passed, reason = _decode_verdict(raw)
                results.append(
                    ComponentResult(
                        appr_asp=asp_id,
                        target_asp=_find_target_asp_id(sub_et),
                        targ_id=_match_targ_id(args, records),
                        passed=passed,
                        reason=reason,
                        args=args,
                        description=_describe(args),
                    )
                )
                # sub_et is original measurement evidence, not appraisal output
            else:
                _walk(sub_et)
        elif ctor in ("left_evt", "right_evt"):
            inner = body if isinstance(body, dict) else (body[0] if body else None)
            _walk(inner)

    _walk(payload[1])
    return results


def overall_verdict(components: List[ComponentResult]) -> bool:
    """Binary policy: pass iff there is at least one result and none failed."""
    return bool(components) and all(c.passed for c in components)


def component_key_id(c: ComponentResult, seen: Dict[str, int] | None = None) -> str:
    """Stable identifier for blackboard component keys."""
    base = c.targ_id or c.description or c.target_asp
    if seen is None:
        return base
    n = seen.get(base, 0)
    seen[base] = n + 1
    return base if n == 0 else f"{base}#{n}"
