"""
The verified appraisal summary as pybb's episode-response interpreter.

copland-evidence-tools (Rocq, CakeML-extracted) exposes the formally
verified `do_appraisal_summary` from copland-spec: given a session and an
evidence package it re-partitions the flat RawEv into one entry per
appraisal event, with a machine-checked correctness theorem —
`Permutation r (flatten summary)` (every slot accounted for: the
fail-open dropped-component hazard is eliminated by proof, not runtime
checks) and `all_keys_provenance` (each entry's appraiser is the
session-declared ASP_Comps companion of its measurement, with the
evidence heads matching). Typing and slot-size preconditions are
decidable and fail closed inside the tool.

pybb's role degenerates to per-entry LOCAL interpretation, none of it
structural: decode the entry's verdict slot ("" = pass, else the
reason), read the target id from the stored EvidenceT's asp_targid (the
Step-1 self-identification key — attribution is a field read), and lift
the retained measured output (slot 1 of an EXTEND appraiser's slice).
No positional reconstruction happens in Python.

Transport: the tool reads the request from a FILE (--req-file, our
patch) because real evidence exceeds the CakeML runtime's ~64KB argv
buffer. The summary JSON uses DUPLICATE keys for repeated ASP ids
(association-list semantics — one entry per event, order preserved), so
parsing uses object_pairs_hook throughout.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .appraisal import ComponentResult, _decode_verdict, _describe

EVIDENCE_TOOLS_BIN = os.environ.get(
    "COPLAND_EVIDENCE_TOOLS",
    str(Path.home() / "Claude_workspace" / "copland-evidence-tools"
        / "_build" / "default" / "theories" / "copland_evidence_tools"))


def available() -> bool:
    return Path(EVIDENCE_TOOLS_BIN).is_file() and \
        os.access(EVIDENCE_TOOLS_BIN, os.X_OK)


class SummaryError(RuntimeError):
    """The verified summarizer refused or failed — treated as a failed
    protocol run (fail closed), never silently reinterpreted."""


def _entry_targ_and_args(et: Any) -> tuple:
    """The appraised event's args from the entry's stored EvidenceT: the
    top node is the appraisal event (its args are the appraised
    measurement's); if it carries no asp_targid (e.g. sig), the nested
    measurement node is consulted before giving up."""
    node = et
    args: Dict = {}
    first_args: Optional[Dict] = None
    while isinstance(node, (list, tuple)) or (
            isinstance(node, dict) and "EvidenceT_CONSTRUCTOR" in dict(node)):
        d = dict(node) if not isinstance(node, dict) else node
        if d.get("EvidenceT_CONSTRUCTOR") != "asp_evt":
            break
        body = d.get("EvidenceT_BODY", [])
        params = dict(body[1]) if len(body) > 1 else {}
        args = dict(params.get("ASP_ARGS") or {})
        if first_args is None:
            first_args = args
        if args.get("asp_targid"):
            return args.get("asp_targid"), first_args or args
        node = body[2] if len(body) > 2 else None
        if not isinstance(node, dict):
            break
    return None, first_args or args


def _target_asp(et: Any) -> str:
    """The appraised measurement's ASP id: the asp_evt directly beneath
    the entry's top (appraisal) node."""
    if isinstance(et, dict) and et.get("EvidenceT_CONSTRUCTOR") == "asp_evt":
        body = et.get("EvidenceT_BODY", [])
        sub = body[2] if len(body) > 2 else None
        if isinstance(sub, dict) and sub.get("EvidenceT_CONSTRUCTOR") == "asp_evt":
            return dict(sub.get("EvidenceT_BODY", [None, {}])[1]).get(
                "ASP_ID", "unknown")
    return "unknown"


def _plain(obj: Any) -> Any:
    """Convert pairs-hook structures back to plain dicts for serialization."""
    if isinstance(obj, list) and obj and all(
            isinstance(x, tuple) and len(x) == 2 for x in obj):
        return {k: _plain(v) for k, v in obj}
    if isinstance(obj, list):
        return [_plain(x) for x in obj]
    return obj


def summarize_response(response: dict, session: dict) -> List[ComponentResult]:
    """
    Interpret a CVM ProtocolRunResponse via the verified appraisal
    summary: one ComponentResult per appraisal event, attributed by
    asp_targid, with the retained measured output on EXTEND appraisers.
    Raises SummaryError on any refusal — the caller fails the protocol.
    """
    payload = response.get("PAYLOAD")
    if not isinstance(payload, list) or len(payload) < 2:
        raise SummaryError("response has no evidence payload to summarize")

    request = {"TYPE": "REQUEST", "ACTION": "APPSUMM",
               "ATTESTATION_SESSION": session, "EVIDENCE": payload}
    fd, req_path = tempfile.mkstemp(suffix="_appsumm_req.json",
                                    prefix="pybb_")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(request, f)
        proc = subprocess.run(
            [EVIDENCE_TOOLS_BIN, "--req-file", req_path],
            capture_output=True, text=True, timeout=300)
    finally:
        os.unlink(req_path)
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out.startswith("{"):
        raise SummaryError(
            f"summarizer failed: {(proc.stderr or out)[:300]}")
    summary = json.loads(out, object_pairs_hook=lambda p: p)
    top = dict(summary)
    if not top.get("SUCCESS"):
        raise SummaryError(f"summarizer refused the evidence: {out[:300]}")

    results: List[ComponentResult] = []
    slots = 0
    for aid, inner in top["PAYLOAD"]:
        for appr_id, pair in inner:
            et_pairs, rawev = pair
            et = _plain(et_pairs)
            rv = dict(rawev)["RawEv"]
            slots += len(rv)
            passed, reason = _decode_verdict(rv[0] if rv else "")
            targ_id, args = _entry_targ_and_args(et)
            results.append(ComponentResult(
                appr_asp=appr_id,
                target_asp=aid,
                targ_id=targ_id,
                passed=passed,
                reason=reason,
                args=args,
                description=_describe(args),
                measured_b64=rv[1] if len(rv) > 1 else "",
            ))
    # local-parse sanity (the THEOREM covers the tool's partitioning; this
    # guards OUR reading of its output): entries must jointly account for
    # every slot of the original response
    original = len(payload[0].get("RawEv", []))
    if slots != original:
        raise SummaryError(
            f"summary slot accounting mismatch: entries carry {slots}, "
            f"response has {original}")
    return results
