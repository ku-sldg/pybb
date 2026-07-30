"""
Provisioning on the blackboard: golden evidence bundles from the golden
directory.

A provisioning request lives in the blackboard's provision partition
(written by `request_provision` following an external event that adds
files to the golden directory) and names a protocol:

    {"protocol": <protocol_id>}

The registered predicate (built by `make_provision_predicate`) IS the
provisioning, mirroring the attestation predicate: it runs the protocol's
measurement-only term (APPR stripped) via the client against the golden
copies of the watched files — never the live tree — writes the evidence
bundle under <golden_root>/_bundles/<protocol_id>/, extracts each target's
golden slice with asp-libs' extract_golden_slice, and installs the fresh
golden_b64 values into the protocol's asp_args (in memory and on disk,
invalidating any prebuilt request that baked in old goldens). The
controller evaluates the provision partition before certify, so
attestation entries in the same run always see freshly provisioned
goldens.

Trust boundary: provisioning sources exclusively from the golden
directory. Files land there only by deliberate out-of-band acts (see
snapshot.py / capture_golden.py), so blackboard failure handling can never
launder live state into golden values.
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel

from ..blackboard import Blackboard, BlackboardEntry
from .client import DEFAULT_ASP_BIN
from .copland import empty_evidence, inject_asp_args, iter_aspc_bodies, normalize_term
from .snapshot import mirror_path

_NULL_ASP = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "NULL"}}

# Companion appraisers whose measurement ASPs carry provisioned goldens.
# model_slices_appr marks the signed golden-spec protocols: whole-file
# evidence whose golden is the administrator-blessed file content.
GOLDEN_COMPANIONS = ("goldenbytes_appr", "goldenevidence_appr", "model_slices_appr")

# Dashboard bookkeeping fields stored in asp_args.json but never sent to the
# CVM; they must not appear in the provisioning term's ASP_ARGS or the
# evidence-tree args would fail to match at extraction time.
_BOOKKEEPING_KEYS = ("golden_b64", "golden_ts", "filepath_golden", "env_var_golden")


def provision_request(protocol_id: str) -> dict:
    """Measurement descriptor for a provisioning request."""
    return {"protocol": protocol_id}


def request_provision(
    blackboard: Blackboard, protocol_id: str, predicate: str = "provision"
) -> BlackboardEntry:
    """
    External-event API: write a provisioning request for one protocol into
    the blackboard's provision partition. Re-provisioning after further
    golden-directory changes happens in a fresh workflow run (fresh
    predicate caches).
    """
    return blackboard.write_entry(
        key=f"provision:{protocol_id}",
        predicate=predicate,
        measurement=provision_request(protocol_id),
        partition="provision",
    )


class ProvisionOutcome(BaseModel):
    """
    Result of one provisioning request; a provision entry's result.
    Truthy iff the golden evidence bundle was created and every target's
    golden slice installed.
    """

    protocol: str
    provisioned: List[str] = []  # targ_ids with freshly installed goldens
    bundle_path: str = ""
    error: str = ""

    def __bool__(self) -> bool:
        return not self.error and bool(self.provisioned)


def _measurement_term(term: dict) -> dict:
    """
    Return a copy of term with every APPR ASP removed, so the provisioning
    run always succeeds (there is no golden to compare against yet).
    Adapted from cvm-mcp protocol_builder._make_measurement_term, the
    reference provisioning flow.
    """
    if not isinstance(term, dict):
        return term
    ctor = term.get("TERM_CONSTRUCTOR", "")
    body = term.get("TERM_BODY")

    if ctor == "asp":
        if isinstance(body, dict) and body.get("ASP_CONSTRUCTOR") == "APPR":
            return None  # signal parent to remove this node
        return term

    if ctor == "lseq" and isinstance(body, list):
        children = [c for c in (_measurement_term(x) for x in body) if c is not None]
        if not children:
            return _NULL_ASP
        if len(children) == 1:
            return children[0]  # unwrap so measurement evidence IS the output
        return {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": children}

    if ctor in ("bseq", "bpar") and isinstance(body, list) and len(body) >= 3:
        c1 = _measurement_term(body[1]) or _NULL_ASP
        c2 = _measurement_term(body[2]) or _NULL_ASP
        return {"TERM_CONSTRUCTOR": ctor, "TERM_BODY": [body[0], c1, c2]}

    if ctor == "att" and isinstance(body, list) and len(body) == 2:
        inner = _measurement_term(body[1])
        if inner is None:
            return None
        return {"TERM_CONSTRUCTOR": "att", "TERM_BODY": [body[0], inner]}

    return term


def _extract_golden_slice(bundle_dir: str, asp_id: str, targ_id: str) -> str:
    """Invoke asp-libs' extract_golden_slice; returns the golden_b64."""
    extract_bin = os.path.join(DEFAULT_ASP_BIN, "extract_golden_slice")
    result = subprocess.run(
        [extract_bin, bundle_dir, asp_id, targ_id], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"extract_golden_slice failed for {asp_id}/{targ_id}: "
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def make_provision_predicate(
    client: Any,
    protocols: Dict[str, Any],
    golden_root: Path,
    extract_fn: Callable[[str, str, str], str] = _extract_golden_slice,
) -> Callable[[dict], ProvisionOutcome]:
    """
    Predicate over provisioning-request measurements: run the named
    protocol's measurement-only term against the golden copies and install
    the extracted goldens. Memoized on the measurement so per-cycle
    re-evaluation is at-most-once per request descriptor per predicate
    lifetime; a later external event re-provisions in a fresh workflow run.
    """
    cache: Dict[str, ProvisionOutcome] = {}

    def predicate(measurement: dict) -> ProvisionOutcome:
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            cache[key] = _provision(client, protocols, golden_root, extract_fn, measurement)
        return cache[key]

    return predicate


def _provision(
    client: Any,
    protocols: Dict[str, Any],
    golden_root: Path,
    extract_fn: Callable[[str, str, str], str],
    measurement: dict,
) -> ProvisionOutcome:
    protocol_id = measurement.get("protocol", "")
    protocol = protocols.get(protocol_id)
    if protocol is None:
        return ProvisionOutcome(protocol=protocol_id,
                                error=f"unknown protocol '{protocol_id}'")

    comps = protocol.session.get("Session_Context", {}).get("ASP_Comps", {})
    golden_ids = {a for a, c in comps.items() if c in GOLDEN_COMPANIONS}
    if not golden_ids:
        return ProvisionOutcome(
            protocol=protocol_id,
            error="protocol has no goldenbytes_appr components; nothing to provision",
        )

    # provisioning term: assembled like an attestation request, then APPR
    # stripped, args re-rooted at the golden copies, asp_id_appr injected
    term = _measurement_term(
        normalize_term(inject_asp_args(protocol.term, protocol.asp_args))
    )
    missing = []
    for body in iter_aspc_bodies(term):
        args = {k: v for k, v in (body.get("ASP_ARGS") or {}).items()
                if k not in _BOOKKEEPING_KEYS}
        filepath = args.get("filepath")
        if filepath and args.get("measure_in_place"):
            # tool artifacts and build inputs/outputs: hash the LIVE file —
            # there is no golden copy (toolchains and build trees are not
            # golden-restorable); the installed hash golden is protected by
            # the bundle signature. Build OUTPUTS may not exist yet: the
            # term produces them before hashing them (the build event runs
            # between the input and output measurements).
            if not Path(filepath).is_file() and \
                    not str(args.get("metadata", "")).startswith("build_out"):
                missing.append(filepath)
        elif filepath:
            golden_copy = mirror_path(golden_root, Path(filepath))
            if not golden_copy.is_file():
                missing.append(filepath)
            args["filepath"] = str(golden_copy)
        if body.get("ASP_ID") in golden_ids:
            args["asp_id_appr"] = body["ASP_ID"]
        body["ASP_ARGS"] = args
    if missing:
        return ProvisionOutcome(
            protocol=protocol_id,
            error="no golden copy for: " + ", ".join(sorted(missing)),
        )

    plc = protocol.session.get("Session_Plc", "P0")
    request = {
        "TYPE": "REQUEST",
        "ACTION": "RUN",
        "REQ_PLC": plc,
        "TO_PLC": plc,
        "TERM": term,
        "EVIDENCE": empty_evidence(),
        "ATTESTATION_SESSION": protocol.session,
    }
    try:
        response = client.run_protocol(
            protocol.model_copy(update={"prebuilt_request": request})
        )
    except Exception as e:
        return ProvisionOutcome(protocol=protocol_id, error=str(e))
    if not response.get("SUCCESS"):
        return ProvisionOutcome(
            protocol=protocol_id,
            error=f"provisioning run failed: {response.get('PAYLOAD', 'unknown error')}",
        )

    # the golden evidence bundle: [payload, global_context], the format
    # extract_golden_slice / do_EvidenceSlice expects
    session_ctx = protocol.session.get("Session_Context", {})
    global_context = {
        "ASP_Types": session_ctx.get("ASP_Types", {}),
        "ASP_Comps": comps,
    }
    bundle_dir = Path(golden_root) / "_bundles" / protocol_id
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / "provision_bundle.json"
    bundle_path.write_text(json.dumps([response["PAYLOAD"], global_context]))
    # golden-rooted measurement args, so slice extraction reconstructs the
    # exact ASP_ARGS the evidence tree carries
    golden_args = {
        asp_id: {
            targ_id: _golden_args(args, golden_root)
            for targ_id, args in targets.items()
        }
        for asp_id, targets in protocol.asp_args.items()
    }
    (bundle_dir / "asp_args.json").write_text(json.dumps(golden_args, indent=2))

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_asp_args = copy.deepcopy(protocol.asp_args)
    provisioned = []
    for asp_id, targets in protocol.asp_args.items():
        if asp_id not in golden_ids:
            continue
        for targ_id in targets:
            try:
                golden_b64 = extract_fn(str(bundle_dir), asp_id, targ_id)
            except Exception as e:
                return ProvisionOutcome(protocol=protocol_id, error=str(e))
            new_asp_args[asp_id][targ_id]["golden_b64"] = golden_b64
            new_asp_args[asp_id][targ_id]["golden_ts"] = ts
            provisioned.append(targ_id)

    # install: shared ProtocolDir object first (same-run attestation sees
    # fresh goldens), then the protocol dir on disk. A prebuilt request
    # bakes in old goldens and must not survive re-provisioning.
    protocol.asp_args = new_asp_args
    protocol.prebuilt_request = None
    proto_dir = Path(protocol.path)
    if proto_dir.is_dir():
        (proto_dir / "asp_args.json").write_text(json.dumps(new_asp_args, indent=2))
        stale = proto_dir / "cvm_request.json"
        if stale.is_file():
            stale.unlink()

    return ProvisionOutcome(
        protocol=protocol_id,
        provisioned=provisioned,
        bundle_path=str(bundle_path),
    )


def _golden_args(args: dict, golden_root: Path) -> dict:
    out = {k: v for k, v in args.items() if k not in _BOOKKEEPING_KEYS}
    if out.get("filepath") and not out.get("measure_in_place"):
        out["filepath"] = str(mirror_path(golden_root, Path(out["filepath"])))
    return out
