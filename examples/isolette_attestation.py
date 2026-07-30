"""
Attestation-driven blackboard demo for the isolette — the INSPECTA
seL4/Microkit exemplar (targets/isolette-microkit: the vendored AADL model
with GUMBO contracts, plus the generated Microkit/Rust/Verus tree), with
the HAMR **attestation report** as the authoritative source of the
measurement targets and golden slices.

Protocols (generated from the report, never hand-curated):

    isl_l1a    whole-file hashes of every file the report names
               (AADL model packages + contract-bearing Rust files)
    isl_l2     readfile_range of every report slice: Model (GUMBO
               contracts in AADL) + Verus/Rust realizations in the
               generated crates
    isl_verus  [--validate] cargo-verus verify of every contract-bearing
               crate (7): the generated Verus contracts must PROVE against
               the implemented behavior

One trust question — isl:files — since every l2 slice lives inside an
l1a-hashed file:

    eval isl_l1a: pass = intact (readiness has already verified the
                  SIGNED golden baseline bundle)
      fail -> isl_l2 refines (which contract slice, model or Verus)
                fail -> [--repair] WholeFileRestoreKS restores the
                        violated files from golden; episode 2 verifies

Usage:
    python examples/isolette_attestation.py [--check] [--provision]
        [--tamper-verus] [--repair] [--validate]

--check      attestation-manager detection: compare the model's contract
             content against the provisioned golden slices
--provision  (re)generate the isl protocol dirs from the attestation
             report, capture golden, and provision via the blackboard
             (creates the signed evidence bundles readiness verifies)
--tamper-verus  corrupt a line inside a Verus contract slice of the
             generated Rust; detection/attribution (and --repair)
--validate   run the Verus semantic tier after a passing isl_l1a
             (requires the Verus toolchain; cold builds are slow)
"""

import argparse
import json
import shutil
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
    make_provision_predicate,
    make_readiness_predicate,
    readiness_request,
    request_provision,
    trust_summary,
)
from pybb.attestation.props import model_files_from_report, write_props_protocol_dir
from pybb.attestation.targetmap import (
    build_term,
    derive_targets_from_report,
    report_slices,
)
from pybb.attestation.tools import (
    build_tools_protocol_dir,
    weave_tool_measurements,
)

REPO = Path(__file__).parent.parent
ISL_ROOT = REPO / "targets" / "isolette-microkit"
REPORT = ISL_ROOT / "hamr" / "microkit" / "attestation" / "aadl_attestation_report.json"
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
PROTOCOL_IDS = ("isl_l1a", "isl_l2")
PROPS_ID = "isl_props"
TEMPLATES = {"isl_l1a": "gumbo_l1a", "isl_l2": "gumbo_l2"}
VERUS_ARGS = [
    "verify", "-Z", "build-std=core,alloc,compiler_builtins",
    "-Z", "build-std-features=compiler-builtins-mem",
    "--target", "aarch64-unknown-none", "--", "--output-json", "--time",
]


def derive_report_targets():
    """The report is the authority on targets and golden slices."""
    return derive_targets_from_report(REPORT, prefix="isl")


def verus_crates() -> list:
    """Contract-bearing crates, from the report's Verus/Rust slices."""
    crates = set()
    for s in report_slices(REPORT):
        if s["kind"] in ("Verus", "Rust") and "/crates/" in s["filepath"]:
            crates.add(s["filepath"].split("/crates/")[1].split("/")[0])
    return sorted(crates)


# Just-in-time tool measurement: the verus toolchain is hashed in the
# same term as the verification, before the use (~21 ms); the HAMR
# toolchain is measured by the promotion gate right before codegen.
TOOL_CADENCE = "per_use"
HAMR_TOOLS_ID = "hamr_tools"


def build_verus_protocol() -> ProtocolDir:
    """isl_verus: report-derived crate list, tcmk_verus session/manifest,
    verus toolchain measurements woven in per TOOL_CADENCE."""
    d = FIXTURES / "isl_verus"
    d.mkdir(exist_ok=True)
    targets = {
        f"isl_{crate}_verus_targ": {
            "exe_args": VERUS_ARGS,
            "cwd": str(ISL_ROOT / "hamr" / "microkit" / "crates" / crate),
        }
        for crate in verus_crates()
    }
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
    session = json.loads((FIXTURES / "tcmk_verus" / "session.json").read_text())
    manifest = json.loads((FIXTURES / "tcmk_verus" / "manifest.json").read_text())
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
    print(f"  isl_verus: {len(targets)} crates from report"
          + (f" + {n_tools} woven tool measurements" if n_tools else ""))
    return ProtocolDir.load(str(d))


def build_protocol_dirs() -> dict:
    """(Re)generate the isl protocol dirs from the attestation report."""
    derived = derive_report_targets()
    protocols = {}
    for pid, asp_args in derived.items():
        d = FIXTURES / pid
        d.mkdir(exist_ok=True)
        for f in ("session.json", "manifest.json"):
            shutil.copy2(FIXTURES / TEMPLATES[pid] / f, d / f)
        (d / "asp_args.json").write_text(json.dumps(asp_args, indent=2) + "\n")
        (d / "term.json").write_text(json.dumps(build_term(asp_args)) + "\n")
        protocols[pid] = ProtocolDir.load(str(d))
        print(f"  {pid}: {sum(len(t) for t in asp_args.values())} targets from report")
    model_files = model_files_from_report(REPORT)
    write_props_protocol_dir(
        FIXTURES / PROPS_ID, "isl", model_files,
        "The administrator-blessed golden spec: whole-file signed evidence "
        "of every AADL model file the report's GUMBO contract (Model) "
        "slices live in. Baseline verification checks that all hash and "
        "slice goldens are derivable from the blessed content.")
    protocols[PROPS_ID] = ProtocolDir.load(str(FIXTURES / PROPS_ID))
    print(f"  {PROPS_ID}: {len(model_files)} blessed model files")
    protocols["isl_verus"] = build_verus_protocol()
    build_tools_protocol_dir(
        FIXTURES / HAMR_TOOLS_ID, "hamr", ["hamr"],
        "The HAMR codegen + report-emitter toolchain (sireum.jar + the "
        "org.sireum OSATE plugins): measured in place at blessing, and "
        "re-measured by the promotion gate immediately before codegen.")
    protocols[HAMR_TOOLS_ID] = ProtocolDir.load(str(FIXTURES / HAMR_TOOLS_ID))
    print(f"  {HAMR_TOOLS_ID}: "
          f"{len(protocols[HAMR_TOOLS_ID].asp_args['hashfile'])} tool artifacts")
    return protocols


def load_protocols(validate: bool = False) -> dict:
    if not all((FIXTURES / pid / "asp_args.json").is_file()
               for pid in (*PROTOCOL_IDS, PROPS_ID)):
        print("isl protocol dirs missing — generating from the attestation report")
        protocols = build_protocol_dirs()
    else:
        protocols = {pid: ProtocolDir.load(str(FIXTURES / pid))
                     for pid in (*PROTOCOL_IDS, PROPS_ID)}
    if validate:
        protocols["isl_verus"] = ProtocolDir.load(str(FIXTURES / "isl_verus"))
    return protocols


def provision_flow(protocols: dict) -> None:
    """Capture golden and provision all report-derived goldens on the
    blackboard (the provisioning run signs each evidence bundle; the
    isl_props bundle is the administrator's blessing of the model files;
    tool hash goldens land measure-in-place)."""
    measured = {pid: protocols[pid] for pid in (*PROTOCOL_IDS, PROPS_ID)}
    for pid in ("isl_verus", HAMR_TOOLS_ID):
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


def tamper_verus(protocols: dict) -> None:
    """Corrupt a line inside a Verus contract slice of the generated Rust."""
    l2 = protocols["isl_l2"].asp_args["readfile_range"]
    targ, args = next((t, a) for t, a in sorted(l2.items())
                      if "thermostat_rt_mhs" in a["filepath"]
                      and a["filepath"].endswith(".rs"))
    rs = Path(args["filepath"])
    lines = rs.read_text().splitlines(keepends=True)
    lines[args["start_index"] - 1] = "// TAMPERED: verus contract weakened\n"
    rs.write_text("".join(lines))
    print(f"Tampered Verus slice: {rs.name} line {args['start_index']} ({targ})")


def attest_episode(protocols: dict, repair: bool,
                   validate: bool = False) -> BlackboardController:
    controller = BlackboardController()
    client = CvmSubprocessClient()
    controller.register_predicate(
        "attestation", make_attestation_predicate(client, protocols))
    controller.register_predicate("protocol_check",
                                  make_readiness_predicate(
                                      protocols, baseline_root=GOLDEN_ROOT,
                                      client=client))
    fail_chain = [TierKS(protocol_id="isl_l2")]
    if repair:
        fail_chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                             refined_by="isl_l2"))
    confirm = [TierKS(protocol_id="isl_verus")] if validate else []
    starter = StartAttestationKS(episodes={"isl:files": "isl_l1a"})
    for ks in (*confirm, *fail_chain, starter):
        controller.add_ks(ks)
    controller.route("isl:files", on_pass=confirm, on_fail=fail_chain)
    controller.blackboard.write_entry(
        key="isl:ready", predicate="protocol_check",
        measurement=readiness_request(list(protocols)))
    controller.route("isl:ready", on_pass=[starter], on_fail=[])
    controller.run()
    print(trust_summary(controller.blackboard, semantic=["isl_verus"]))
    return controller


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--tamper-verus", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--validate", action="store_true")
    cli = parser.parse_args()

    if cli.check:
        protocols = load_protocols()
        changed = changed_contracts(protocols["isl_l2"])
        if changed:
            print("HAMR codegen needed — model contracts changed since "
                  "last provisioning:")
            for targ in changed:
                print(f"  {targ}")
        else:
            print("No model contract changes since last provisioning; "
                  "codegen not needed.")
        return
    if cli.provision:
        protocols = build_protocol_dirs()
        provision_flow(protocols)
        return

    protocols = load_protocols(validate=cli.validate)
    golden = TargetSnapshot.load(
        {pid: protocols[pid] for pid in PROTOCOL_IDS}, GOLDEN_ROOT)
    if cli.tamper_verus:
        tamper_verus(protocols)
    try:
        attest_episode(protocols, repair=cli.repair, validate=cli.validate)
        if cli.repair:
            print("\n=== episode 2: verification (fresh run, fresh caches) ===")
            attest_episode(protocols, repair=cli.repair, validate=cli.validate)
    finally:
        restored = golden.restore()
        if restored:
            print(f"\nRestored {len(restored)} live target(s) from golden")


if __name__ == "__main__":
    main()
