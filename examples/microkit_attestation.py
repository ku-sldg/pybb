"""
Attestation-driven blackboard demo for the Microkit/Rust/Verus pipeline:
the temp-control model ported to seL4 Microkit (targets/temp-control-microkit),
with the HAMR **attestation report** as the authoritative source of the
measurement targets and golden slices.

Protocols (generated from the report, never hand-curated):

    tcmk_l1a  whole-file hashes of every file the report names
              (2 AADL models + 2 contract-bearing Rust files)
    tcmk_l2   readfile_range of every report slice: Model (GUMBO
              contracts in AADL) + Verus/Rust realizations in the
              generated crates

One trust question — tcmk:files — since every l2 slice lives inside an
l1a-hashed file (no safe-to-edit component class here; generated Rust is
whole-file-immutable):

    eval tcmk_l1a: pass = intact
      fail -> tcmk_l2 refines (which contract slice, model or Verus)
                fail -> [--repair] WholeFileRestoreKS restores the
                        violated files from golden -> repaired, pending;
                        episode 2 verifies

Usage:
    python examples/microkit_attestation.py [--check] [--provision]
        [--promote] [--tamper-verus] [--repair] [--validate]

--check      attestation-manager detection: compare the model's contract
             content against the provisioned golden slices (position-
             independent); reports whether HAMR codegen is needed

--validate   semantic tier: a passing tcmk_l1a is provisional until
             tcmk_verus confirms — cargo-verus verify must PROVE the
             generated Verus contracts against the implemented behavior
             of both crates (requires the Verus toolchain and rust)

--provision  (re)generate the tcmk protocol dirs from the attestation
             report, capture golden, and provision via the blackboard
--promote    the full lifecycle: real Microkit codegen (phantom + hamr
             codegen -p Microkit, standalone toolchain required) ->
             report regenerated -> report-driven target regeneration ->
             gold moves -> provisioning -> verification episode
--tamper-verus  corrupt a line inside a Verus contract slice of the
             generated Rust; detection/attribution (and --repair)
"""

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    attestation_request,
    make_attestation_predicate,
    make_promotion_predicate,
    changed_contracts,
    make_provision_predicate,
    make_readiness_predicate,
    readiness_request,
    request_promotion,
    request_provision,
    trust_summary,
)
from pybb.attestation.targetmap import build_term, derive_targets_from_report

REPO = Path(__file__).parent.parent
TCMK_ROOT = REPO / "targets" / "temp-control-microkit"
REPORT = TCMK_ROOT / "hamr" / "microkit" / "attestation" / "aadl_attestation_report.json"
FIXTURES = REPO / "tests" / "fixtures"
GOLDEN_ROOT = REPO / "golden"
PROTOCOL_IDS = ("tcmk_l1a", "tcmk_l2")
TEMPLATES = {"tcmk_l1a": "gumbo_l1a", "tcmk_l2": "gumbo_l2"}
SIREUM_STANDALONE = Path.home() / "Applications/Sireum/bin/sireum"


def derive_report_targets():
    """The report is the authority on targets and golden slices."""
    return derive_targets_from_report(REPORT, prefix="tcmk")


def build_protocol_dirs() -> dict:
    """(Re)generate the tcmk protocol dirs from the attestation report."""
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
    return protocols


def load_protocols() -> dict:
    if not all((FIXTURES / pid / "asp_args.json").is_file() for pid in PROTOCOL_IDS):
        print("tcmk protocol dirs missing — generating from the attestation report")
        return build_protocol_dirs()
    return {pid: ProtocolDir.load(str(FIXTURES / pid)) for pid in PROTOCOL_IDS}


def hamr_microkit_codegen() -> str:
    """Real Microkit codegen: phantom -> AIR -> codegen (report regenerates)."""
    if not SIREUM_STANDALONE.is_file():
        raise RuntimeError(
            f"standalone Sireum not found at {SIREUM_STANDALONE} — install it "
            "(git clone sireum/kekinian + bin/init.sh; sireum hamr phantom -u)")
    env = {**os.environ,
           "SIREUM_CACHE": str(Path.home() / "Claude_workspace/.sireum_cache")}
    with tempfile.TemporaryDirectory(prefix="pybb_air_") as tmp:
        air = Path(tmp) / "TempControlSystem_i.json"
        subprocess.run([str(SIREUM_STANDALONE), "hamr", "phantom", "-f", str(air),
                        str(TCMK_ROOT / "aadl")], check=True, env=env)
        subprocess.run([str(SIREUM_STANDALONE), "hamr", "codegen", "-p", "Microkit",
                        "--package-name", "tc",
                        "--output-dir", str(TCMK_ROOT / "hamr"),
                        "--workspace-root-dir", str(TCMK_ROOT / "aadl"),
                        str(air)], check=True, env=env)
    return "ran: sireum hamr phantom + codegen -p Microkit (report regenerated)"


def provision_flow(protocols: dict) -> None:
    """Capture golden and provision all report-derived goldens on the blackboard."""
    snapshot = TargetSnapshot.capture(protocols, dest=GOLDEN_ROOT)
    print(f"golden captured: {len(snapshot.files)} files")
    client = CvmSubprocessClient()
    ctl = BlackboardController()
    ctl.register_predicate("provision",
                           make_provision_predicate(client, protocols, GOLDEN_ROOT))
    for pid in protocols:
        request_provision(ctl.blackboard, pid)
    bb = ctl.run()
    for key, entry in bb.get_provision().items():
        print(f"  {key}: {len(entry.result.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: FAILED - {entry.result.error}")


def promote_flow(protocols: dict) -> None:
    """Full lifecycle: real codegen -> report-driven targets -> gold -> goldens."""
    client = CvmSubprocessClient()
    ctl = BlackboardController()
    ctl.register_predicate("promotion", make_promotion_predicate(
        protocols, GOLDEN_ROOT,
        codegen_fn=hamr_microkit_codegen,
        targets_fn=derive_report_targets,
    ))
    ctl.register_predicate("provision",
                           make_provision_predicate(client, protocols, GOLDEN_ROOT))
    request_promotion(ctl.blackboard, "tcmk", list(PROTOCOL_IDS))
    bb = ctl.run()
    for key, entry in bb.get_provision().items():
        o = entry.result
        if key.startswith("promote:"):
            print(f"  {key}: codegen={o.codegen}; targets={o.targets}; "
                  f"{o.captured} files -> golden")
        else:
            print(f"  {key}: {len(o.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        raise SystemExit(f"  {key}: FAILED - {entry.result.error}")


def tamper_verus(protocols: dict) -> None:
    """Corrupt a line inside a Verus contract slice of the generated Rust."""
    l2 = protocols["tcmk_l2"].asp_args["readfile_range"]
    targ, args = next((t, a) for t, a in sorted(l2.items())
                      if a["filepath"].endswith("tcproc_tempControl_app.rs"))
    rs = Path(args["filepath"])
    lines = rs.read_text().splitlines(keepends=True)
    lines[args["start_index"] - 1] = "// TAMPERED: verus contract weakened\n"
    rs.write_text("".join(lines))
    print(f"Tampered Verus slice: {rs.name} line {args['start_index']} ({targ})")


def attest_episode(protocols: dict, repair: bool,
                   validate: bool = False) -> BlackboardController:
    controller = BlackboardController()
    controller.register_predicate(
        "attestation", make_attestation_predicate(CvmSubprocessClient(), protocols))
    controller.register_predicate("protocol_check",
                                  make_readiness_predicate(protocols))
    fail_chain = [TierKS(protocol_id="tcmk_l2")]
    if repair:
        fail_chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                             refined_by="tcmk_l2"))
    confirm = [TierKS(protocol_id="tcmk_verus")] if validate else []
    starter = StartAttestationKS(episodes={"tcmk:files": "tcmk_l1a"})
    for ks in (*confirm, *fail_chain, starter):
        controller.add_ks(ks)
    controller.route("tcmk:files", on_pass=confirm, on_fail=fail_chain)
    checked = list(PROTOCOL_IDS) + (["tcmk_verus"] if validate else [])
    controller.blackboard.write_entry(
        key="tcmk:ready", predicate="protocol_check",
        measurement=readiness_request(checked))
    controller.route("tcmk:ready", on_pass=[starter], on_fail=[])
    controller.run()
    print(trust_summary(controller.blackboard, semantic=["tcmk_verus"]))
    return controller


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--provision", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--tamper-verus", action="store_true")
    parser.add_argument("--repair", action="store_true")
    parser.add_argument("--validate", action="store_true")
    cli = parser.parse_args()

    if cli.check:
        protocols = load_protocols()
        changed = changed_contracts(protocols["tcmk_l2"])
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
    protocols = load_protocols()
    if cli.validate:
        protocols["tcmk_verus"] = ProtocolDir.load(str(FIXTURES / "tcmk_verus"))
    if cli.promote:
        promote_flow(protocols)
        print("\n=== verification episode (new baseline) ===")
        attest_episode(protocols, repair=False)
        return

    golden = TargetSnapshot.load(protocols, GOLDEN_ROOT)
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
