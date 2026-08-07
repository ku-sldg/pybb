"""
AUTOVERUS FAILURE EXAMPLE

Proof is complete and correct and the SPECIFICATION is false, so no repair can
succeed.

    proof   eval verus (1 verified, 1 error)
      fail -> repair:autoverus acts once and cannot converge
                max_attempts exhausted, no next rung
                -> ESCALATED, carrying the repair in ks_history

--repair-steps defaults to 2 rather than 5 since running to exhaustion instead of convergence

Setup:
    1. Edit VERUS and AUTOVERUS at the top of pybb/autoverus/config.py to
       point at your own installation.
    2. Set OPENAI_API_KEY in your environment.

Usage:
    python examples/autoverus_failure_example.py [--repair-steps N] [--keep]

Exits 0 when the entry escalates
unexpected pass exits 1, because it means the fixture stopped being unfixable.
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))                   # pybb, without installing it
sys.path.insert(0, str(Path(__file__).parent))  # the success example's wiring

from pybb.autoverus import AutoVerusConfig, preflight  # noqa: E402
# One trust question, one rung, one report shape -- the difference is the
# fixture, so the wiring is imported rather than restated. print_report
# already has the escalated branch this example exists to exercise.
from autoverus_example import KEY, build_controller, print_report  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "autoverus"
UNFIXABLE = FIXTURES / "unfixable_proof.rs"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repair-steps", type=int, default=2,
                        help="AutoVerus internal repair rounds (default: 2 - "
                             "every round here runs to exhaustion)")
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
        return 1

    print(f"  verus:     {config.verus}")
    print(f"  autoverus: {config.main_py()}")
    print(f"  python:    {config.python_bin()}")

    # The rung rewrites in place even when the repair does not converge, so
    # work on a copy -- the fixture must stay unfixable for the next run.
    workdir = Path(tempfile.mkdtemp(prefix="pybb_autoverus_fail_"))
    target = workdir / UNFIXABLE.name
    shutil.copyfile(UNFIXABLE, target)
    print(f"  target:   {target} (copy of {UNFIXABLE.name})\n")

    try:
        controller = build_controller(target, cli.repair_steps, cli.keep,
                                      config)
        controller.run()
        print_report(controller, target)
        if cli.keep:
            print(f"\nworking copy kept at {workdir}")

        if KEY not in controller.blackboard.get_escalate():
            print("\nUNEXPECTED: the entry did not escalate - "
                  f"{UNFIXABLE.name} should have an unprovable postcondition")
            return 1
        return 0
    finally:
        if not cli.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
