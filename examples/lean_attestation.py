"""
Attestation-driven blackboard demo for the Lean pipeline: the temp-control
model ported to Lean 4 (targets/temp-control-lean) — a specification
(TempControl/Spec.lean, the GUMBO compute contracts as theorems) over a
proof-free implementation (TempControl/Impl.lean) that the executable
(Main.lean) is built from. Measurement targets derive from a syntax scan
of the package (derive_targets_from_lean); l2 slices are named by
declaration, so attribution names the tampered theorem.

This is a THIN CONFIG over examples/lean_workflow.py — the shared driver
holds the whole workflow (protocols, provisioning, episodes, tamper
demos, --check/--promote); a second Lean scenario is pure configuration
(see examples/gear_attestation.py). The driver builds:

    lean_l1a   whole-file hashes: every .lean source + lakefile.toml +
               lean-toolchain (build config and toolchain pin are inside
               the trust boundary)
    lean_l2    readfile_range per top-level declaration (attribution)
    lean_check `lake lean TempControl/Spec.lean -- --json`: every theorem
               must still PROVE (fails on error diagnostics and hasSorry —
               a sorry exits 0, so exit codes alone would bless it)
    lean_exec  hash-then-run of the PINNED built binary: its hash must
               match the build-anchored golden, then it is executed
               directly (lake env <binary>, never rebuilt) per GUMBO case;
               stdout must equal the expected command. Main imports only
               TempControl.Impl, so provability and behavior stay
               independent measurements.
    lean_build the build event, run at provisioning: toolchain -> input
               sources -> lake build -> output binary, one signature
    lean_props the administrator-blessed golden spec (Spec.lean signed
               whole-file); re-blessed ONLY by --promote

Three independent trust questions, three always-run entries:

    lean:files     eval lean_l1a: fail -> lean_l2 refines (which
                   declaration) -> [--repair] WholeFileRestoreKS
    lean:proofs    [--validate] eval lean_check: fail escalates directly
    lean:behavior  [--validate] eval lean_exec: fail escalates directly

Two artifacts are owned by the out-of-band attestation manager and change
ONLY through --promote (the administrator's sanctioning act): the
lean_props blessing, and the exec expecteds (behavior vectors' expected
outputs — sanctioned via --expect, e.g. --expect hot=fanCmd=Off).

Usage:
    python examples/lean_attestation.py [--check] [--provision]
        [--promote [--expect KEY=VALUE ...]] [--tamper]
        [--tamper-semantic] [--repair] [--validate]

See examples/lean_workflow.py for flag semantics and docs/demo_lean.md
for the demo arcs (structural tamper + repair, laundered semantic tamper
with double refutation, sanctioned change).
"""

from pathlib import Path

import lean_workflow
from lean_workflow import LeanExampleConfig

REPO = Path(__file__).parent.parent

CONFIG = LeanExampleConfig(
    prefix="lean",
    package_root=REPO / "targets" / "temp-control-lean",
    spec_rel="TempControl/Spec.lean",
    bin_name="temp-control",
    # one vector per GUMBO case; `expected` is AM config, not a
    # provisioned golden — laundering cannot reach it
    exec_vectors={
        "hot": {"args": ["101", "70", "90", "Off"], "expected": "fanCmd=On"},
        "cold": {"args": ["60", "70", "90", "On"], "expected": "fanCmd=Off"},
        "hold": {"args": ["80", "70", "90", "On"], "expected": "fanCmd=On"},
    },
    tamper_targ="lean_spec_fanOn_when_hot_targ",
    tamper_semantic_spot=(
        "TempControl/Impl.lean",
        "if temp > sp.high then .On",
        "if temp > sp.high then .Off",
        "computeFanCmd hot branch .On -> .Off"),
)

# test-facing API (tests/test_integration_lean.py)
EXEC_KEYS = CONFIG.exec_keys


def resolved_exec_targets(overrides=None):
    return lean_workflow.resolved_exec_targets(CONFIG, overrides)


def vector_failures(exec_targets, run_vector=lean_workflow._run_vector):
    return lean_workflow.vector_failures(exec_targets, run_vector)


def make_codegen_fn(exec_targets, run_vector=lean_workflow._run_vector):
    return lean_workflow.make_codegen_fn(CONFIG, exec_targets, run_vector)


if __name__ == "__main__":
    lean_workflow.run_cli(CONFIG, __doc__)
