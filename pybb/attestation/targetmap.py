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
        f"{_TC}/slang/src/main/bridge/tc/TempControlSystem/TempControl_i_tcproc_tempControl_GumboX.scala",
        f"{_TC}/slang/src/main/bridge/tc/TempSensor/TempSensor_i_tcproc_tempSensor_GumboX.scala",
    ],
    "aadl": [
        (f"{_TC}/aadl/packages/TempControlSystem.aadl", "tc_sys_aadl"),
        (f"{_TC}/aadl/packages/TempSensor.aadl", "ts_aadl"),
    ],
    "gumbox": [
        (f"{_TC}/slang/src/main/bridge/tc/TempControlSystem/TempControl_i_tcproc_tempControl_GumboX.scala", "tc_gumbox"),
        (f"{_TC}/slang/src/main/bridge/tc/TempSensor/TempSensor_i_tcproc_tempSensor_GumboX.scala", "ts_gumbox"),
    ],
    "components": [
        (f"{_TC}/slang/src/main/component/tc/TempControlSystem/TempControl_i_tcproc_tempControl.scala", "tc_comp"),
        (f"{_TC}/slang/src/main/component/tc/TempSensor/TempSensor_i_tcproc_tempSensor.scala", "ts_comp"),
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

    from .copland import with_asp_targids

    return {
        "gumbo_l1a": {"hashfile": with_asp_targids(l1a)},
        "gumbo_l1b": {"readfile_marker_range": with_asp_targids(l1b)},
        "gumbo_l2": {"readfile_range": with_asp_targids(l2)},
    }


# ── report-driven backend ─────────────────────────────────────────────────────

def _stem_slug(filepath: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", Path(filepath).stem.lower()).strip("_")


def report_slices(report_path: Path) -> List[dict]:
    """
    Flatten a HAMR attestation report (emitted by Microkit codegen —
    aadl_attestation_report.json / sysml_attestation_report.json) into
    [{filepath, begin, end, kind, metadata}, ...], slice uris resolved
    relative to the report's directory, deduplicated.
    """
    import json as _json

    report_path = Path(report_path)
    base = report_path.parent
    report = _json.loads(report_path.read_text())
    out: List[dict] = []
    seen = set()

    def walk(node, component: str, contract: str):
        if isinstance(node, dict):
            ntype = node.get("type")
            if ntype == "ComponentReport":
                component = "_".join(node.get("idPath", [])) or component
            elif ntype and ntype.endswith("ContractReport"):
                contract = node.get("id", contract)
            elif ntype == "Slice":
                pos = node["pos"]
                filepath = str((base / pos["uri"]).resolve())
                key = (filepath, pos["beginLine"], pos["endLine"])
                if key not in seen:
                    seen.add(key)
                    out.append({
                        "filepath": filepath,
                        "begin": pos["beginLine"],
                        "end": pos["endLine"],
                        "kind": node.get("kind", ""),
                        "metadata": f"{component}::{contract}",
                    })
                return
            for v in node.values():
                walk(v, component, contract)
        elif isinstance(node, list):
            for v in node:
                walk(v, component, contract)

    walk(report, "", "")
    return out


def derive_targets_from_report(report_path: Path, prefix: str = "gumbo") -> Dict[str, Dict[str, dict]]:
    """
    Report-driven alternative to `derive_targets`: target maps from the
    HAMR attestation report, the authoritative statement of which contract
    slices matter (model positions AND their generated Verus/Rust
    realizations). Same output shape as the syntax scan:

        {"<prefix>_l1a": {"hashfile": ...},     # every unique file the report names
         "<prefix>_l2":  {"readfile_range": ...}}  # every report slice

    (No marker-block protocol: Microkit/Rust codegen expresses generated
    regions as report slices, not BEGIN/END markers.)
    """
    slices = report_slices(report_path)

    l1a: Dict[str, dict] = {}
    for filepath in sorted({s["filepath"] for s in slices}):
        targ, n = f"{prefix}_{_stem_slug(filepath)}_targ", 1
        while targ in l1a:
            n += 1
            targ = f"{prefix}_{_stem_slug(filepath)}_{n}_targ"
        l1a[targ] = {"filepath": filepath, "env_var": ""}

    l2: Dict[str, dict] = {}
    for s in slices:
        base_id = f"{prefix}_{_stem_slug(s['filepath'])}_{s['begin']}_{s['end']}"
        targ, n = f"{base_id}_targ", 1
        while targ in l2:
            n += 1
            targ = f"{base_id}_{n}_targ"
        l2[targ] = {
            "filepath": s["filepath"],
            "start_index": s["begin"],
            "end_index": s["end"],
            "metadata": s["metadata"],
        }

    from .copland import with_asp_targids

    return {
        f"{prefix}_l1a": {"hashfile": with_asp_targids(l1a)},
        f"{prefix}_l2": {"readfile_range": with_asp_targids(l2)},
    }


# ── lean-package backend ──────────────────────────────────────────────────────

_LEAN_DECL = re.compile(
    r"^(?:@\[[^\]]*\]\s*)?"
    r"(?:private\s+|protected\s+|noncomputable\s+|partial\s+|unsafe\s+)*"
    r"(theorem|lemma|def|abbrev|inductive|structure|instance|example)\b"
    r"\s*([A-Za-z_][\w'.]*)?")


def lean_decl_spans(text: str) -> List[Tuple[str, Optional[str], int, int]]:
    """
    (kind, name, start, end) for every top-level declaration in a Lean
    source: the declaration line through the end of its contiguous
    non-blank block (or the line before the next top-level declaration,
    whichever comes first) — 1-based inclusive, the same contiguous-block
    rule as gumbox_spans, so proof bodies must not contain blank lines.
    `name` is None for anonymous declarations (instance/example).

    Purely syntactic, but block-comment aware: lines inside `/- ... -/`
    (including doc comments, which nest per Lean's lexer) are never
    declaration starts — a comment line beginning with a declaration
    keyword must not become a target. An attribute line of its own
    (`@[simp]`) above the declaration is outside the span; it lives
    inside the l1a file hash regardless — l2 spans are attribution
    granularity, not the trust boundary.
    """
    lines = text.splitlines()
    starts: List[Tuple[int, str, Optional[str]]] = []
    depth = 0
    for i, line in enumerate(lines):
        at_line_start = depth
        depth = max(0, depth + line.count("/-") - line.count("-/"))
        if at_line_start > 0 or not line.strip() or line[:1].isspace():
            continue
        m = _LEAN_DECL.match(line)
        if m:
            starts.append((i, m.group(1), m.group(2)))
    spans: List[Tuple[str, Optional[str], int, int]] = []
    for idx, (i, kind, name) in enumerate(starts):
        next_start = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        j = i
        while j + 1 < next_start and lines[j + 1].strip():
            j += 1
        spans.append((kind, name, i + 1, j + 1))
    return spans


def derive_targets_from_lean(package_root: Path, prefix: str = "lean") -> Dict[str, Dict[str, dict]]:
    """
    Lean/Lake-package backend: measurement targets by syntax scan of the
    package's .lean sources (.lake build tree excluded). Same output shape
    as the other backends:

        {"<prefix>_l1a": {"hashfile": ...},        # every .lean source +
                                                   #   lakefile + lean-toolchain
         "<prefix>_l2":  {"readfile_range": ...}}  # every declaration span

    Hashing lakefile* and lean-toolchain pins the build configuration and
    the toolchain the proofs were checked under, not just the sources.

    l2 targets are named by declaration (lean_spec_fanOn_when_hot_targ),
    so a violated slice reads as the tampered theorem; anonymous
    declarations fall back to positional names. metadata carries
    Module.Path::decl for attribution.
    """
    package_root = Path(package_root)
    sources = sorted(p for p in package_root.rglob("*.lean")
                     if ".lake" not in p.parts)
    manifests = [p for p in (package_root / "lakefile.toml",
                             package_root / "lakefile.lean",
                             package_root / "lean-toolchain") if p.is_file()]

    l1a: Dict[str, dict] = {}
    for p in [*sources, *manifests]:
        targ, n = f"{prefix}_{_stem_slug(str(p))}_targ", 1
        while targ in l1a:
            n += 1
            targ = f"{prefix}_{_stem_slug(str(p))}_{n}_targ"
        l1a[targ] = {"filepath": str(p), "env_var": ""}

    l2: Dict[str, dict] = {}
    for p in sources:
        module = ".".join(p.relative_to(package_root).with_suffix("").parts)
        fslug = _stem_slug(str(p))
        for kind, name, start, end in lean_decl_spans(p.read_text()):
            if name:
                base_id = f"{prefix}_{fslug}_" + re.sub(r"\W+", "_", name)
                meta = f"{module}::{name}"
            else:
                base_id = f"{prefix}_{fslug}_{kind}_{start}_{end}"
                meta = f"{module}::{kind}@{start}"
            targ, n = f"{base_id}_targ", 1
            while targ in l2:
                n += 1
                targ = f"{base_id}_{n}_targ"
            l2[targ] = {
                "filepath": str(p),
                "start_index": start,
                "end_index": end,
                "metadata": meta,
            }

    from .copland import with_asp_targids

    return {
        f"{prefix}_l1a": {"hashfile": with_asp_targids(l1a)},
        f"{prefix}_l2": {"readfile_range": with_asp_targids(l2)},
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
