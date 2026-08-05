"""
landing-gear_Lean — attestation-driven blackboard demo: the
classic avionics retraction interlock in Lean 4
(targets/landing-gear-lean). The lever may command retraction, but the
gear must never retract on the ground (weight-on-wheels) or below the
configured retraction speed — the safety property every airframe
certification basis states in some form.

    LandingGear/Impl.lean  computeGearCmd (proof-free): lever Down always
                           extends; lever Up retracts only airborne at or
                           above Config.retractSpeed, else holds
    LandingGear/Spec.lean  the contracts as theorems: Config.valid
                           invariant, extend_when_commanded,
                           no_retract_on_ground (the star),
                           no_retract_below_speed, retract_when_safe, and
                           the safety converse retract_only_when_safe;
                           three kernel-evaluated decide examples
    Main.lean              imports ONLY Impl — provability (gear_check)
                           and behavior (gear_exec) stay independent

This is a THIN CONFIG over examples/lean_workflow.py — the entire
workflow (gear_l1a/l2/props/check/exec/build protocols, provisioning,
episodes gear:files/proofs/behavior, tamper demos, --check/--promote) is
the shared driver; this scenario is pure configuration. The
--tamper-semantic arc removes the weight-on-wheels interlock (the Up/wow
arm flips Hold -> Retract) and launders every hash measurement by
re-provisioning: refuted twice anyway — no_retract_on_ground (and the
on-ground decide example) no longer prove, and the rebuilt binary answers
Retract to the on-ground vector against expected Hold.

Usage:
    python examples/landing_gear_lean.py [--check] [--provision]
        [--promote [--expect KEY=VALUE ...]] [--tamper]
        [--tamper-semantic] [--repair] [--validate]

See examples/lean_workflow.py for flag semantics and docs/demo_gear.md
for the demo arcs.
"""

from pathlib import Path

import lean_workflow
from lean_workflow import LeanExampleConfig

REPO = Path(__file__).parent.parent

CONFIG = LeanExampleConfig(
    prefix="gear",
    package_root=REPO / "targets" / "landing-gear-lean",
    spec_rel="LandingGear/Spec.lean",
    bin_name="landing-gear",
    # one vector per contract case: <speed> <retractSpeed> <lever> <wow|air>;
    # `expected` is AM config, not a provisioned golden — laundering
    # cannot reach it
    exec_vectors={
        "ground": {"args": ["80", "140", "Up", "wow"],
                   "expected": "gearCmd=Hold"},
        "airborne": {"args": ["180", "140", "Up", "air"],
                     "expected": "gearCmd=Retract"},
        "extend": {"args": ["200", "140", "Down", "air"],
                   "expected": "gearCmd=Extend"},
    },
    tamper_targ="gear_spec_no_retract_on_ground_targ",
    tamper_semantic_spot=(
        "LandingGear/Impl.lean",
        "| .Up, true => .Hold",
        "| .Up, true => .Retract",
        "wow interlock removed: retraction commanded on the ground"),
)

# test-facing API (tests/test_integration_gear.py)
EXEC_KEYS = CONFIG.exec_keys


def resolved_exec_targets(overrides=None):
    return lean_workflow.resolved_exec_targets(CONFIG, overrides)


def vector_failures(exec_targets, run_vector=lean_workflow._run_vector):
    return lean_workflow.vector_failures(exec_targets, run_vector)


def make_codegen_fn(exec_targets, run_vector=lean_workflow._run_vector):
    return lean_workflow.make_codegen_fn(CONFIG, exec_targets, run_vector)


if __name__ == "__main__":
    lean_workflow.run_cli(CONFIG, __doc__)
