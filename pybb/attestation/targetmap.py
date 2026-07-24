"""
Target-map derivation: measurement targets from artifact content.

The keystone of promotion: a sanctioned model change shifts line numbers,
so re-provisioning must regenerate the *target definitions* (ranges,
markers), not just golden values. This module derives them by syntax scan:

- AADL GUMBO clauses (`assume` / `guarantee` / `inv` inside `annex GUMBO`
  blocks, clause keyword line through the terminating `;`) -> gumbo_l2
  line-range targets for the model files
- GumboX `@strictpure def` spans (def line through the last line of the
  contiguous block) -> gumbo_l2 line-range targets for the oracle files
- component-file `// BEGIN X` / `// END X` pairs -> gumbo_l1b
  marker-range targets
- whole watched files -> gumbo_l1a hashfile targets

Derived maps are complete over their syntax, so they may be SUPERSETS of a
historically hand-curated provisioned map (verified: every provisioned
temp-control range is derivable). After promotion the derived map IS the
new baseline. Deriving from the HAMR attestation report instead (the
cvm-mcp hamr_report_protocols.py approach) is the planned alternative
backend; the scan keeps pybb self-contained for now.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── span scanners ─────────────────────────────────────────────────────────────

_AADL_ANNEX_OPEN = re.compile(r"annex\s+GUMBO\s*\{\*\*")
_AADL_CLAUSE = re.compile(r"^(assume|guarantee|inv)\s+\w+")


def aadl_contract_spans(text: str) -> List[Tuple[int, int]]:
    """1-based inclusive line spans of GUMBO clauses in an AADL model."""
    lines = text.splitlines()
    spans: List[Tuple[int, int]] = []
    in_annex = False
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if _AADL_ANNEX_OPEN.search(stripped):
            in_annex = True
        if "**}" in stripped:
            in_annex = False
        if in_annex and _AADL_CLAUSE.match(stripped) and not stripped.startswith("--"):
            j = i
            while j < len(lines) and not lines[j].rstrip().endswith(";"):
                j += 1
            spans.append((i + 1, j + 1))
            i = j + 1
            continue
        i += 1
    return spans


def gumbox_spans(text: str) -> List[Tuple[int, int]]:
    """1-based inclusive spans of @strictpure contract predicates."""
    lines = text.splitlines()
    spans = []
    for i, line in enumerate(lines):
        if line.strip().startswith("@strictpure def"):
            j = i
            while j + 1 < len(lines) and lines[j + 1].strip():
                j += 1
            spans.append((i + 1, j + 1))
    return spans


_MARKER = re.compile(r"//\s*(BEGIN\s+(.+?))\s*$")

_MARKER_SLUGS = [
    ("STATE VARS", "state_vars"),
    ("INITIALIZES MODIFIES", "init_mod"),
    ("INITIALIZES ENSURES", "init_ens"),
    ("COMPUTE MODIFIES", "compute_mod"),
    ("COMPUTE ENSURES", "compute_ens"),
]


def marker_blocks(text: str) -> List[Tuple[str, str]]:
    """(begin_marker, end_marker) pairs for codegen-managed blocks."""
    pairs = []
    for line in text.splitlines():
        m = _MARKER.search(line)
        if m:
            begin = m.group(1)
            pairs.append((begin, "END " + m.group(2)))
    return pairs


def _marker_slug(begin_marker: str) -> str:
    body = begin_marker.removeprefix("BEGIN").strip()
    for phrase, slug in _MARKER_SLUGS:
        if body.startswith(phrase):
            return slug
    return re.sub(r"\W+", "_", body.lower()).strip("_")


# ── target-map derivation ─────────────────────────────────────────────────────

# spec shape: {"hash_files": [filepath, ...],
#              "aadl": [(filepath, prefix), ...],
#              "gumbox": [(filepath, prefix), ...],
#              "components": [(filepath, prefix), ...]}

_TC = "/Users/adampetz/Claude_workspace/temp-control-jvm"
TEMP_CONTROL_SPEC = {
    "hash_files": [
        f"{_TC}/aadl/packages/TempControlSystem.aadl",
        f"{_TC}/aadl/packages/TempSensor.aadl",
        f"{_TC}/slang/src/main/bridge/tc/TempControlSoftwareSystem/TempControlPeriodic_p_tcproc_tempControl_GumboX.scala",
        f"{_TC}/slang/src/main/bridge/tc/TempSensor/TempSensorPeriodic_p_tcproc_tempSensor_GumboX.scala",
    ],
    "aadl": [
        (f"{_TC}/aadl/packages/TempControlSystem.aadl", "tc_sys_aadl"),
        (f"{_TC}/aadl/packages/TempSensor.aadl", "ts_aadl"),
    ],
    "gumbox": [
        (f"{_TC}/slang/src/main/bridge/tc/TempControlSoftwareSystem/TempControlPeriodic_p_tcproc_tempControl_GumboX.scala", "tc_gumbox"),
        (f"{_TC}/slang/src/main/bridge/tc/TempSensor/TempSensorPeriodic_p_tcproc_tempSensor_GumboX.scala", "ts_gumbox"),
    ],
    "components": [
        (f"{_TC}/slang/src/main/component/tc/TempControlSoftwareSystem/TempControlPeriodic_p_tcproc_tempControl.scala", "tc_comp"),
        (f"{_TC}/slang/src/main/component/tc/TempSensor/TempSensorPeriodic_p_tcproc_tempSensor.scala", "ts_comp"),
    ],
}


def derive_targets(spec: dict) -> Dict[str, Dict[str, dict]]:
    """
    Derive fresh asp_args maps (no golden values — provisioning fills them)
    for the three measurement protocols from current file content:

        {"gumbo_l1a": {"hashfile": {...}},
         "gumbo_l1b": {"readfile_marker_range": {...}},
         "gumbo_l2":  {"readfile_range": {...}}}
    """
    l1a = {}
    for filepath in spec["hash_files"]:
        targ = Path(filepath).stem.lower() + "_targ"
        l1a[targ] = {"filepath": filepath, "env_var": ""}

    l2 = {}
    for kind, scanner in (("aadl", aadl_contract_spans), ("gumbox", gumbox_spans)):
        for filepath, prefix in spec[kind]:
            for start, end in scanner(Path(filepath).read_text()):
                l2[f"{prefix}_{start}_{end}_targ"] = {
                    "filepath": filepath,
                    "start_index": start,
                    "end_index": end,
                }

    l1b = {}
    for filepath, prefix in spec["components"]:
        for begin, end in marker_blocks(Path(filepath).read_text()):
            l1b[f"{prefix}_{_marker_slug(begin)}_targ"] = {
                "filepath": filepath,
                "begin_marker": begin,
                "end_marker": end,
            }

    return {
        "gumbo_l1a": {"hashfile": l1a},
        "gumbo_l1b": {"readfile_marker_range": l1b},
        "gumbo_l2": {"readfile_range": l2},
    }


# ── term construction (the shape the provisioned protocols use) ──────────────

_SIG = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}
_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}


def build_term(asp_args: Dict[str, dict]) -> dict:
    """lseq( lseq( bseq_chain(ASPC...), SIG ), APPR ) over the target map."""
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": asp_id, "ASP_TARG_ID": targ_id},
        }}
        for asp_id, targets in asp_args.items()
        for targ_id in targets
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    return {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [acc, _SIG]}, _APPR]}


def install_targets(protocol, asp_args: Dict[str, dict]) -> int:
    """
    Install a freshly derived target map into a ProtocolDir: new term and
    asp_args in memory and on disk, stale prebuilt request dropped. Golden
    values are NOT set — a provisioning request must follow.
    Returns the number of targets installed.
    """
    import json

    protocol.asp_args = copy.deepcopy(asp_args)
    protocol.term = build_term(asp_args)
    protocol.prebuilt_request = None
    proto_dir = Path(protocol.path)
    if proto_dir.is_dir():
        (proto_dir / "asp_args.json").write_text(json.dumps(protocol.asp_args, indent=2) + "\n")
        (proto_dir / "term.json").write_text(json.dumps(protocol.term, indent=2) + "\n")
        stale = proto_dir / "cvm_request.json"
        if stale.is_file():
            stale.unlink()
    return sum(len(t) for t in asp_args.values())
