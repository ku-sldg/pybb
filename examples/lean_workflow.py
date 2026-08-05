"""
Shared driver for the Lean attestation examples: the whole pybb workflow —
protocol-dir generation, provisioning, attestation episodes, tamper demos,
and the out-of-band attestation-manager acts (--check / --promote) —
parameterized by a per-package LeanExampleConfig.

The architectural claim this module makes concrete: a second Lean scenario
is PURE CONFIGURATION. examples/temp_control_lean.py (temp-control) and
examples/landing_gear_lean.py (landing gear) are thin config modules over
this driver; nothing here knows either scenario. Per config the driver
builds six protocols

    <p>_l1a    whole-file hashes (.lean sources + lakefile + toolchain pin)
    <p>_l2     readfile_range per top-level declaration (attribution)
    <p>_props  the administrator-blessed spec (whole-file, signed)
    <p>_check  `lake lean <spec> -- --json`: every theorem must PROVE
    <p>_exec   hash-then-run of the pinned binary, one vector per contract
    <p>_build  the build event (toolchain -> inputs -> lake build -> binary)

and three always-run entries: <p>:files (fail -> <p>_l2 refines ->
[--repair] restore), <p>:proofs and <p>:behavior (escalate directly).
temp_control_lean_props and the exec expecteds are AM-owned and change only through
--promote. See the config modules' docstrings and docs/demo_lean.md /
docs/demo_gear.md for the scenario-level stories.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    changed_decls,
    make_attestation_predicate,
    make_promotion_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    promotion_request,
    readiness_request,
    request_provision,
    trust_summary,
)
from pybb.attestation.build import install_build_outputs, write_build_protocol_dir
from pybb.attestation.copland import with_asp_targids
from pybb.attestation.props import write_props_protocol_dir
from pybb.attestation.targetmap import build_term, derive_targets_from_lean
from pybb.attestation.tools import (
    lean_artifacts,
    register_tool,
    weave_tool_measurements,
)

REPO = Path(__file__).parent.parent
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
EVIDENCE_DIR = REPO / "evidence"  # per-episode archived responses (gzipped)
TEMPLATES = {"l1a": "temp_control_aadl_slang_l1a", "l2": "temp_control_aadl_slang_l2"}
LAKE = Path.home() / "Claude_workspace" / "bin" / "lake"

# Just-in-time tool measurement: the lean toolchain (wrapper -> elan shim
# -> pinned binaries -> elaborator library) is hashed IN THE SAME TERM as
# each tier's tool invocation, sequenced before the use. Cadence is the
# optimization parameter (~123 ms per woven term): "per_use" (default),
# "per_episode" (standalone tools entry), "provision_only" (blessed
# hashes, no live re-measurement).
TOOL_CADENCE = "per_use"

_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}
TIER_SESSION = {
    "Session_Plc": "P0", "Plc_Mapping": {}, "PubKey_Mapping": {},
    "Session_Context": {
        "ASP_Types": {
            "run_command_lean": {
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
            "run_command_lean_appr": {
                # EXTEND: the appraiser retains the evidence it judged, so
                # the tool's output survives into the episode response and
                # the verified appraisal summary lifts it per entry
                # (ComponentResult.measured_b64) — the per-contract join
                # material
                "FWD": {"FWD": "EXTEND", "_BODY": 1, "EvInSig": "NONE"},
                "ATTRS": []},
        },
        "ASP_Comps": {"run_command_lean": "run_command_lean_appr"},
    },
}
TIER_MANIFEST = {"ASPS": ["run_command_lean", "run_command_lean_appr"],
                 "ASP_FS_MAP": {}, "POLICY": []}


@dataclass
class LeanExampleConfig:
    """One Lean scenario: everything the driver needs, nothing else."""

    prefix: str            # protocol-id prefix and entry namespace
    package_root: Path     # the vendored Lake package
    spec_rel: str          # blessed spec file, relative to package_root
    bin_name: str          # the lean_exe target (.lake/build/bin/<name>)
    exec_vectors: dict     # key -> {"args": [...], "expected": "..."}
    tamper_targ: str       # l2 slice whose proof line --tamper corrupts
    tamper_semantic_spot: tuple  # (rel_file, old, new, message) for
                                 # --tamper-semantic's implementation flip

    def __post_init__(self) -> None:
        self.package_root = Path(self.package_root)
        register_tool("lean", lambda: lean_artifacts(self.package_root))

    # ── derived identity ──────────────────────────────────────────────────
    @property
    def l1a(self) -> str: return f"{self.prefix}_l1a"

    @property
    def l2(self) -> str: return f"{self.prefix}_l2"

    @property
    def props_id(self) -> str: return f"{self.prefix}_props"

    @property
    def check_id(self) -> str: return f"{self.prefix}_check"

    @property
    def exec_id(self) -> str: return f"{self.prefix}_exec"

    @property
    def build_id(self) -> str: return f"{self.prefix}_build"

    @property
    def protocol_ids(self) -> tuple: return (self.l1a, self.l2)

    @property
    def tier_ids(self) -> tuple: return (self.check_id, self.exec_id)

    @property
    def spec_file(self) -> Path: return self.package_root / self.spec_rel

    @property
    def bin(self) -> Path:
        return self.package_root / ".lake" / "build" / "bin" / self.bin_name

    @property
    def bin_targ(self) -> str:
        import re
        return f"{self.prefix}_bin_{re.sub(r'[^a-z0-9]+', '_', self.bin_name)}_targ"

    @property
    def exec_keys(self) -> tuple: return tuple(self.exec_vectors)

    def exec_targ(self, key: str) -> str:
        return f"{self.prefix}_exec_{key}_targ"

    def entry(self, question: str) -> str:
        return f"{self.prefix}:{question}"

    # ── tier config (the AM-owned protocol definitions) ───────────────────
    @property
    def check_targets(self) -> dict:
        return {f"{self.prefix}_spec_check_targ": {
            "exe_args": ["lean", self.spec_rel, "--", "--json"],
            "cwd": str(self.package_root)}}

    @property
    def exec_targets_default(self) -> dict:
        return {self.exec_targ(key): {
            "exe_args": ["env", str(self.bin), *vec["args"]],
            "cwd": str(self.package_root), "expected": vec["expected"]}
            for key, vec in self.exec_vectors.items()}

    @property
    def tier_meta(self) -> dict:
        # display names carry no prefix — the protocol ids (temp_control_lean_check,
        # landing_gear_lean_check) disambiguate
        return {
            self.check_id: {
                "name": "Lean Proof Check (semantic tier)",
                "description":
                    f"Runs `lake lean {self.spec_rel} -- --json`: every "
                    "theorem must still PROVE. The appraiser fails on any "
                    "error diagnostic or hasSorry warning. The lean "
                    "toolchain is hashed in the same term, before the "
                    "invocation (measure-then-use).",
            },
            self.exec_id: {
                "name": "Lean Executable Behavior (exec tier)",
                "description":
                    "Hashes the PINNED built binary against its "
                    "build-anchored golden, then executes it directly "
                    "(lake env <binary>, no rebuild) on one input vector "
                    "per contract case; the appraiser compares stdout to "
                    "the expected command. The lean toolchain is hashed "
                    "in the same term, before the invocations.",
            },
        }


# ── exec expecteds: AM config with promote-time sanction ──────────────────────

def resolved_exec_targets(cfg: LeanExampleConfig,
                          overrides: dict | None = None) -> dict:
    """
    The sanctioned behavior expectation: config defaults, then the
    currently installed (previously sanctioned) expecteds, then explicit
    --expect overrides — the promote-time sanctioning of a behavior
    change. Expecteds are AM config: laundering re-provisions goldens,
    never these.
    """
    targets = copy.deepcopy(cfg.exec_targets_default)
    installed = FIXTURES / cfg.exec_id / "asp_args.json"
    if installed.is_file():
        current = json.loads(installed.read_text()).get("run_command_lean", {})
        for targ, args in targets.items():
            if "expected" in current.get(targ, {}):
                args["expected"] = current[targ]["expected"]
    for key, value in (overrides or {}).items():
        if cfg.exec_targ(key) not in targets:
            raise SystemExit(f"--expect: unknown vector '{key}' "
                             f"(choose from {', '.join(cfg.exec_keys)})")
        targets[cfg.exec_targ(key)]["expected"] = value
    return targets


def _run_vector(args: dict) -> str:
    out = subprocess.run([str(LAKE), *args["exe_args"]], cwd=args["cwd"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def vector_failures(exec_targets: dict, run_vector=_run_vector) -> list:
    """Behavior vectors vs the sanctioned expecteds; [] iff conformant."""
    failures = []
    for targ, args in exec_targets.items():
        got = run_vector(args)
        if got != args["expected"]:
            failures.append(
                f"{targ}: expected '{args['expected']}', got '{got}'")
    return failures


def make_codegen_fn(cfg: LeanExampleConfig, exec_targets: dict,
                    run_vector=_run_vector):
    """
    The promotion pipeline's 'codegen' for Lean: there is no model->code
    step, so the sanctioned build IS the regeneration — lake build, then
    the behavior gate: every exec vector must match the sanctioned
    expecteds. A behavior change that was not sanctioned via --expect
    refuses the promotion before anything is blessed.
    """
    def build_and_check() -> str:
        subprocess.run([str(LAKE), "build"], cwd=cfg.package_root, check=True,
                       capture_output=True)
        failures = vector_failures(exec_targets, run_vector)
        if failures:
            raise RuntimeError(
                "behavior gate refused: " + "; ".join(failures)
                + " — if this behavior change is sanctioned, "
                  "re-run with --expect KEY=VALUE")
        return ("lake build ok; behavior vectors match the sanctioned "
                "expecteds")
    return build_and_check


# ── protocol-dir generation ───────────────────────────────────────────────────

def _tier_term(asp_id: str, targets: dict) -> dict:
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": asp_id, "ASP_TARG_ID": targ,
                         "ASP_ARGS": args}}}
        for targ, args in targets.items()
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    return {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [acc, _APPR]}


def build_tier_protocol_dirs(cfg: LeanExampleConfig,
                             exec_targets: dict | None = None) -> None:
    """(Re)generate the semantic-tier dirs from the config, with tool
    measurements woven in per TOOL_CADENCE. The exec tier additionally
    hashes the pinned binary against its build-anchored golden BEFORE
    running it (hash-then-run, same term). Exec expecteds are AM-owned:
    unless a sanctioned set is passed in (--promote --expect), the
    installed expecteds carry over (resolved_exec_targets)."""
    tier_targets = {cfg.check_id: cfg.check_targets,
                    cfg.exec_id: (exec_targets if exec_targets is not None
                                  else resolved_exec_targets(cfg))}
    for pid, targets in tier_targets.items():
        targets = with_asp_targids(targets)
        asp_args = {"run_command_lean": dict(targets)}
        term = _tier_term("run_command_lean", targets)
        if pid == cfg.exec_id:
            bin_targs = with_asp_targids({cfg.bin_targ: {
                "filepath": str(cfg.bin), "env_var": "",
                "measure_in_place": True,
                "metadata": f"binary::{cfg.bin_name}"}})
            asp_args = {"hashfile": bin_targs, **asp_args}
            body = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
                {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
                    "ASP_CONSTRUCTOR": "ASPC",
                    "ASP_BODY": {"ASP_ID": "hashfile",
                                 "ASP_TARG_ID": cfg.bin_targ}}},
                term["TERM_BODY"][0]]}
            term = {"TERM_CONSTRUCTOR": "lseq",
                    "TERM_BODY": [body, _APPR]}
        session, manifest = TIER_SESSION, TIER_MANIFEST
        if TOOL_CADENCE == "per_use":
            asp_args, term, session, manifest = weave_tool_measurements(
                asp_args, term, session, manifest)
        d = FIXTURES / pid
        d.mkdir(exist_ok=True)
        (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
        (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
        (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
        (d / "meta.json").write_text(
            json.dumps(cfg.tier_meta[pid], indent=2) + "\n")
        n_tools = len(asp_args.get("hashfile", {}))
        print(f"  {pid}: {len(targets)} targets"
              + (f" + {n_tools} woven tool measurements" if n_tools else ""))


def build_protocol_dirs(cfg: LeanExampleConfig, bless_props: bool = False,
                        exec_targets: dict | None = None) -> dict:
    """(Re)generate the measurement protocol dirs from the syntax scan.
    The props definition is AM-owned: it is rewritten only under
    --promote (bless_props) or when missing entirely (bootstrap) — an
    ordinary --provision keeps the existing blessing untouched."""
    derived = derive_targets_from_lean(cfg.package_root, prefix=cfg.prefix)
    protocols = {}
    for pid, template in ((cfg.l1a, TEMPLATES["l1a"]),
                          (cfg.l2, TEMPLATES["l2"])):
        d = FIXTURES / pid
        d.mkdir(exist_ok=True)
        for f in ("session.json", "manifest.json"):
            shutil.copy2(FIXTURES / template / f, d / f)
        (d / "asp_args.json").write_text(json.dumps(derived[pid], indent=2) + "\n")
        (d / "term.json").write_text(json.dumps(build_term(derived[pid])) + "\n")
        protocols[pid] = ProtocolDir.load(str(d))
        print(f"  {pid}: {sum(len(t) for t in derived[pid].values())} targets from scan")
    props_dir = FIXTURES / cfg.props_id
    if bless_props or not (props_dir / "asp_args.json").is_file():
        write_props_protocol_dir(
            props_dir, cfg.prefix, [str(cfg.spec_file)],
            "The administrator-blessed golden spec: whole-file signed "
            f"evidence of {cfg.spec_rel} (the contract theorems). Baseline "
            "verification checks that the spec's hash and declaration-slice "
            "goldens are derivable from the blessed content.")
        print(f"  {cfg.props_id}: 1 blessed spec file")
    else:
        print(f"  {cfg.props_id}: existing blessing kept "
              "(only --promote re-blesses the spec)")
    protocols[cfg.props_id] = ProtocolDir.load(str(props_dir))
    build_tier_protocol_dirs(cfg, exec_targets)
    for pid in cfg.tier_ids:
        protocols[pid] = ProtocolDir.load(str(FIXTURES / pid))
    inputs = [a["filepath"]
              for a in derived[cfg.l1a]["hashfile"].values()]
    write_build_protocol_dir(
        FIXTURES / cfg.build_id, cfg.prefix, ["lean"], inputs,
        [str(cfg.bin)],
        "run_command_lean", "run_command_lean_appr",
        {"exe_args": ["build"], "cwd": str(cfg.package_root)},
        "The build event: lake build as a signed term — toolchain, input "
        "sources, the build, and the output binary under one signature. "
        "The exec tier's binary golden is cross-installed from this "
        "bundle's output evidence.")
    protocols[cfg.build_id] = ProtocolDir.load(str(FIXTURES / cfg.build_id))
    print(f"  {cfg.build_id}: {len(inputs)} inputs -> 1 output, "
          "toolchain-measured build event")
    return protocols


def load_protocols(cfg: LeanExampleConfig, validate: bool = False) -> dict:
    if not all((FIXTURES / pid / "asp_args.json").is_file()
               for pid in (*cfg.protocol_ids, cfg.props_id)):
        print(f"{cfg.prefix} protocol dirs missing — generating from the "
              "syntax scan")
        protocols = build_protocol_dirs(cfg)
    else:
        protocols = {pid: ProtocolDir.load(str(FIXTURES / pid))
                     for pid in (*cfg.protocol_ids, cfg.props_id)}
    if validate:
        for pid in (*cfg.tier_ids, cfg.build_id):
            protocols[pid] = ProtocolDir.load(str(FIXTURES / pid))
    return protocols


# ── provisioning ──────────────────────────────────────────────────────────────

def provision_flow(cfg: LeanExampleConfig, protocols: dict,
                   bless_props: bool = False) -> None:
    """Capture golden and provision on the blackboard: measurement
    protocols and — with woven tool measurements — the tier protocols,
    whose tool hash goldens land measure-in-place (live artifacts, no
    golden copies). The props blessing is provisioned ONLY under
    --promote (bless_props) or when it has never been blessed (bootstrap):
    re-signing the spec is the administrator's sanctioning act, so
    ordinary re-provisioning — including a laundering pass — cannot
    refresh it."""
    props = protocols.get(cfg.props_id)
    props_unblessed = props is not None and not any(
        a.get("golden_b64")
        for a in props.asp_args.get("readfile", {}).values())
    pids = list(cfg.protocol_ids)
    if props is not None and (bless_props or props_unblessed):
        pids.append(cfg.props_id)
    measured = {pid: protocols[pid] for pid in pids}
    if cfg.build_id in protocols:
        measured[cfg.build_id] = protocols[cfg.build_id]  # build runs before tiers
    for pid in cfg.tier_ids:
        if pid in protocols and "hashfile" in protocols[pid].asp_args:
            measured[pid] = protocols[pid]
    snapshot = TargetSnapshot.capture(measured, dest=GOLDEN_ROOT)
    print(f"golden captured: {len(snapshot.files)} files")
    client = CvmSubprocessClient()
    ctl = BlackboardController()
    ctl.register_predicate("provision",
                           make_provision_predicate(client, measured, GOLDEN_ROOT))
    for pid in measured:
        request_provision(ctl.blackboard, pid)
    bb = ctl.run()
    for key, entry in bb.get_provision().items():
        print(f"  {key}: {len(entry.result.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: FAILED - {entry.result.error}")
    if cfg.build_id in protocols:
        installed = install_build_outputs(
            protocols[cfg.build_id],
            {pid: protocols[pid] for pid in cfg.tier_ids if pid in protocols})
        for entry in installed:
            print(f"  build output golden -> {entry}")


# ── the attestation-manager acts ──────────────────────────────────────────────

def check_flow(cfg: LeanExampleConfig, protocols: dict) -> None:
    """AM detection: the declaration-level diff, matched by name. The
    blessed spec bytes (props) are the authoritative baseline for the
    spec file — l2 goldens are launderable, the blessing is not."""
    diff = changed_decls(protocols[cfg.l2], cfg.package_root,
                         prefix=cfg.prefix,
                         props_protocol=protocols.get(cfg.props_id))
    if not diff:
        print("No declaration changes since last blessing; "
              "promotion not needed.")
        return
    print("Promotion needed — declarations changed since last blessing:")
    for label, bucket in (("added", diff.added), ("removed", diff.removed),
                          ("modified", diff.modified), ("moved", diff.moved)):
        for meta in bucket:
            print(f"  {label:<9}{meta}")
    print("Run --promote to make the sanctioned change the new baseline"
          " (an unsanctioned change should be investigated instead).")


def promote_flow(cfg: LeanExampleConfig, protocols: dict,
                 expect_overrides: dict) -> None:
    """
    The sanctioning act, in pipeline order:

      1. detection report (informational — what is being sanctioned)
      2. promotion request on the blackboard; its predicate runs the gates
         and moves gold: behavior gate (lake build + vectors vs the
         sanctioned expecteds), proof gate (the check protocol must prove,
         lean toolchain measured in the same term), syntax-scan target
         regeneration, golden capture
      3. only after the promote outcome is good: regenerate the AM-owned
         config (tier dirs with the sanctioned expecteds, the props
         blessing definition, the build event) and provision EVERYTHING,
         props included — the re-blessing
      4. verification episode against the new baseline

    Steps 2 and 3 are deliberately two blackboard runs: a refused gate
    must leave the old baseline fully in place, so no provision request
    exists until the promotion outcome is known good.
    """
    print("=== sanction review (declaration diff) ===")
    check_flow(cfg, protocols)
    exec_targets = resolved_exec_targets(cfg, expect_overrides)
    for key in expect_overrides or {}:
        print(f"  sanctioned expected: {key} -> "
              f"{exec_targets[cfg.exec_targ(key)]['expected']}")

    print("\n=== promotion episode (gates, then gold moves) ===")
    client = CvmSubprocessClient()
    gated = {pid: protocols[pid]
             for pid in (*cfg.protocol_ids, cfg.props_id)}
    gated[cfg.check_id] = protocols[cfg.check_id]
    ctl = BlackboardController()
    ctl.register_predicate("promotion", make_promotion_predicate(
        gated, GOLDEN_ROOT,
        targets_fn=lambda: derive_targets_from_lean(cfg.package_root,
                                                    prefix=cfg.prefix),
        codegen_fn=make_codegen_fn(cfg, exec_targets),
        client=client,
        validate_with=cfg.check_id,
    ))
    ctl.blackboard.write_entry(
        key=f"promote:{cfg.prefix}", predicate="promotion",
        measurement=promotion_request(cfg.prefix), partition="provision")
    bb = ctl.run()
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: REFUSED - {entry.result.error}")
    outcome = bb.provision[f"promote:{cfg.prefix}"].result
    print(f"  promote:{cfg.prefix}: {outcome.codegen}; proofs validated; "
          f"targets regenerated={outcome.targets}; "
          f"{outcome.captured} files -> golden")

    print("\n=== provisioning the new baseline (props re-blessed) ===")
    fresh = build_protocol_dirs(cfg, bless_props=True,
                                exec_targets=exec_targets)
    protocols.update(fresh)
    provision_flow(cfg, protocols, bless_props=True)

    print("\n=== verification episode (new baseline) ===")
    attest_episode(cfg, protocols, repair=False, validate=True)


# ── tamper demos ──────────────────────────────────────────────────────────────

def tamper(cfg: LeanExampleConfig, protocols: dict) -> None:
    """Corrupt the proof line of a named theorem slice."""
    args = protocols[cfg.l2].asp_args["readfile_range"][cfg.tamper_targ]
    spec = Path(args["filepath"])
    lines = spec.read_text().splitlines(keepends=True)
    lines[args["end_index"] - 1] = "  -- TAMPERED: proof body removed\n"
    spec.write_text("".join(lines))
    print(f"Tampered theorem slice: {spec.name} line {args['end_index']} "
          f"({args['metadata']})")


def tamper_semantic(cfg: LeanExampleConfig) -> Path:
    """Flip the implementation per the config's semantic-tamper spot."""
    rel, old, new, message = cfg.tamper_semantic_spot
    impl = cfg.package_root / rel
    text = impl.read_text()
    assert old in text, "implementation shape changed — update the config's " \
                        "tamper_semantic_spot"
    impl.write_text(text.replace(old, new))
    print(f"Tampered implementation: {message} ({rel})")
    return impl


# ── episodes ──────────────────────────────────────────────────────────────────

def attest_episode(cfg: LeanExampleConfig, protocols: dict, repair: bool,
                   validate: bool = False) -> BlackboardController:
    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate(
        "attestation", make_attestation_predicate(client, protocols,
                                                  archive_dir=EVIDENCE_DIR))
    controller.register_predicate("protocol_check",
                                  make_readiness_predicate(
                                      protocols, baseline_root=GOLDEN_ROOT,
                                      client=client))
    fail_chain = [TierKS(protocol_id=cfg.l2)]
    if repair:
        fail_chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                             refined_by=cfg.l2))
    episodes = {cfg.entry("files"): cfg.l1a}
    if validate:
        episodes[cfg.entry("proofs")] = cfg.check_id
        episodes[cfg.entry("behavior")] = cfg.exec_id
    starter = StartAttestationKS(episodes=episodes)
    for ks in (*fail_chain, starter):
        controller.add_ks(ks)
    controller.route(cfg.entry("files"), on_pass=[], on_fail=fail_chain)
    if validate:
        controller.route(cfg.entry("proofs"), on_pass=[], on_fail=[])
        controller.route(cfg.entry("behavior"), on_pass=[], on_fail=[])
    controller.blackboard.write_entry(
        key=cfg.entry("ready"), predicate="protocol_check",
        measurement=readiness_request(list(protocols)))
    controller.route(cfg.entry("ready"), on_pass=[starter], on_fail=[])
    controller.run()
    print(trust_summary(controller.blackboard, semantic=list(cfg.tier_ids)))
    return controller


# ── CLI ───────────────────────────────────────────────────────────────────────

def run_cli(cfg: LeanExampleConfig, description: str) -> None:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--expect", action="append", default=[],
                        metavar="KEY=VALUE")
    parser.add_argument("--tamper", action="store_true")
    parser.add_argument("--tamper-semantic", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--validate", action="store_true")
    cli = parser.parse_args()

    if cli.expect and not cli.promote:
        parser.error("--expect is the promote-time sanctioning knob; "
                     "use it with --promote")
    if cli.check:
        check_flow(cfg, load_protocols(cfg))
        return
    if cli.promote:
        overrides = {}
        for item in cli.expect:
            key, sep, value = item.partition("=")
            if not sep:
                parser.error(f"--expect wants KEY=VALUE, got '{item}'")
            overrides[key] = value
        promote_flow(cfg, load_protocols(cfg, validate=True), overrides)
        return
    if cli.provision:
        protocols = build_protocol_dirs(cfg)
        provision_flow(cfg, protocols)
        return

    if cli.tamper_semantic:
        cli.validate = True  # undetected without the semantic tiers
    protocols = load_protocols(cfg, validate=cli.validate)

    if cli.tamper_semantic:
        # Snapshot the CLEAN live bytes in memory before laundering: the
        # golden/ tree is re-captured over the tampered sources below, so
        # it cannot serve as the restore source afterward.
        impl = cfg.package_root / cfg.tamper_semantic_spot[0]
        clean = {str(impl): impl.read_bytes()}
        tamper_semantic(cfg)
        print("\n=== laundering: re-provisioning over the tampered tree ===")
        provision_flow(cfg, protocols)
        try:
            print("\n=== attestation episode (hashes bless the laundered change) ===")
            attest_episode(cfg, protocols, repair=False, validate=True)
        finally:
            for path, data in clean.items():
                Path(path).write_bytes(data)
            print("\nRestored implementation; re-provisioning clean baseline")
            provision_flow(cfg, protocols)
        return

    golden = TargetSnapshot.load(
        {pid: protocols[pid] for pid in cfg.protocol_ids}, GOLDEN_ROOT)
    if cli.tamper:
        tamper(cfg, protocols)
    try:
        attest_episode(cfg, protocols, repair=cli.repair, validate=cli.validate)
        if cli.repair:
            print("\n=== episode 2: verification (fresh run, fresh caches) ===")
            attest_episode(cfg, protocols, repair=cli.repair,
                           validate=cli.validate)
    finally:
        restored = golden.restore()
        if restored:
            print(f"\nRestored {len(restored)} live target(s) from golden")
