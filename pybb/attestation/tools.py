"""
Tool registry: the measurable identity of the verifier toolchains.

Just-in-time tool measurement (the measure-then-use pattern): a protocol
that invokes an external tool carries hashfile events for that tool's
artifacts, sequenced BEFORE the use inside the same Copland term, so the
evidence order itself witnesses "the tool was in this state immediately
before it ran". This module is the parameterizable core: WHAT constitutes
a tool's identity (its artifact list) and WHICH ASPs use which tools are
declarative data here; the weaving itself lives in the term transformer.

A tool's artifacts are everything on its invocation chain that embodies
its behavior — for lean: the workspace wrapper the CVM resolves via
path_prepend, the elan shim it execs, the pinned toolchain's entry-point
binaries, and the shared library carrying the elaborator (bin/lean is a
52K dynamically-linked stub; libleanshared.dylib is the 163M that matters).

Tool targets are provisioned MEASURE-IN-PLACE (args carry
measure_in_place=true): provisioning hashes the live artifact rather than
a golden/ copy — toolchains are not golden-restorable and their jars do
not belong in the repository; the installed hash golden is protected by
the provisioning bundle's signature like every other golden.

Measurement cadence is an optimization parameter of the WEAVER (see
with_tool_measurements): "per_use" weaves measurements into every term
that invokes the tool (tightest window, default); "per_episode" measures
once per episode in a dedicated always-run entry; "provision_only" trusts
the blessed hashes without live re-measurement. The registry is cadence-
agnostic.

Deliberately out of scope (user decision 2026-07-30): the attestation
stack itself (cvm binary, ASP executables). Self-measurement is drift
detection, not a root of trust; a system mechanism (e.g. TPM-backed boot
attestation) is the right tool for that layer and can be added later —
the registry accepts new classes without redesign (register_tool).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Union

from .provision import carry_goldens

HOME = Path.home()
WORKSPACE_BIN = HOME / "Claude_workspace" / "bin"
ELAN_HOME = HOME / ".elan"
VERUS_DIST = HOME / "Claude_workspace" / "verus-arm64-macos"
SIREUM_STANDALONE = HOME / "Applications" / "Sireum"
OSATE_PLUGINS = (HOME / ".sireum" / "phantom" / "osate-2.17.0-vfinal.app"
                 / "Contents" / "Eclipse" / "plugins")


def lean_artifacts(package_root: Union[str, Path]) -> List[str]:
    """The lean invocation chain for a Lake package: workspace wrapper ->
    elan shim -> pinned toolchain entry points -> elaborator library.
    The pin is read from the package's lean-toolchain file (already inside
    the l1a hash boundary), so the measured binaries are the ones elan
    will resolve for THIS package."""
    pin = (Path(package_root) / "lean-toolchain").read_text().strip()
    # elan's toolchain directory naming: '/' -> '--', ':' -> '---'
    slug = pin.replace("/", "--").replace(":", "---")
    toolchain = ELAN_HOME / "toolchains" / slug
    return [str(p) for p in (
        WORKSPACE_BIN / "lake",
        ELAN_HOME / "bin" / "lake",
        toolchain / "bin" / "lean",
        toolchain / "bin" / "lake",
        toolchain / "bin" / "leanchecker",
        toolchain / "lib" / "lean" / "libleanshared.dylib",
    )]


def cargo_verus_artifacts() -> List[str]:
    """The verus invocation chain: workspace wrapper -> distro binaries."""
    return [str(p) for p in (
        WORKSPACE_BIN / "cargo-verus",
        VERUS_DIST / "cargo-verus",
        VERUS_DIST / "rust_verify",
        VERUS_DIST / "verus",
    )]


def hamr_artifacts() -> List[str]:
    """The HAMR codegen + report emitter: the sireum kernel jar and the
    org.sireum OSATE plugins that perform AADL->AIR (phantom)."""
    plugins = sorted(OSATE_PLUGINS.glob("org.sireum*.jar")) \
        if OSATE_PLUGINS.is_dir() else []
    return [str(SIREUM_STANDALONE / "bin" / "sireum.jar"),
            *[str(p) for p in plugins]]


# name -> artifact resolver (callables taking no args; lean takes the
# Lake package root and is registered per-example via register_tool or
# called directly)
_REGISTRY: Dict[str, Callable[[], List[str]]] = {
    "cargo-verus": cargo_verus_artifacts,
    "hamr": hamr_artifacts,
}

# ASP_ID -> tool names it invokes (the weaver consults this)
ASP_USES: Dict[str, List[str]] = {
    "run_command_lean": ["lean"],
    "run_command_cargo_verus": ["cargo-verus"],
    "run_command_hamr": ["hamr"],
}


def register_tool(name: str, artifacts: Union[List[str], Callable[[], List[str]]],
                  used_by: List[str] = ()) -> None:
    """Extend or override the registry (also the test seam: tests register
    stub tools instead of tampering real toolchains)."""
    _REGISTRY[name] = artifacts if callable(artifacts) else (lambda: list(artifacts))
    for asp_id in used_by:
        ASP_USES.setdefault(asp_id, []).append(name)


def tool_artifacts(name: str) -> List[str]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown tool '{name}' — register_tool it first")
    return _REGISTRY[name]()


def _slug(filepath: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", Path(filepath).name.lower()).strip("_")


def tool_targets(tool_names: List[str], prefix: str = "tool") -> Dict[str, dict]:
    """hashfile targets for the named tools' artifacts, deduplicated,
    marked measure_in_place, with tool::<name> metadata for attribution."""
    targets: Dict[str, dict] = {}
    seen: Dict[str, str] = {}  # filepath -> targ (dedupe across tools)
    for name in tool_names:
        for fp in tool_artifacts(name):
            if fp in seen:
                continue
            targ, n = f"{prefix}_{name.replace('-', '_')}_{_slug(fp)}_targ", 1
            while targ in targets:
                n += 1
                targ = f"{prefix}_{name.replace('-', '_')}_{_slug(fp)}_{n}_targ"
            targets[targ] = {
                "filepath": fp,
                "env_var": "",
                "measure_in_place": True,
                "metadata": f"tool::{name}",
                "asp_targid": targ,
            }
            seen[fp] = targ
    return targets


def tools_for_term(asp_args: Dict[str, dict]) -> List[str]:
    """Which tools a protocol's ASPs invoke, in first-use order."""
    used: List[str] = []
    for asp_id in asp_args:
        for name in ASP_USES.get(asp_id, []):
            if name not in used:
                used.append(name)
    return used


# ── weaving: measure-then-use inside one term ─────────────────────────────────

# Measurement cadence — the optimization parameter:
#   "per_use"        weave hashfile(tool...) into every term that invokes
#                    the tool, sequenced before the use: the evidence order
#                    witnesses "measured immediately before running"
#                    (tightest window; ~123ms lean / ~21ms verus / ~133ms
#                    hamr per term with the asm hashfile)
#   "per_episode"    no weaving; the example registers a standalone
#                    <prefix>_tools protocol (build_tools_protocol_dir) as
#                    an always-run entry — tools measured once per episode
#   "provision_only" the standalone protocol is provisioned and its signed
#                    bundle baseline-verified at readiness, but tools are
#                    not re-measured live
CADENCES = ("per_use", "per_episode", "provision_only")

_SIG = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}
_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}

_HASHFILE_TYPES = {
    "hashfile": {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                 "ATTRS": []},
    "sig": {"FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "ALL"}, "ATTRS": []},
    "sig_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
    "goldenbytes_appr": {"FWD": {"FWD": "REPLACE", "_BODY": 1}, "ATTRS": []},
}


def _hashfile_chain(targets: Dict[str, dict]) -> dict:
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": "hashfile", "ASP_TARG_ID": targ}}}
        for targ in targets
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    return acc


def weave_tool_measurements(asp_args: Dict[str, dict], term: dict,
                            session: dict, manifest: dict) -> tuple:
    """
    The per_use cadence: return (asp_args, term, session, manifest) with
    hashfile measurements of every tool the protocol's ASPs invoke woven
    in, sequenced BEFORE the uses and SIGned with them in the same term:

        lseq( body, APPR )  ->  lseq( lseq( lseq( bseq(hashfile...),
                                                  body ), SIG ), APPR )

    The evidence order witnesses measure-then-use within one attested
    execution. Tool targets are measure_in_place (provisioning hashes the
    live artifact; see provision.py) and appraise via goldenbytes_appr
    against the blessed hash goldens. No-op for protocols that invoke no
    registered tools; refuses protocols that already carry hashfile
    targets (weaving is not idempotent and l1a-style protocols never need
    it — their ASPs use no external tools).
    """
    tools = tools_for_term(asp_args)
    if not tools:
        return asp_args, term, session, manifest
    existing_hash = asp_args.get("hashfile", {})
    if any(str(a.get("metadata", "")).startswith("tool::")
           for a in existing_hash.values()):
        raise ValueError("protocol already carries tool measurements — "
                         "refusing to weave twice")
    if not (term.get("TERM_CONSTRUCTOR") == "lseq"
            and isinstance(term.get("TERM_BODY"), list)
            and len(term["TERM_BODY"]) == 2
            and term["TERM_BODY"][1] == _APPR):
        raise ValueError("expected a tier-shaped term lseq(body, APPR)")

    targets = tool_targets(tools)
    body = term["TERM_BODY"][0]
    woven_term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
            {"TERM_CONSTRUCTOR": "lseq",
             "TERM_BODY": [_hashfile_chain(targets), body]},
            _SIG]},
        _APPR]}

    woven_args = {"hashfile": {**targets, **existing_hash},
                  **{k: v for k, v in asp_args.items() if k != "hashfile"}}

    session = json.loads(json.dumps(session))  # deep copy
    ctx = session.setdefault("Session_Context", {})
    types = ctx.setdefault("ASP_Types", {})
    for asp_id, typ in _HASHFILE_TYPES.items():
        types.setdefault(asp_id, typ)
    comps = ctx.setdefault("ASP_Comps", {})
    comps.setdefault("hashfile", "goldenbytes_appr")
    comps.setdefault("sig", "sig_appr")

    manifest = json.loads(json.dumps(manifest))
    asps = manifest.setdefault("ASPS", [])
    for asp_id in ("hashfile", "goldenbytes_appr", "sig", "sig_appr"):
        if asp_id not in asps:
            asps.append(asp_id)

    return woven_args, woven_term, session, manifest


def make_tool_gate(client: Any, protocol: Any) -> Callable[[], Union[str, None]]:
    """
    A just-before-use toolchain gate for promotion (see
    make_promotion_predicate's tool_gate): measures the tools protocol's
    live artifacts against its blessed hash goldens via a fresh
    attestation run. Returns None when the toolchain matches the blessing;
    an error string naming the drifted artifacts otherwise. Built fresh
    per call site so the measurement happens AT gate time, not at predicate
    construction.
    """
    from .knowledge_sources import attestation_request, make_attestation_predicate

    def gate() -> Union[str, None]:
        predicate = make_attestation_predicate(
            client, {protocol.protocol_id: protocol})
        verdict = predicate(attestation_request(protocol.protocol_id))
        if verdict.passed:
            return None
        failing = sorted({c.targ_id or c.description for c in verdict.failing()})
        return (f"{protocol.protocol_id} drifted from blessed hashes: "
                + ", ".join(failing)) if failing else \
            (verdict.error or f"{protocol.protocol_id} measurement failed")

    return gate


def build_tools_protocol_dir(proto_dir: Union[str, Path], prefix: str,
                             tool_names: List[str], description: str) -> None:
    """
    The per_episode / provision_only cadences: a standalone tools protocol
    (hashfile over the tools' artifacts + SIG + APPR). Provision it like
    any protocol (goldens land measure-in-place); attest it as an
    always-run entry for per_episode, or rely on readiness baseline
    verification alone for provision_only.
    """
    proto_dir = Path(proto_dir)
    proto_dir.mkdir(exist_ok=True)
    targets = tool_targets(tool_names, prefix=f"{prefix}_tool")
    session = {
        "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {
            "ASP_Types": dict(_HASHFILE_TYPES),
            "ASP_Comps": {"hashfile": "goldenbytes_appr", "sig": "sig_appr"},
        },
    }
    manifest = {"ASPS": ["hashfile", "goldenbytes_appr", "sig", "sig_appr"],
                "ASP_FS_MAP": {}, "POLICY": []}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq",
         "TERM_BODY": [_hashfile_chain(targets), _SIG]}, _APPR]}
    (proto_dir / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (proto_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    asp_args = {"hashfile": targets}
    args_path = proto_dir / "asp_args.json"
    if args_path.is_file():
        asp_args = carry_goldens(json.loads(args_path.read_text()), asp_args)
    args_path.write_text(json.dumps(asp_args, indent=2) + "\n")
    (proto_dir / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (proto_dir / "meta.json").write_text(json.dumps({
        "name": f"{prefix} toolchain measurement",
        "description": description,
        "copland": f"lseq( lseq( bseq( hashfile×{len(targets)} ), SIG ), APPR )",
    }, indent=2) + "\n")
