"""
Signed golden-spec ("props") protocols: administrator-blessed model files.

The golden properties of an example — GUMBO contract clauses in the AADL
model, theorem statements in a Lean specification — are protected at FILE
granularity: a props protocol measures the WHOLE model file (readfile, raw
bytes) and SIGNs it during provisioning, so the provision bundle is the
administrator's blessing of the file as a unit (policy: sanctioning
happens per artifact, not per clause). Slices are then derived VIEWS:
baseline verification (baseline.verify_bundle with anchor_protocols)
injects the measurement protocols' slice definitions and goldens into the
blessed evidence, and the model_slices_appr ASP checks that every
per-slice golden — and the file's hash golden — is EXTRACTABLE from the
blessed content. Slice definitions are appraiser inputs checked against
signed bytes, never independently trusted labels; re-deriving positions
(promotion, report regeneration) cannot invalidate a blessing while the
content is unchanged.

Wiring: a props protocol is a provisioning/baseline artifact, verified at
readiness — it is not an episode attestation entry (l1a/l2 already cover
live drift; props answers "is the baseline sanctioned").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

_SIG = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}
_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}

PROPS_SESSION = {
    "Session_Plc": "P0",
    "Plc_Mapping": {},
    "PubKey_Mapping": {},
    "Session_Context": {
        "ASP_Types": {
            "readfile": {
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
            "sig": {
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "ALL"},
                "ATTRS": []},
            "sig_appr": {
                "FWD": {"FWD": "REPLACE", "_BODY": 1},
                "ATTRS": []},
            "model_slices_appr": {
                "FWD": {"FWD": "REPLACE", "_BODY": 1},
                "ATTRS": []},
        },
        "ASP_Comps": {"readfile": "model_slices_appr", "sig": "sig_appr"},
    },
}

PROPS_MANIFEST = {"ASPS": ["readfile", "sig", "sig_appr", "model_slices_appr"],
                  "ASP_FS_MAP": {}, "POLICY": []}


def _stem_slug(filepath: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", Path(filepath).stem.lower()).strip("_")


def props_targets(prefix: str, filepaths: List[str]) -> Dict[str, dict]:
    targets: Dict[str, dict] = {}
    for fp in sorted(filepaths):
        targ, n = f"{prefix}_props_{_stem_slug(fp)}_targ", 1
        while targ in targets:
            n += 1
            targ = f"{prefix}_props_{_stem_slug(fp)}_{n}_targ"
        targets[targ] = {"env_var": "", "filepath": str(fp),
                         "asp_targid": targ}
    return targets


def props_term(targets: Dict[str, dict]) -> dict:
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": "readfile", "ASP_TARG_ID": targ}}}
        for targ in targets
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    return {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [acc, _SIG]}, _APPR]}


def write_props_protocol_dir(proto_dir: Path, prefix: str,
                             filepaths: List[str], description: str) -> None:
    """Write a props protocol dir (session/manifest/asp_args/term/meta).
    Goldens are NOT set — a provisioning request must follow; provisioning
    signs the whole-file evidence, and that bundle IS the blessing."""
    proto_dir = Path(proto_dir)
    proto_dir.mkdir(exist_ok=True)
    targets = props_targets(prefix, filepaths)
    (proto_dir / "session.json").write_text(json.dumps(PROPS_SESSION, indent=2) + "\n")
    (proto_dir / "manifest.json").write_text(json.dumps(PROPS_MANIFEST, indent=2) + "\n")
    (proto_dir / "asp_args.json").write_text(
        json.dumps({"readfile": targets}, indent=2) + "\n")
    (proto_dir / "term.json").write_text(json.dumps(props_term(targets), indent=2) + "\n")
    (proto_dir / "meta.json").write_text(json.dumps({
        "name": f"{prefix} signed golden spec (props)",
        "description": description,
        "copland": f"lseq( lseq( bseq( readfile×{len(targets)} ), SIG ), APPR )",
    }, indent=2) + "\n")


def model_files_from_report(report_path: Path) -> List[str]:
    """The model files: every file the report's Model-kind slices live in."""
    from .targetmap import report_slices

    return sorted({s["filepath"] for s in report_slices(report_path)
                   if s["kind"] == "Model"})
