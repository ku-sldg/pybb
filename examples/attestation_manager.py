"""
Out-of-band attestation manager for the temp-control model.

The manager (or its administrator) is the sanctioned actor of the
promotion pipeline: it re-measures the AADL models on demand and, when
contracts changed since last provisioning, places a promotion request on
the blackboard — kicking off HAMR codegen, target-map regeneration, a
golden-directory update, and fresh provisioning. Sanction assumption:
AADL edits at this level are authorized; the manager is the authorization
point.

Commands:
    check     re-measure AADL contract content against last-provisioned
              goldens (position-independent); report whether HAMR codegen
              is needed
    promote   write the promote + provisioning requests, run the promotion
              episode, then a verification episode (readiness + both
              attestation entries against the new baseline)
    watch     poll `check` every --interval seconds until a change appears

Flags:
    --demo-edit     apply a sanctioned contract change to the live AADL
                    model first (SetPoint upper bound 110.0 -> 112.0),
                    and restore the original live tree at the end
    --in-place      operate on the repo's protocol dirs and golden/ for
                    real (default: scratch copies, repo state untouched)
    --validate      opt-in semantic gate at promotion (sireum, ~minutes)
    --codegen-cmd   override the codegen invocation with a shell command.
                    Default is the REAL HAMR run: phantom (AADL -> AIR via
                    headless OSATE) + `hamr codegen -p JVM` regenerating
                    the live slang project (requires the standalone Sireum
                    toolchain at ~/Applications/Sireum).
"""

import argparse
import base64
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    StartAttestationKS,
    TargetSnapshot,
    TierKS,
    make_attestation_predicate,
    make_promotion_predicate,
    make_provision_predicate,
    make_readiness_predicate,
    readiness_request,
    request_promotion,
    trust_summary,
)
from pybb.attestation.targetmap import TEMP_CONTROL_SPEC

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
GOLDEN_ROOT = Path(__file__).parent.parent / "golden"
TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")
PROTOCOL_IDS = ("gumbo_l1a", "gumbo_l1b", "gumbo_l2")


def _normalize(s: str) -> str:
    return "".join(s.split())


def changed_contracts(protocols: dict) -> list[str]:
    """
    Contract slices from last provisioning whose content no longer appears
    in the (sanctioned) current AADL models. Position-independent, so a
    merely-moved contract does not read as changed.
    """
    aadl_paths = {fp for fp, _ in TEMP_CONTROL_SPEC["aadl"]}
    texts = {fp: _normalize(Path(fp).read_text()) for fp in aadl_paths}
    changed = []
    for targ, args in protocols["gumbo_l2"].asp_args.get("readfile_range", {}).items():
        fp, golden = args.get("filepath"), args.get("golden_b64")
        if fp not in texts or not golden:
            continue
        content = _normalize(base64.b64decode(golden).decode())
        if content not in texts[fp]:
            changed.append(targ)
    return changed


def sanctioned_demo_edit() -> None:
    """The administrator revises the SetPoint invariant (110.0 -> 112.0)."""
    aadl = TC_ROOT / "aadl/packages/TempControlSystem.aadl"
    text = aadl.read_text()
    assert 'f32"110.0"' in text, "demo edit expects the 110.0 bound"
    aadl.write_text(text.replace('f32"110.0"', 'f32"112.0"', 1))
    print(f"Sanctioned edit applied: {aadl.name} SetPoint bound 110.0 -> 112.0")


def load_working_set(in_place: bool):
    """Protocol dirs + golden root: repo state, or scratch copies of it."""
    if in_place:
        root, golden = FIXTURES, GOLDEN_ROOT
    else:
        scratch = Path(tempfile.mkdtemp(prefix="pybb_am_"))
        golden = scratch / "golden"
        shutil.copytree(GOLDEN_ROOT, golden)
        for pid in PROTOCOL_IDS:
            shutil.copytree(FIXTURES / pid, scratch / pid)
        root = scratch
        print(f"Scratch working set at {scratch}")
    protocols = {pid: ProtocolDir.load(str(root / pid)) for pid in PROTOCOL_IDS}
    return protocols, golden


SIREUM_STANDALONE = Path.home() / "Applications/Sireum/bin/sireum"


def hamr_jvm_codegen() -> str:
    """
    The real HAMR run: phantom (AADL -> AIR via headless OSATE) then
    codegen -p JVM into the live slang project. Generated files are
    overwritten; developer component files are not (HAMR contract).
    Requires the standalone Sireum + OSATE toolchain; pass --codegen-cmd
    to substitute a different invocation.
    """
    if not SIREUM_STANDALONE.is_file():
        raise RuntimeError(
            f"standalone Sireum not found at {SIREUM_STANDALONE} — install it "
            "(git clone sireum/kekinian + bin/init.sh; sireum hamr phantom -u) "
            "or pass --codegen-cmd")
    env = {**os.environ,
           "SIREUM_CACHE": str(Path.home() / "Claude_workspace/.sireum_cache")}
    with tempfile.TemporaryDirectory(prefix="pybb_air_") as tmp:
        air = Path(tmp) / "TempControlSystem_i.json"
        subprocess.run(
            [str(SIREUM_STANDALONE), "hamr", "phantom", "-f", str(air),
             str(TC_ROOT / "aadl")],
            check=True, env=env)
        subprocess.run(
            [str(SIREUM_STANDALONE), "hamr", "codegen", "-p", "JVM",
             "--package-name", "tc",
             "--slang-output-dir", str(TC_ROOT / "slang"),
             "--no-proyek-ive", str(air)],
            check=True, env=env)
    return "ran: sireum hamr phantom + codegen -p JVM (live slang regenerated)"


def make_codegen_fn(cmd: str | None):
    if cmd:
        def run() -> str:
            subprocess.run(cmd, shell=True, check=True, cwd=TC_ROOT)
            return f"ran: {cmd}"
        return run
    return hamr_jvm_codegen


def cmd_check(protocols) -> list[str]:
    changed = changed_contracts(protocols)
    if changed:
        print("HAMR codegen needed — contracts changed since last provisioning:")
        for targ in changed:
            print(f"  {targ}")
    else:
        print("No contract changes since last provisioning; codegen not needed.")
    return changed


def cmd_promote(protocols, golden_root, cli) -> None:
    client = CvmSubprocessClient()
    controller = BlackboardController()
    if cli.validate:
        protocols["gumbo_validation"] = ProtocolDir.load(
            str(FIXTURES / "gumbo_validation"))
    controller.register_predicate("promotion", make_promotion_predicate(
        protocols, golden_root, TEMP_CONTROL_SPEC,
        codegen_fn=make_codegen_fn(cli.codegen_cmd),
        client=client,
        validate_with="gumbo_validation" if cli.validate else None,
    ))
    controller.register_predicate("provision", make_provision_predicate(
        client, protocols, golden_root))
    request_promotion(controller.blackboard, "gumbo", list(PROTOCOL_IDS))
    controller.run()
    bb = controller.blackboard

    print("\n=== promotion episode (provision partition) ===")
    for key, entry in bb.get_provision().items():
        outcome = entry.result
        if key.startswith("promote:"):
            print(f"  {key}: codegen={outcome.codegen}; "
                  f"targets regenerated={outcome.targets}; "
                  f"{outcome.captured} files -> golden")
        else:
            print(f"  {key}: {len(outcome.provisioned)} goldens provisioned")
    for key, entry in bb.get_escalate().items():
        print(f"  {key}: FAILED - {entry.result.error}")
        return

    print("\n=== verification episode (new baseline) ===")
    verifier = BlackboardController()
    verifier.register_predicate("attestation",
                                make_attestation_predicate(client, protocols))
    verifier.register_predicate("protocol_check",
                                make_readiness_predicate(protocols))
    starter = StartAttestationKS(episodes={"gumbo:files": "gumbo_l1a",
                                           "gumbo:contracts": "gumbo_l1b"})
    refine = TierKS(protocol_id="gumbo_l2")
    for ks in (starter, refine):
        verifier.add_ks(ks)
    verifier.route("gumbo:files", on_fail=[refine])
    verifier.route("gumbo:contracts", on_fail=[])
    verifier.blackboard.write_entry(
        key="gumbo:ready", predicate="protocol_check",
        measurement=readiness_request(list(PROTOCOL_IDS)))
    verifier.route("gumbo:ready", on_pass=[starter], on_fail=[])
    verifier.run()
    print("  " + trust_summary(verifier.blackboard).replace("\n", "\n  "))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "promote", "watch"])
    parser.add_argument("--demo-edit", action="store_true")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--codegen-cmd", default=None)
    parser.add_argument("--interval", type=int, default=30)
    cli = parser.parse_args()

    # snapshot of the CURRENT baseline, to restore the live tree after a demo edit
    original = TargetSnapshot.load(
        {pid: ProtocolDir.load(str(FIXTURES / pid)) for pid in PROTOCOL_IDS},
        GOLDEN_ROOT,
    ) if cli.demo_edit else None

    try:
        if cli.demo_edit:
            sanctioned_demo_edit()
        protocols, golden_root = load_working_set(cli.in_place)

        if cli.command == "check":
            cmd_check(protocols)
        elif cli.command == "promote":
            cmd_promote(protocols, golden_root, cli)
        elif cli.command == "watch":
            while not cmd_check(protocols):
                time.sleep(cli.interval)
            print("Run `promote` to make the change the new baseline.")
    finally:
        if original is not None:
            restored = original.restore()
            if restored:
                print(f"\nDemo cleanup: restored {len(restored)} live "
                      f"target(s) to the original baseline")


if __name__ == "__main__":
    main()
