"""
Build-event protocols: executable provenance as a signed Copland term.

A build protocol makes the BUILD itself an attested event, so an
executable artifact's golden is born linked to the evidence of its
production. One term, one signature:

    lseq( lseq( lseq( lseq( bseq( hashfile: builder toolchain ),
                            bseq( hashfile: input sources ) ),
                      run_command_<tool>( the build ) ),
                bseq( hashfile: output binaries ) ),
          SIG )                                     [APPR appended]

The evidence ORDER witnesses: this toolchain existed, these inputs
existed, then the build ran, then these outputs existed — all under one
signature. The protocol runs at PROVISIONING only (building is a
blessing-time act, like golden capture; episodes never rebuild): its
bundle is the build-provenance record, and the OUTPUT hash goldens are
cross-installed into the runtime protocol that will enforce them
(install_build_outputs), so the binary golden the exec tier compares
against is, at birth, a fragment of signed build evidence.

Event roles are carried in target metadata — "tool::<name>" (from the
tool registry), "build_input::<file>", "build_output::<file>" — so
baseline verification can select the right cross-link anchor per event:
inputs against the source protocol's goldens, tools against the blessed
toolchain goldens, outputs against the runtime protocol's installed
binary golden.

Inputs and outputs are measure_in_place: inputs are hashed LIVE at build
time (the evidence records what the build actually consumed — divergence
from the blessed sources is the cross-link check's job, not hidden by
re-rooting), and outputs live in build trees that are never
golden-mirrored. Output files may not exist before the build runs;
provisioning skips the upfront existence check for build_output targets
(the term hashes them after the build produces them).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List

from .tools import _APPR, _HASHFILE_TYPES, _SIG, _hashfile_chain, tool_targets

_BUILD_ASP_TYPE = {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                   "ATTRS": []}
_APPR_ASP_TYPE = {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []}


def _slug(filepath: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", Path(filepath).name.lower()).strip("_")


def _file_targets(prefix: str, role: str, filepaths: List[str]) -> Dict[str, dict]:
    targets: Dict[str, dict] = {}
    for fp in sorted(filepaths):
        targ, n = f"{prefix}_{role}_{_slug(fp)}_targ", 1
        while targ in targets:
            n += 1
            targ = f"{prefix}_{role}_{_slug(fp)}_{n}_targ"
        targets[targ] = {
            "filepath": str(fp),
            "env_var": "",
            "measure_in_place": True,
            "metadata": f"build_{role}::{Path(fp).name}",
        }
    return targets


def write_build_protocol_dir(
    proto_dir: Any, prefix: str, tool_names: List[str],
    input_filepaths: List[str], output_filepaths: List[str],
    build_asp_id: str, build_appr_id: str, build_args: dict,
    description: str,
) -> None:
    """Write a build protocol dir. `build_args` are the build invocation's
    ASP_ARGS (e.g. {"exe_args": ["build"], "cwd": <package>}); the build
    ASP and its appraiser follow the run_command pairing convention."""
    proto_dir = Path(proto_dir)
    proto_dir.mkdir(exist_ok=True)
    assert input_filepaths and output_filepaths, \
        "a build event needs at least one input and one output"

    tools = tool_targets(tool_names) if tool_names else {}
    inputs = _file_targets(prefix, "in", input_filepaths)
    outputs = _file_targets(prefix, "out", output_filepaths)
    cmd_targ = f"{prefix}_build_cmd_targ"

    core = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
            ({"TERM_CONSTRUCTOR": "lseq",
              "TERM_BODY": [_hashfile_chain(tools), _hashfile_chain(inputs)]}
             if tools else _hashfile_chain(inputs)),
            {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
                "ASP_CONSTRUCTOR": "ASPC",
                "ASP_BODY": {"ASP_ID": build_asp_id, "ASP_TARG_ID": cmd_targ,
                             "ASP_ARGS": build_args}}}]},
        _hashfile_chain(outputs)]}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [core, _SIG]}, _APPR]}

    asp_args = {"hashfile": {**tools, **inputs, **outputs},
                build_asp_id: {cmd_targ: dict(build_args)}}

    session = {
        "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {
            "ASP_Types": {**_HASHFILE_TYPES,
                          build_asp_id: dict(_BUILD_ASP_TYPE),
                          build_appr_id: dict(_APPR_ASP_TYPE)},
            "ASP_Comps": {"hashfile": "goldenbytes_appr", "sig": "sig_appr",
                          build_asp_id: build_appr_id},
        },
    }
    manifest = {"ASPS": ["hashfile", "goldenbytes_appr", "sig", "sig_appr",
                         build_asp_id, build_appr_id],
                "ASP_FS_MAP": {}, "POLICY": []}

    (proto_dir / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (proto_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (proto_dir / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
    (proto_dir / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (proto_dir / "meta.json").write_text(json.dumps({
        "name": f"{prefix} build event (executable provenance)",
        "description": description,
        "copland": ("lseq( lseq( lseq( lseq( bseq(hashfile: tools), "
                    "bseq(hashfile: inputs) ), build ), "
                    "bseq(hashfile: outputs) ), SIG )"),
    }, indent=2) + "\n")


def build_output_targets(build_protocol: Any) -> Dict[str, dict]:
    """The build protocol's output targets (metadata build_out::*)."""
    return {targ: args for targ, args
            in build_protocol.asp_args.get("hashfile", {}).items()
            if str(args.get("metadata", "")).startswith("build_out")}


def install_build_outputs(build_protocol: Any,
                          runtime_protocols: Dict[str, Any]) -> List[str]:
    """
    Cross-install: copy each build-output hash golden from the (freshly
    provisioned) build protocol into every runtime protocol carrying a
    hashfile target for the same artifact — the binary golden the runtime
    tier enforces IS the signed build event's output. Returns
    "protocol:targ" for each installed golden.
    """
    outputs = build_output_targets(build_protocol)
    by_filepath = {args["filepath"]: args for args in outputs.values()}
    installed: List[str] = []
    for pid, protocol in runtime_protocols.items():
        if protocol is build_protocol:
            continue
        changed = False
        new_args = copy.deepcopy(protocol.asp_args)
        for targ, args in new_args.get("hashfile", {}).items():
            src = by_filepath.get(args.get("filepath"))
            if src and src.get("golden_b64"):
                args["golden_b64"] = src["golden_b64"]
                if src.get("golden_ts"):
                    args["golden_ts"] = src["golden_ts"]
                installed.append(f"{pid}:{targ}")
                changed = True
        if changed:
            protocol.asp_args = new_args
            protocol.prebuilt_request = None
            proto_dir = Path(protocol.path)
            if proto_dir.is_dir():
                (proto_dir / "asp_args.json").write_text(
                    json.dumps(new_args, indent=2) + "\n")
                stale = proto_dir / "cvm_request.json"
                if stale.is_file():
                    stale.unlink()
    return installed
