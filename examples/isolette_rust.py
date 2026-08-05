"""
isolette_AADL_Rust / isolette_SysMLv2_Rust (selected by --frontend) —
attestation-driven blackboard demo for the isolette: the INSPECTA
seL4/Microkit exemplar (targets/isolette-microkit), with the HAMR
**attestation report** as the authoritative source of the measurement
targets and golden slices.

The target vendors BOTH model frontends over ONE implemented
Microkit/Rust tree: the AADL workspace (aadl/) and the SysML v2 model
(sysml/). HAMR emits an attestation report per frontend
(aadl_attestation_report.json / sysml_attestation_report.json) from the
same frontend-agnostic reporter; the reports differ only in where their
Model-kind slices live (.aadl vs .sysml) — the Verus/Rust realization
slices cover the same implemented crates. `--frontend` selects which
report drives the workflow; each frontend has its own protocol set
(isolette_aadl_rust_* / isolette_sysmlv2_rust_*) and blessing, so both baselines coexist.

Protocols (generated from the selected report, never hand-curated;
prefix isolette_aadl_rust_ for AADL, isolette_sysmlv2_rust_ for SysML):

    <p>_l1a    whole-file hashes of every file the report names
               (model files + contract-bearing Rust files)
    <p>_l2     readfile_range of every report slice: Model (GUMBO
               contracts in the model language) + Verus/Rust realizations
               in the generated crates
    <p>_verus  [--validate] cargo-verus verify of every contract-bearing
               crate (7): the generated Verus contracts must PROVE against
               the implemented behavior
    <p>_props  the administrator-blessed model files (whole-file, signed)

One trust question — <p>:files — since every l2 slice lives inside an
l1a-hashed file:

    eval <p>_l1a: pass = intact (readiness has already verified the
                  SIGNED golden baseline bundle)
      fail -> <p>_l2 refines (which contract slice, model or Verus)
                fail -> [--repair] WholeFileRestoreKS restores the
                        violated files from golden; episode 2 verifies

The props blessing is owned by the out-of-band attestation manager and
changes ONLY through --promote (or first-time bootstrap): an ordinary
--provision re-blesses measurements but keeps the existing model
blessing, so an unsanctioned model change followed by re-provisioning
leaves a stale blessing that baseline verification refutes.

Usage:
    python examples/isolette_rust.py [--frontend {aadl,sysml}]
        [--check] [--provision] [--promote] [--tamper-verus] [--repair]
        [--validate]

--frontend   which model frontend's report drives the workflow
             (default: aadl — byte-identical to the pre-SysML behavior)
--check      attestation-manager detection: compare the model's contract
             content against the provisioned golden slices
--provision  (re)generate the protocol dirs from the attestation
             report, capture golden, and provision via the blackboard
             (creates the signed evidence bundles readiness verifies);
             the props blessing is kept, not re-signed
--promote    the sanctioned pipeline: tool gate (HAMR toolchain + for
             SysML the pinned sysml-aadl-libraries, measured immediately
             before use) -> REAL codegen in place (the report
             regenerates; SysML needs no OSATE) -> proof gate (the Verus
             tier must prove against the regenerated contracts) ->
             report-driven target regeneration -> gold moves -> full
             provisioning INCLUDING the props re-blessing -> a
             verification episode against the new baseline
--tamper-verus  corrupt a line inside a Verus contract slice of the
             generated Rust; detection/attribution (and --repair)
--validate   run the Verus semantic tier after a passing l1a
             (requires the Verus toolchain; cold builds are slow)
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
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
    changed_contracts,
    make_attestation_predicate,
    make_promotion_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    promotion_request,
    readiness_request,
    request_provision,
    trust_summary,
)
from pybb.attestation.copland import with_asp_targids
from pybb.attestation.props import model_files_from_report, write_props_protocol_dir
from pybb.attestation.targetmap import (
    build_term,
    derive_targets_from_report,
    report_slices,
)
from pybb.attestation.tools import (
    build_tools_protocol_dir,
    make_tool_gate,
    register_tool,
    weave_tool_measurements,
)

REPO = Path(__file__).parent.parent
ISL_ROOT = REPO / "targets" / "isolette-microkit"
ATTESTATION_DIR = ISL_ROOT / "hamr" / "microkit" / "attestation"
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
VERUS_ARGS = [
    "verify", "-Z", "build-std=core,alloc,compiler_builtins",
    "-Z", "build-std-features=compiler-builtins-mem",
    "--target", "aarch64-unknown-none", "--", "--output-json", "--time",
]


@dataclass(frozen=True)
class Frontend:
    """One model frontend: its report and the protocol namespace it owns."""

    name: str           # "aadl" | "sysml"
    prefix: str         # protocol-id prefix (isolette_aadl_rust_ / isolette_sysmlv2_rust_)
    model_suffix: str   # model-language extension (--check, props scope)
    model_label: str    # human phrase for the props blessing description

    @property
    def report(self) -> Path:
        return ATTESTATION_DIR / f"{self.name}_attestation_report.json"

    @property
    def l1a(self) -> str: return f"{self.prefix}_l1a"

    @property
    def l2(self) -> str: return f"{self.prefix}_l2"

    @property
    def props_id(self) -> str: return f"{self.prefix}_props"

    @property
    def verus_id(self) -> str: return f"{self.prefix}_verus"

    @property
    def protocol_ids(self) -> tuple: return (self.l1a, self.l2)


FRONTENDS = {
    "aadl": Frontend(name="aadl", prefix="isolette_aadl_rust", model_suffix=".aadl",
                     model_label="AADL model file"),
    "sysml": Frontend(name="sysml", prefix="isolette_sysmlv2_rust", model_suffix=".sysml",
                      model_label="SysML v2 model file"),
}

# Just-in-time tool measurement: the verus toolchain is hashed in the
# same term as the verification, before the use (~21 ms); the HAMR
# toolchain — and, for the SysML frontend, the sysml-aadl-libraries the
# codegen elaborates against — is measured by the promotion gate right
# before codegen.
TOOL_CADENCE = "per_use"
HAMR_TOOLS_ID = "hamr_tools"
SYSML_LIBS_ID = "sysml_libs"
SYSML_LIBS_ROOT = Path.home() / "Claude_workspace" / "sysml-aadl-libraries"
SIREUM_STANDALONE = Path.home() / "Applications" / "Sireum" / "bin" / "sireum"

# The libraries are codegen INPUT, not toolchain — but a contract change
# laundered through a library edit is exactly what the promote gate must
# refuse, so they are measured like a tool: pinned clone, live hashes vs
# blessed goldens (measure-in-place). Keep the clone pinned no newer than
# the Sireum release (newer library commits crash older frontends).
register_tool(SYSML_LIBS_ID, lambda: sorted(
    str(p) for p in SYSML_LIBS_ROOT.rglob("*.sysml")))

# per-frontend promote configuration: which tools protocols gate codegen
TOOL_GATE_IDS = {
    "aadl": (HAMR_TOOLS_ID,),
    "sysml": (HAMR_TOOLS_ID, SYSML_LIBS_ID),
}


def _sireum_env() -> dict:
    return {**os.environ,
            "SIREUM_CACHE": str(Path.home() / "Claude_workspace/.sireum_cache")}


def sysml_codegen() -> str:
    """Real SysML v2 codegen, in place: one CLI call, no OSATE/phantom.
    Regenerates the Microkit tree AND sysml_attestation_report.json at
    the vendored target; developer-owned app.rs files are never
    re-spliced (HAMR contract)."""
    if not SIREUM_STANDALONE.is_file():
        raise RuntimeError(
            f"standalone Sireum not found at {SIREUM_STANDALONE}")
    if not SYSML_LIBS_ROOT.is_dir():
        raise RuntimeError(
            f"sysml-aadl-libraries not found at {SYSML_LIBS_ROOT} — clone "
            "santoslab/sysml-aadl-libraries and PIN it no newer than the "
            "Sireum release")
    sysml_dir = ISL_ROOT / "sysml"
    subprocess.run(
        [str(SIREUM_STANDALONE), "hamr", "sysml", "codegen",
         "--package-name", "isolette",
         "--platform", "Microkit",
         "--runtime-monitoring",
         "--no-proyek-ive",
         "--workspace-root-dir", str(sysml_dir),
         "--sourcepath", f"{sysml_dir}:{SYSML_LIBS_ROOT}",
         "--system-name", "Isolette::Isolette_Single_Sensor",
         "--output-dir", str(ISL_ROOT / "hamr"),
         "--sel4-output-dir", str(ISL_ROOT / "hamr" / "microkit"),
         str(sysml_dir / "Isolette.sysml")],
        check=True, env=_sireum_env(), cwd=sysml_dir)
    return ("ran: sireum hamr sysml codegen -p Microkit "
            "(report regenerated in place)")


def aadl_codegen() -> str:
    """Real AADL codegen: phantom (AADL -> AIR via headless OSATE) then
    codegen -p Microkit, regenerating the tree and
    aadl_attestation_report.json in place. Wired for parity with the
    SysML frontend; its first in-place run is a supervised baseline
    migration (toolchain drift since INSPECTA generated the vendored
    tree) that has not been exercised yet."""
    if not SIREUM_STANDALONE.is_file():
        raise RuntimeError(
            f"standalone Sireum not found at {SIREUM_STANDALONE}")
    aadl_ws = ISL_ROOT / "aadl"
    with tempfile.TemporaryDirectory(prefix="pybb_air_") as tmp:
        air = Path(tmp) / "Isolette.json"
        subprocess.run([str(SIREUM_STANDALONE), "hamr", "phantom",
                        "-f", str(air), str(aadl_ws)],
                       check=True, env=_sireum_env())
        subprocess.run([str(SIREUM_STANDALONE), "hamr", "codegen",
                        "-p", "Microkit",
                        "--package-name", "isolette",
                        "--runtime-monitoring",
                        "--workspace-root-dir", str(aadl_ws),
                        "--output-dir", str(ISL_ROOT / "hamr"),
                        "--sel4-output-dir", str(ISL_ROOT / "hamr" / "microkit"),
                        str(air)],
                       check=True, env=_sireum_env())
    return ("ran: sireum hamr phantom + codegen -p Microkit "
            "(report regenerated in place)")


CODEGEN = {"aadl": aadl_codegen, "sysml": sysml_codegen}


def derive_report_targets(fe: Frontend):
    """The report is the authority on targets and golden slices."""
    return derive_targets_from_report(fe.report, prefix=fe.prefix)


def verus_crates(fe: Frontend) -> list:
    """Contract-bearing crates, from the report's Verus/Rust slices."""
    crates = set()
    for s in report_slices(fe.report):
        if s["kind"] in ("Verus", "Rust") and "/crates/" in s["filepath"]:
            crates.add(s["filepath"].split("/crates/")[1].split("/")[0])
    return sorted(crates)


def build_verus_protocol(fe: Frontend) -> ProtocolDir:
    """<p>_verus: report-derived crate list, temp_control_aadl_rust_verus session/manifest,
    verus toolchain measurements woven in per TOOL_CADENCE."""
    d = FIXTURES / fe.verus_id
    d.mkdir(exist_ok=True)
    targets = with_asp_targids({
        f"{fe.prefix}_{crate}_verus_targ": {
            "exe_args": VERUS_ARGS,
            "cwd": str(ISL_ROOT / "hamr" / "microkit" / "crates" / crate),
        }
        for crate in verus_crates(fe)
    })
    asp_args = {"run_command_cargo_verus": targets}
    nodes = [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": "run_command_cargo_verus",
                         "ASP_TARG_ID": targ, "ASP_ARGS": args}}}
        for targ, args in targets.items()
    ]
    acc = nodes[0]
    for node in nodes[1:]:
        acc = {"TERM_CONSTRUCTOR": "bseq", "TERM_BODY": ["both_paths", acc, node]}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        acc, {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}]}
    session = json.loads((FIXTURES / "temp_control_aadl_rust_verus" / "session.json").read_text())
    manifest = json.loads((FIXTURES / "temp_control_aadl_rust_verus" / "manifest.json").read_text())
    n_tools = 0
    if TOOL_CADENCE == "per_use":
        asp_args, term, session, manifest = weave_tool_measurements(
            asp_args, term, session, manifest)
        n_tools = len(asp_args.get("hashfile", {}))
    (d / "session.json").write_text(json.dumps(session, indent=2) + "\n")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
    (d / "term.json").write_text(json.dumps(term, indent=2) + "\n")
    (d / "meta.json").write_text(json.dumps({
        "name": "Isolette Verus Verification (semantic tier)",
        "description": "cargo-verus verify over every contract-bearing "
                       "isolette crate (report-derived): the generated Verus "
                       "contracts must PROVE against the implemented behavior. "
                       "The verus toolchain is hashed in the same term, before "
                       "the invocations (measure-then-use).",
        "copland": f"lseq( bseq( run_command_cargo_verus×{len(targets)} ), APPR )",
    }, indent=2) + "\n")
    print(f"  {fe.verus_id}: {len(targets)} crates from report"
          + (f" + {n_tools} woven tool measurements" if n_tools else ""))
    return ProtocolDir.load(str(d))


def build_protocol_dirs(fe: Frontend, bless_props: bool = False) -> dict:
    """(Re)generate the frontend's protocol dirs from its report. The
    props definition is AM-owned: rewritten only under --promote
    (bless_props) or when missing entirely (bootstrap) — an ordinary
    --provision keeps the existing blessing untouched."""
    derived = derive_report_targets(fe)
    protocols = {}
    for pid, asp_args in derived.items():
        d = FIXTURES / pid
        d.mkdir(exist_ok=True)
        template = "temp_control_aadl_slang_l1a" if pid.endswith("_l1a") else "temp_control_aadl_slang_l2"
        for f in ("session.json", "manifest.json"):
            shutil.copy2(FIXTURES / template / f, d / f)
        (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
        (d / "term.json").write_text(json.dumps(build_term(asp_args)) + "\n")
        protocols[pid] = ProtocolDir.load(str(d))
        print(f"  {pid}: {sum(len(t) for t in asp_args.values())} targets from report")
    props_dir = FIXTURES / fe.props_id
    if bless_props or not (props_dir / "asp_args.json").is_file():
        # props scope = every file the report classifies as Model-kind —
        # the report is the authority, not the file extension (both
        # reports place one Model-classified Verus spec fn in a generated
        # app.rs; the committed AADL blessing has always covered it)
        model_files = model_files_from_report(fe.report)
        write_props_protocol_dir(
            props_dir, fe.prefix, model_files,
            "The administrator-blessed golden spec: whole-file signed evidence "
            f"of every {fe.model_label} the report's GUMBO contract (Model) "
            "slices live in. Baseline verification checks that all hash and "
            "slice goldens are derivable from the blessed content.")
        print(f"  {fe.props_id}: {len(model_files)} blessed model files")
    else:
        print(f"  {fe.props_id}: existing blessing kept "
              "(only --promote re-blesses the model)")
    protocols[fe.props_id] = ProtocolDir.load(str(props_dir))
    protocols[fe.verus_id] = build_verus_protocol(fe)
    build_tools_protocol_dir(
        FIXTURES / HAMR_TOOLS_ID, "hamr", ["hamr"],
        "The HAMR codegen + report-emitter toolchain (sireum.jar + the "
        "org.sireum OSATE plugins): measured in place at blessing, and "
        "re-measured by the promotion gate immediately before codegen.")
    protocols[HAMR_TOOLS_ID] = ProtocolDir.load(str(FIXTURES / HAMR_TOOLS_ID))
    print(f"  {HAMR_TOOLS_ID}: "
          f"{len(protocols[HAMR_TOOLS_ID].asp_args['hashfile'])} tool artifacts")
    if fe.name == "sysml":
        build_tools_protocol_dir(
            FIXTURES / SYSML_LIBS_ID, "sysml", [SYSML_LIBS_ID],
            "The SysMLv2 AADL libraries the codegen elaborates against "
            "(pinned clone): codegen INPUT measured like a tool — a "
            "contract change laundered through a library edit must fail "
            "the promotion gate's live hashes against these blessed "
            "goldens.")
        protocols[SYSML_LIBS_ID] = ProtocolDir.load(str(FIXTURES / SYSML_LIBS_ID))
        print(f"  {SYSML_LIBS_ID}: "
              f"{len(protocols[SYSML_LIBS_ID].asp_args['hashfile'])} library files")
    return protocols


def load_protocols(fe: Frontend, validate: bool = False) -> dict:
    if not all((FIXTURES / pid / "asp_args.json").is_file()
               for pid in (*fe.protocol_ids, fe.props_id)):
        print(f"{fe.prefix} protocol dirs missing — generating from the "
              "attestation report")
        protocols = build_protocol_dirs(fe)
    else:
        protocols = {pid: ProtocolDir.load(str(FIXTURES / pid))
                     for pid in (*fe.protocol_ids, fe.props_id)}
    if validate:
        protocols[fe.verus_id] = ProtocolDir.load(str(FIXTURES / fe.verus_id))
    return protocols


def provision_flow(fe: Frontend, protocols: dict,
                   bless_props: bool = False) -> None:
    """Capture golden and provision the report-derived goldens on the
    blackboard (the provisioning run signs each evidence bundle; tool
    hash goldens land measure-in-place). The props blessing is
    provisioned ONLY under --promote (bless_props) or when it has never
    been blessed (bootstrap): re-signing the model files is the
    administrator's sanctioning act, so ordinary re-provisioning —
    including a laundering pass — cannot refresh it."""
    props = protocols.get(fe.props_id)
    props_unblessed = props is not None and not any(
        a.get("golden_b64")
        for a in props.asp_args.get("readfile", {}).values())
    pids = list(fe.protocol_ids)
    if props is not None and (bless_props or props_unblessed):
        pids.append(fe.props_id)
    measured = {pid: protocols[pid] for pid in pids}
    for pid in (fe.verus_id, HAMR_TOOLS_ID, SYSML_LIBS_ID):
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


def _combined_tool_gate(client, protocols: dict, tool_ids: tuple):
    """One gate over several tools protocols (toolchain + codegen
    inputs): first drift refuses."""
    gates = [(tid, make_tool_gate(client, protocols[tid]))
             for tid in tool_ids if tid in protocols]

    def gate():
        for _, g in gates:
            error = g()
            if error:
                return error
        return None

    return gate


def print_check(fe: Frontend, protocols: dict) -> list:
    changed = changed_contracts(protocols[fe.l2], model_suffix=fe.model_suffix)
    if changed:
        print("HAMR codegen needed — model contracts changed since "
              "last provisioning:")
        for targ in changed:
            print(f"  {targ}")
    else:
        print("No model contract changes since last provisioning; "
              "codegen not needed.")
    return changed


def promote_flow(fe: Frontend, protocols: dict) -> None:
    """
    The sanctioning act, in pipeline order:

      1. detection report (informational — what is being sanctioned)
      2. promotion request alone on the blackboard; its predicate runs
         the gates and moves gold: tool gate (HAMR toolchain, and for
         SysML the pinned libraries, measured immediately before use) ->
         real codegen IN PLACE (the report regenerates — the one step
         re-provisioning alone can never do) -> proof gate (the Verus
         tier: implemented crates must still prove against the
         regenerated contracts) -> report-driven target regeneration ->
         golden capture
      3. only after the promote outcome is good: rebuild the AM-owned
         dirs from the NEW report (props blessing definition, verus
         crate list) and provision everything, props included — the
         re-blessing
      4. verification episode against the new baseline

    Steps 2 and 3 are deliberately two blackboard runs: a refused gate
    must leave the old baseline fully in place, so no provision request
    exists until the promotion outcome is known good.
    """
    print("=== sanction review (contract diff) ===")
    print_check(fe, protocols)

    print("\n=== promotion episode (gates, then gold moves) ===")
    client = CvmSubprocessClient()
    gated = {pid: protocols[pid]
             for pid in (*fe.protocol_ids, fe.props_id, fe.verus_id)}
    ctl = BlackboardController()
    ctl.register_predicate("promotion", make_promotion_predicate(
        gated, GOLDEN_ROOT,
        targets_fn=lambda: derive_report_targets(fe),
        codegen_fn=CODEGEN[fe.name],
        client=client,
        validate_with=fe.verus_id,
        tool_gate=_combined_tool_gate(client, protocols,
                                      TOOL_GATE_IDS[fe.name]),
    ))
    ctl.blackboard.write_entry(
        key=f"promote:{fe.prefix}", predicate="promotion",
        measurement=promotion_request(fe.prefix), partition="provision")
    bb = ctl.run()
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: REFUSED - {entry.result.error}")
    outcome = bb.provision[f"promote:{fe.prefix}"].result
    print(f"  promote:{fe.prefix}: {outcome.codegen}; proofs validated; "
          f"targets regenerated={outcome.targets}; "
          f"{outcome.captured} files -> golden")

    print("\n=== provisioning the new baseline (props re-blessed) ===")
    fresh = build_protocol_dirs(fe, bless_props=True)
    protocols.update(fresh)
    provision_flow(fe, protocols, bless_props=True)

    print("\n=== verification episode (new baseline) ===")
    attest_episode(fe, protocols, repair=False, validate=True)


def tamper_verus(fe: Frontend, protocols: dict) -> None:
    """Corrupt a line inside a Verus contract slice of the generated Rust."""
    l2 = protocols[fe.l2].asp_args["readfile_range"]
    targ, args = next((t, a) for t, a in sorted(l2.items())
                      if "thermostat_rt_mhs" in a["filepath"]
                      and a["filepath"].endswith(".rs"))
    rs = Path(args["filepath"])
    lines = rs.read_text().splitlines(keepends=True)
    lines[args["start_index"] - 1] = "// TAMPERED: verus contract weakened\n"
    rs.write_text("".join(lines))
    print(f"Tampered Verus slice: {rs.name} line {args['start_index']} ({targ})")


def attest_episode(fe: Frontend, protocols: dict, repair: bool,
                   validate: bool = False) -> BlackboardController:
    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate(
        "attestation", make_attestation_predicate(client, protocols))
    controller.register_predicate("protocol_check",
                                  make_readiness_predicate(
                                      protocols, baseline_root=GOLDEN_ROOT,
                                      client=client))
    fail_chain = [TierKS(protocol_id=fe.l2)]
    if repair:
        fail_chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                             refined_by=fe.l2))
    confirm = [TierKS(protocol_id=fe.verus_id)] if validate else []
    starter = StartAttestationKS(episodes={f"{fe.prefix}:files": fe.l1a})
    for ks in (*confirm, *fail_chain, starter):
        controller.add_ks(ks)
    controller.route(f"{fe.prefix}:files", on_pass=confirm, on_fail=fail_chain)
    controller.blackboard.write_entry(
        key=f"{fe.prefix}:ready", predicate="protocol_check",
        measurement=readiness_request(list(protocols)))
    controller.route(f"{fe.prefix}:ready", on_pass=[starter], on_fail=[])
    controller.run()
    print(trust_summary(controller.blackboard, semantic=[fe.verus_id]))
    return controller


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", choices=sorted(FRONTENDS),
                        default="aadl")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--tamper-verus", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--validate", action="store_true")
    cli = parser.parse_args()
    fe = FRONTENDS[cli.frontend]

    if cli.check:
        print_check(fe, load_protocols(fe))
        return
    if cli.promote:
        protocols = load_protocols(fe, validate=True)
        for tid in TOOL_GATE_IDS[fe.name]:
            if (FIXTURES / tid / "asp_args.json").is_file():
                protocols[tid] = ProtocolDir.load(str(FIXTURES / tid))
        promote_flow(fe, protocols)
        return
    if cli.provision:
        protocols = build_protocol_dirs(fe)
        provision_flow(fe, protocols)
        return

    protocols = load_protocols(fe, validate=cli.validate)
    golden = TargetSnapshot.load(
        {pid: protocols[pid] for pid in fe.protocol_ids}, GOLDEN_ROOT)
    if cli.tamper_verus:
        tamper_verus(fe, protocols)
    try:
        attest_episode(fe, protocols, repair=cli.repair, validate=cli.validate)
        if cli.repair:
            print("\n=== episode 2: verification (fresh run, fresh caches) ===")
            attest_episode(fe, protocols, repair=cli.repair,
                           validate=cli.validate)
    finally:
        restored = golden.restore()
        if restored:
            print(f"\nRestored {len(restored)} live target(s) from golden")


if __name__ == "__main__":
    main()
