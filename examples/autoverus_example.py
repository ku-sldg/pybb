"""
AUTOVERUS REPAIR EXAMPLE

A Rust file carries a Verus contract and a loop invariant that is present
but incomplete, so its proof fails. The blackboard asks "does this file
verify?", AutoVerus answers the failure by repairing the proof, and the
same run re-verifies the result -- detect, repair, confirm, in one
controller.run().

    proof   eval verus (1 verified, 1 error)
      fail -> repair:autoverus rewrites the file and re-measures it
                pass = repaired and verified
                fail = escalated, carrying the repair in ks_history

Independent of the attestation stack.

Setup:
    1. Edit VERUS and AUTOVERUS at the top of pybb/autoverus/config.py to
       point at your own installation.
    2. Set OPENAI_API_KEY in your environment.

Usage:
    python examples/autoverus_example.py [--repair-steps N] [--keep]
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))  # run from a checkout without installing pybb

from pybb import BlackboardController  # noqa: E402
from pybb.autoverus import (  # noqa: E402
    AutoVerusConfig,
    AutoVerusRepairKS,
    make_verus_predicate,
    preflight,
    source_measurement,
)

FIXTURES = REPO / "tests" / "fixtures" / "autoverus"
BROKEN = FIXTURES / "broken_proof.rs"
KEY = "proof"


def build_controller(target: Path, repair_steps: int, keep_intermediate: bool,
                     config: AutoVerusConfig) -> BlackboardController:
    """One episode's controller: fresh predicate, fresh memo cache."""
    controller = BlackboardController()
    rung = AutoVerusRepairKS(repair_steps=repair_steps,
                             keep_intermediate=keep_intermediate,
                             config=config,
                             allow_llm=True)  # armed by --autoverus in main()
    controller.register_predicate("verus", make_verus_predicate(config=config))
    controller.add_ks(rung)  # eligible to run...
    controller.blackboard.write_entry(
        key=KEY, predicate="verus", measurement=source_measurement(target))
    controller.route(KEY, [rung])  # ...and given the key on failure
    return controller


def print_report(controller: BlackboardController, target: Path) -> None:
    blackboard = controller.blackboard
    escalated = KEY in blackboard.get_escalate()
    entry = blackboard.get_escalate().get(KEY) if escalated \
        else blackboard.get_entry(KEY)

    print(f"\ncycles: {controller.cycle_count}")
    print("verdict trail:")
    # History also snapshots bookkeeping writes (ks_history updates re-save an
    # already-evaluated entry), so collapse repeats of the same verdict.
    last = None
    for key, snapshot in blackboard.get_history():
        if key != KEY or snapshot.result is None:
            continue
        line = f"{'pass' if snapshot.good_standing else 'FAIL'}  " \
               f"{snapshot.result.summary()}"
        if line != last:
            print(f"  {line}")
            last = line

    if entry is None:
        print(f"\n{KEY}: no entry (nothing ran)")
        return
    repairs = entry.ks_history.get("repair:autoverus", 0)
    if escalated:
        # `if entry.result` would be wrong: VerusResult truthiness IS the
        # verdict, so a failing result is falsy -- and an escalated entry's
        # result is failing precisely when there is something to report.
        verdict = "no verdict" if entry.result is None \
            else entry.result.summary()
        print(f"\n{KEY}: ESCALATED after {repairs} repair attempt(s) - "
              f"{verdict}")
    elif entry.good_standing and repairs:
        print(f"\n{KEY}: verified after AutoVerus repair "
              f"({entry.result.summary()})")
    elif entry.good_standing:
        print(f"\n{KEY}: verified with no repair needed "
              f"({entry.result.summary()})")
    print(f"ks_history: {entry.ks_history}")
    print(f"\nrepaired file: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repair-steps", type=int, default=5,
                        help="AutoVerus internal repair rounds (default: 5)")
    parser.add_argument("--keep", action="store_true",
                        help="keep the working copy and AutoVerus's "
                             "intermediate-*/ directories for inspection")
    parser.add_argument("--autoverus", action="store_true",
                        help="explicit confirmation: this run may call the "
                             "OpenAI API via AutoVerus (key read from the "
                             "OPENAI_API_KEY environment variable only)")
    cli = parser.parse_args()

    if not cli.autoverus:
        raise SystemExit(
            "This example calls an LLM API (OpenAI, via AutoVerus). "
            "Pass --autoverus to confirm; the key is read from "
            "OPENAI_API_KEY and never stored.")

    config = AutoVerusConfig()
    print("preflight...")
    problems = preflight(config)
    if problems:
        print("\ncannot run - the environment does not support a real run:")
        for problem in problems:
            print(f"  - {problem}")
        raise SystemExit(1)

    print(f"  verus:     {config.verus}")
    print(f"  autoverus: {config.main_py()}")
    print(f"  python:    {config.python_bin()}")

    # Repair rewrites the file in place, so work on a copy -- otherwise the
    # second run of this demo would start from an already-repaired fixture.
    workdir = Path(tempfile.mkdtemp(prefix="pybb_autoverus_demo_"))
    target = workdir / BROKEN.name
    shutil.copyfile(BROKEN, target)
    print(f"  target:   {target} (copy of {BROKEN.name})\n")

    try:
        controller = build_controller(target, cli.repair_steps, cli.keep,
                                      config)
        controller.run()
        print_report(controller, target)
        if cli.keep:
            print(f"\nworking copy kept at {workdir}")
    finally:
        if not cli.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
