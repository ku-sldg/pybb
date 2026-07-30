"""
Baseline verification: the signed golden evidence bundle, re-appraised by
the CVM.

Provisioning (provision.py) already runs each protocol's measurement term
WITH its SIG step against the golden copies, so every bundle under
<golden_root>/_bundles/<protocol_id>/ is a signed Copland evidence
package: RawEv whose first entry is the signature over the flattened
measurement bytes, plus the evidence-type tree that produced them. This
module closes the loop that made those signatures write-only: it verifies
a stored bundle and anchors the currently installed goldens to it.

Verification is an appraisal-only CVM run — no pybb-side crypto:

    TERM     = APPR
    EVIDENCE = the stored bundle's evidence package, with each target's
               currently installed golden_b64 injected into its asp_evt
               args
    SESSION  = the protocol's session (ASP_Comps dispatches companions)

The CVM walks the signed evidence tree under its own appraisal semantics:
the sig event dispatches sig_appr over signature + evidence bytes
(bundle integrity), and each measurement event dispatches its
goldenbytes companion comparing the SIGNED evidence bytes against the
INSTALLED golden (anchoring). A hand-edited golden_b64, a tampered
bundle byte, or a bundle that no longer covers the current target map
all fail, attributed per target. Injecting the goldens cannot weaken
the signature check: the signature covers the RawEv bytes, which are
submitted untouched.

Recorded limitations (documented, not solved here):

- The RSA signature covers the concatenated evidence BYTES; the evidence
  tree's target binding (which args produced which bytes) is unsigned
  metadata. Signing the evidence summary is a CVM-side fix.
- The signing keypair is the demo "unsecure_*_dont_use" pair compiled
  into the sig/sig_appr ASP binaries. Key custody is the actual trust
  root of this feature and is tracked as its own follow-up.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .appraisal import ComponentResult, parse_appraisal
from .provision import GOLDEN_COMPANIONS

_APPR_TERM = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}

# Bookkeeping fields never present in evidence-tree args (see provision.py).
_BOOKKEEPING_KEYS = ("golden_b64", "golden_ts", "filepath_golden", "env_var_golden")

# Identity keys pairing an evidence-tree event with an installed target
# (the same rule appraisal._match_targ_id uses).
_MATCH_KEYS = (
    "filepath", "start_index", "end_index", "begin_marker", "end_marker",
    "exe_args", "cwd",
)


class BaselineReport(BaseModel):
    """
    Outcome of verifying one protocol's signed golden baseline. Truthy iff
    the bundle exists, its signature verifies, every installed golden is
    anchored to the signed evidence, and the bundle covers exactly the
    current target map.
    """

    protocol: str
    bundle_path: str = ""
    signature_ok: bool = False
    anchored: List[str] = []  # targ_ids whose installed golden matches signed evidence
    linked: Dict[str, str] = {}  # build-mode cross-links: targ_id -> anchor protocol
    problems: List[str] = []
    components: List[ComponentResult] = []

    def __bool__(self) -> bool:
        return self.signature_ok and bool(self.anchored) and not self.problems


def _mirror(golden_root: Path, filepath: str) -> str:
    from .snapshot import mirror_path

    return str(mirror_path(golden_root, Path(filepath)))


def _golden_records(protocol: Any, golden_root: Path, golden_ids: set) -> List[dict]:
    """target_records with golden-rooted filepaths, as the evidence tree
    carries them, keeping the installed golden_b64 alongside."""
    records = []
    for asp_id, targets in protocol.asp_args.items():
        if asp_id not in golden_ids:
            continue
        for targ_id, args in targets.items():
            rec_args = {k: v for k, v in args.items() if k not in _BOOKKEEPING_KEYS}
            if rec_args.get("filepath") and not rec_args.get("measure_in_place"):
                rec_args["filepath"] = _mirror(golden_root, rec_args["filepath"])
            records.append({"asp_id": asp_id, "targ_id": targ_id,
                            "args": rec_args,
                            "live_filepath": args.get("filepath", ""),
                            "golden_b64": args.get("golden_b64", "")})
    return records


def _build_anchors(anchor_protocols: Dict[str, Any],
                   exclude_pid: Optional[str] = None) -> Dict[str, dict]:
    """Per live filepath, the goldens installed across the protocol map:
    the hashfile golden (with its source protocol, for cross-linking and
    audit) and every readfile_range slice golden. Protocols disagreeing on
    a file's hash golden are marked conflicted — a cross-link cannot pick
    a side silently."""
    anchors: Dict[str, dict] = {}
    for pid, protocol in (anchor_protocols or {}).items():
        if exclude_pid is not None and pid == exclude_pid:
            continue
        for asp_id, targets in protocol.asp_args.items():
            for targ_id, args in targets.items():
                fp, golden = args.get("filepath"), args.get("golden_b64")
                if not fp or not golden:
                    continue
                entry = anchors.setdefault(fp, {"slices": {}})
                if asp_id == "hashfile":
                    if "hash_golden_b64" in entry \
                            and entry["hash_golden_b64"] != golden:
                        entry["hash_conflict"] = \
                            f"{entry['hash_source']} vs {pid}"
                    else:
                        entry["hash_golden_b64"] = golden
                        entry["hash_source"] = pid
                elif asp_id == "readfile_range":
                    entry["slices"][targ_id] = {
                        "start_index": args["start_index"],
                        "end_index": args["end_index"],
                        "golden_b64": golden,
                    }
    return anchors


def _match_record(args: dict, records: List[dict]) -> Optional[dict]:
    for rec in records:
        keys = [k for k in _MATCH_KEYS if k in rec["args"]]
        if keys and all(args.get(k) == rec["args"].get(k) for k in keys):
            return rec
    return None


def _absolutize_paths(et_node: Any, golden_root: Path) -> None:
    """Older bundles were provisioned from the repo root with a relative
    golden_root, baking relative filepaths into the (unsigned) evidence
    tree. Resolve them against the golden root's parent so matching is
    form-independent; the signature covers the RawEv bytes, never these
    path strings, so normalization cannot mask tampering."""
    if not isinstance(et_node, dict):
        return
    body = et_node.get("EvidenceT_BODY")
    if et_node.get("EvidenceT_CONSTRUCTOR") == "asp_evt" \
            and isinstance(body, list) and len(body) >= 3:
        args = body[1].get("ASP_ARGS") or {}
        fp = args.get("filepath")
        if fp and not Path(fp).is_absolute():
            args["filepath"] = str((golden_root.parent / fp).resolve())
        _absolutize_paths(body[2], golden_root)
    elif isinstance(body, list):
        for child in body:
            _absolutize_paths(child, golden_root)
    elif isinstance(body, dict):
        _absolutize_paths(body, golden_root)


_ROLE_MISSING = {
    "build_in": "build input not covered by any source baseline",
    "build_out": "build output not enforced by any runtime protocol",
    "tool": "tool artifact has no blessed golden elsewhere",
}


def _record_role(rec: dict) -> Optional[str]:
    meta = str(rec["args"].get("metadata", ""))
    for role in ("build_in", "build_out", "tool"):
        if meta.startswith(role):
            return role
    return None


def _cross_link(rec: dict, anchors: Dict[str, dict], linked: Dict[str, str],
                problems: List[str]) -> Optional[str]:
    """Build-mode anchor selection: the golden to inject for a build-bundle
    event comes from ANOTHER protocol, chosen by the event's role — inputs
    from the source baseline, tools from the blessed toolchain goldens,
    outputs from the runtime protocol that enforces the artifact. Returns
    the golden to inject, or None after recording the problem."""
    role = _record_role(rec)
    anchor = anchors.get(rec["live_filepath"], {})
    if anchor.get("hash_conflict"):
        problems.append(
            f"{rec['targ_id']}: anchor protocols disagree on the golden "
            f"for {rec['live_filepath']} ({anchor['hash_conflict']})")
        return None
    golden = anchor.get("hash_golden_b64")
    if not golden:
        problems.append(
            f"{rec['targ_id']}: {_ROLE_MISSING[role]} "
            f"({rec['live_filepath']})")
        return None
    if rec["golden_b64"] and rec["golden_b64"] != golden:
        problems.append(
            f"{rec['targ_id']}: build record and {anchor['hash_source']} "
            f"disagree on the golden for {rec['live_filepath']}")
        return None
    linked[rec["targ_id"]] = anchor["hash_source"]
    return golden


def _inject_goldens(et_node: Any, records: List[dict], golden_ids: set,
                    comps: Dict[str, str], anchors: Dict[str, dict],
                    matched: Dict[str, int], problems: List[str],
                    build_mode: bool = False,
                    linked: Optional[Dict[str, str]] = None) -> None:
    """Walk the bundle's evidence tree; inject each measurement event's
    installed golden_b64 so its goldenbytes companion anchors the signed
    bytes against the installed value. Events whose companion is
    model_slices_appr (blessed whole-file evidence) additionally receive
    the hash and slice goldens other protocols install for that file, so
    the appraiser checks they are derivable from blessed content."""
    if not isinstance(et_node, dict):
        return
    ctor = et_node.get("EvidenceT_CONSTRUCTOR", "")
    body = et_node.get("EvidenceT_BODY")
    if ctor == "split_evt" and isinstance(body, list):
        for child in body:
            _inject_goldens(child, records, golden_ids, comps, anchors,
                            matched, problems, build_mode, linked)
    elif ctor == "asp_evt" and isinstance(body, list) and len(body) >= 3:
        _, params, sub_et = body
        asp_id = params.get("ASP_ID", "")
        if asp_id in golden_ids:
            args = params.get("ASP_ARGS") or {}
            rec = _match_record(args, records)
            if rec is None:
                problems.append(
                    f"bundle event not in current target map: "
                    f"{asp_id} {args.get('filepath', args)}")
            elif build_mode and _record_role(rec) is not None:
                golden = _cross_link(rec, anchors, linked if linked is not None
                                     else {}, problems)
                if golden is not None:
                    args["golden_b64"] = golden
                    params["ASP_ARGS"] = args
                    matched[rec["targ_id"]] = matched.get(rec["targ_id"], 0) + 1
            elif not rec["golden_b64"]:
                problems.append(f"{rec['targ_id']}: no golden installed to anchor")
            else:
                args["golden_b64"] = rec["golden_b64"]
                if comps.get(asp_id) == "model_slices_appr":
                    anchor = anchors.get(rec["live_filepath"], {})
                    if anchor.get("hash_golden_b64"):
                        args["hash_golden_b64"] = anchor["hash_golden_b64"]
                    if anchor.get("slices"):
                        args["slices"] = anchor["slices"]
                params["ASP_ARGS"] = args
                matched[rec["targ_id"]] = matched.get(rec["targ_id"], 0) + 1
        _inject_goldens(sub_et, records, golden_ids, comps, anchors,
                        matched, problems, build_mode, linked)
    elif ctor in ("left_evt", "right_evt"):
        inner = body if isinstance(body, dict) else (body[0] if body else None)
        _inject_goldens(inner, records, golden_ids, comps, anchors,
                        matched, problems, build_mode, linked)


def verify_bundle(client: Any, protocol: Any, golden_root: Path,
                  anchor_protocols: Optional[Dict[str, Any]] = None) -> BaselineReport:
    """
    Verify one protocol's signed golden baseline via an appraisal-only CVM
    run over the stored provision bundle.

    `anchor_protocols` (a protocol map, typically the episode's full set)
    activates blessed-content anchoring for props protocols: each blessed
    whole-file event is appraised by model_slices_appr against every hash
    and slice golden the other protocols install for that file — the
    goldens must be DERIVABLE from administrator-blessed content.
    """
    protocol_id = protocol.protocol_id
    golden_root = Path(golden_root).resolve()
    report = BaselineReport(protocol=protocol_id)

    comps = protocol.session.get("Session_Context", {}).get("ASP_Comps", {})
    golden_ids = {a for a, c in comps.items() if c in GOLDEN_COMPANIONS}
    if not golden_ids:
        report.problems.append("protocol has no goldenbytes components; "
                               "no baseline to verify")
        return report
    if "sig" not in comps:
        report.problems.append("protocol session has no sig companion; "
                               "bundle evidence would be unsigned")
        return report

    bundle_path = Path(golden_root) / "_bundles" / protocol_id / "provision_bundle.json"
    if not bundle_path.is_file():
        report.problems.append(f"no provision bundle at {bundle_path}")
        return report
    report.bundle_path = str(bundle_path)
    try:
        payload, _ctx = json.loads(bundle_path.read_text())
    except Exception as e:
        report.problems.append(f"unreadable bundle: {e}")
        return report

    evidence = copy.deepcopy(payload)
    if isinstance(evidence, list) and len(evidence) > 1:
        _absolutize_paths(evidence[1], golden_root)
    records = _golden_records(protocol, golden_root, golden_ids)
    anchors = _build_anchors(anchor_protocols or {}, exclude_pid=protocol_id)
    # build-bundle mode: events carry provenance roles; each is anchored
    # against ANOTHER protocol's golden (inputs vs the source baseline,
    # tools vs the blessed toolchain, outputs vs the runtime enforcer)
    build_mode = any(str(r["args"].get("metadata", "")).startswith("build_in")
                     for r in records)
    matched: Dict[str, int] = {}
    _inject_goldens(evidence[1] if isinstance(evidence, list) and len(evidence) > 1
                    else None, records, golden_ids, comps, anchors,
                    matched, report.problems, build_mode, report.linked)
    for rec in records:
        if rec["targ_id"] not in matched:
            report.problems.append(
                f"{rec['targ_id']}: not covered by the signed bundle "
                "(re-provisioning required)")
    if report.problems:
        return report

    plc = protocol.session.get("Session_Plc", "P0")
    request = {
        "TYPE": "REQUEST",
        "ACTION": "RUN",
        "REQ_PLC": plc,
        "TO_PLC": plc,
        "TERM": _APPR_TERM,
        "EVIDENCE": evidence,
        "ATTESTATION_SESSION": protocol.session,
    }
    try:
        response = client.run_protocol(
            protocol.model_copy(update={"prebuilt_request": request}))
    except Exception as e:
        report.problems.append(f"verification run failed: {e}")
        return report
    if not response.get("SUCCESS"):
        report.problems.append(
            f"verification run failed: {response.get('PAYLOAD', 'unknown error')}")
        return report

    match_records = [{"asp_id": r["asp_id"], "targ_id": r["targ_id"],
                      "args": r["args"]} for r in records]
    report.components = parse_appraisal(response, match_records)
    if not report.components:
        report.problems.append("verification run returned no appraisal evidence")
        return report

    for c in report.components:
        if c.appr_asp == "sig_appr":
            report.signature_ok = c.passed
            if not c.passed:
                report.problems.append(
                    f"bundle signature verification FAILED: {c.reason or 'invalid'}")
        elif c.targ_id is not None:
            if c.passed:
                report.anchored.append(c.targ_id)
            elif c.appr_asp == "model_slices_appr":
                report.problems.append(
                    f"{c.targ_id}: {c.reason or 'blessed-content anchoring failed'}")
            else:
                report.problems.append(
                    f"{c.targ_id}: installed golden does not match signed "
                    f"evidence ({c.reason or 'mismatch'})")
    if not any(c.appr_asp == "sig_appr" for c in report.components):
        report.problems.append("no signature event in bundle evidence")
    return report
