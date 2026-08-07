"""
temp-control-goals_Lean — the GOAL-DIRECTED encoding pilot: the
administrator blesses abstract goal PROPERTIES (statements, not proofs);
proofs, the implementation, and any intermediate lemmas are workflow-owned
and freely mutable. The invariant the attestation enforces: the blessed
properties remain untouched (targets/temp-control-goals).

    TempControl/Props.lean       BLESSED: self-contained statements file —
                                 types, the Step interface shape, four goal
                                 props parameterized over any candidate
                                 implementation, and the Spec conjunction.
                                 No imports, no theorems, no proofs
                                 (bless_lint enforces this).
    TempControl/Acceptance.lean  BLESSED: the two-line obligation binding —
                                 `example : Spec computeFanCmd := spec_holds`
                                 fails to elaborate if spec_holds is
                                 missing, renamed, or weaker than the
                                 blessed obligation.
    TempControl/Impl.lean        mutable: the implementation candidate.
    TempControl/Proofs.lean      mutable: seed proofs (may be modified,
                                 replaced, or used as guidance) +
                                 spec_holds + intermediate lemmas.
    Main.lean                    imports ONLY Impl — provability and
                                 behavior stay independent measurements.

Encoding consequences (vs the classic temp-control_Lean scenario):
  - the model class blesses Props.lean AND Acceptance.lean; contracts
    slices cover ONLY the blessed files (mutable files carry no structural
    goldens — their attested properties are provability and pinned-binary
    behavior);
  - the verification class has TWO targets: Proofs.lean (every proof must
    elaborate; error diagnostics and hasSorry refute — diagnostics of
    imported modules do not reach a target's JSON stream, so Proofs must
    be a target itself) and Acceptance.lean (the coverage/obligation
    check);
  - editing a proof body or adding a lemma in Proofs.lean leaves every
    structural measurement green — the mutability the goal-directed
    workflow requires;
  - blessing is gated by bless_lint: Props.lean must elaborate standalone
    with clean diagnostics and contain only statement declarations
    (def/abbrev/structure/inductive); Acceptance.lean must match the
    canonical binding.

This is a THIN CONFIG over examples/lean_workflow.py; the whole workflow
(protocols, provisioning, episodes, tamper demos, --check/--promote) is
the shared driver.

Usage:
    python examples/temp_control_goals_lean.py [--check] [--provision]
        [--promote [--expect KEY=VALUE ...]] [--tamper]
        [--tamper-semantic] [--repair] [--validate]

See examples/lean_workflow.py for flag semantics and docs/demo_goals.md
for the demo arcs.
"""

import json
import subprocess
from pathlib import Path

import lean_workflow
from lean_workflow import LeanExampleConfig

from pybb.attestation import LlmEngine, TacticPortfolioEngine

REPO = Path(__file__).parent.parent
PACKAGE = REPO / "targets" / "temp-control-goals"

PROPS_REL = "TempControl/Props.lean"
PROOFS_REL = "TempControl/Proofs.lean"
ACCEPTANCE_REL = "TempControl/Acceptance.lean"

# The blessed statements file admits only statement declarations.
STATEMENT_KINDS = {"def", "abbrev", "structure", "inductive"}


def acceptance_canon() -> str:
    """The canonical obligation binding — Acceptance.lean must be exactly
    this (checked at blessing time; its bytes are then blessed, so live
    tamper of the check itself is caught by the model class)."""
    return (
        "/- BLESSED obligation binding: the live tree must prove exactly the\n"
        "   blessed Spec for the sanctioned implementation. Fails to elaborate if\n"
        "   spec_holds is missing, renamed, or has any weaker type. -/\n"
        "import TempControl.Proofs\n"
        "\n"
        "example : TempControl.Spec TempControl.computeFanCmd := "
        "TempControl.spec_holds\n")


def bless_lint(cfg: LeanExampleConfig) -> None:
    """Refuse a blessing whose statements file is not purely statements
    (or does not elaborate standalone), or whose obligation binding is
    not the canonical one. Raises SystemExit with every problem found."""
    from pybb.attestation.targetmap import lean_decl_spans

    problems = []
    props = cfg.package_root / PROPS_REL
    out = subprocess.run(
        [str(lean_workflow.LAKE), "lean", PROPS_REL, "--", "--json"],
        cwd=cfg.package_root, capture_output=True, text=True)
    if out.returncode != 0:
        problems.append(
            f"{PROPS_REL} does not elaborate standalone (exit {out.returncode})")
    for line in out.stdout.splitlines():
        try:
            diag = json.loads(line)
        except ValueError:
            continue
        if diag.get("severity") == "error" or diag.get("kind") == "hasSorry":
            data = " ".join(str(diag.get("data", "")).split())[:100]
            problems.append(f"{PROPS_REL}: {diag.get('severity')}"
                            f"{' [hasSorry]' if diag.get('kind') == 'hasSorry' else ''}"
                            f": {data}")
    for kind, name, start, _end in lean_decl_spans(props.read_text()):
        if kind not in STATEMENT_KINDS:
            label = f"{kind} {name}" if name else kind
            problems.append(
                f"{PROPS_REL}:{start}: '{label}' — the blessed statements "
                f"file admits only {'/'.join(sorted(STATEMENT_KINDS))} "
                "(proofs and implementations are workflow-owned)")
    live = (cfg.package_root / ACCEPTANCE_REL).read_text()
    if live != acceptance_canon():
        problems.append(f"{ACCEPTANCE_REL} differs from the canonical "
                        "obligation binding")
    if problems:
        raise SystemExit("blessing refused:\n  " + "\n  ".join(problems))


CONFIG = LeanExampleConfig(
    prefix="temp_control_goals_lean",
    package_root=PACKAGE,
    spec_rel=PROPS_REL,
    bin_name="temp-control-goals",
    # one vector per goal-property case; `expected` is AM config, not a
    # provisioned golden — laundering cannot reach it
    exec_vectors={
        "hot":  {"args": ["101", "70", "90", "Off"], "expected": "fanCmd=On"},
        "cold": {"args": ["60", "70", "90", "On"], "expected": "fanCmd=Off"},
        "hold": {"args": ["80", "70", "90", "On"], "expected": "fanCmd=On"},
    },
    tamper_targ="temp_control_goals_lean_props_fanOn_when_hot_prop_targ",
    tamper_semantic_spot=(
        "TempControl/Impl.lean",
        "if temp > sp.high then .On",
        "if temp > sp.high then .Off",
        "hot branch flipped On -> Off"),
    # goal-directed encoding: blessed statements + obligation binding;
    # contracts scoped to the blessed files; two verification targets
    model_rels=[PROPS_REL, ACCEPTANCE_REL],
    contracts_files=[PROPS_REL, ACCEPTANCE_REL],
    verification_targets_override={
        "temp_control_goals_lean_proofs_verification_targ": {
            "exe_args": ["lean", PROOFS_REL, "--", "--json"],
            "cwd": str(PACKAGE)},
        "temp_control_goals_lean_acceptance_verification_targ": {
            "exe_args": ["lean", ACCEPTANCE_REL, "--", "--json"],
            "cwd": str(PACKAGE)},
    },
    bless_lint=bless_lint,
    # --status: the goals checklist (rows = blessed Spec conjuncts;
    # witnesses scanned from the mutable proofs file; the binding row =
    # the acceptance component's verdict)
    witness_rel=PROOFS_REL,
    proofs_targ="temp_control_goals_lean_proofs_verification_targ",
    binding_targ="temp_control_goals_lean_acceptance_verification_targ",
    # --repair is judged by fresh measurement IN-SESSION (restart-episode
    # primitive): tamper -> attribution -> repair -> re-attest, one run
    restart_budget=1,
    # --synthesize: the engine ladder (cheap deterministic tactic search
    # first; the LLM slot ships with no backend — plug complete= in to arm
    # it; end-of-route escalation is the human rung)
    synthesis_engines=[TacticPortfolioEngine(), LlmEngine()],
    impl_name="computeFanCmd",
    # LLM-engine context + the --break-proof repair arc's target
    impl_rel="TempControl/Impl.lean",
    break_proof_decl="fanHold_in_band",
)

# test-facing API (tests/test_integration_goals.py)
EXEC_KEYS = CONFIG.exec_keys


def resolved_exec_targets(overrides=None):
    return lean_workflow.resolved_exec_targets(CONFIG, overrides)


def vector_failures(exec_targets, run_vector=lean_workflow._run_vector):
    return lean_workflow.vector_failures(exec_targets, run_vector)


def make_codegen_fn(exec_targets, run_vector=lean_workflow._run_vector):
    return lean_workflow.make_codegen_fn(CONFIG, exec_targets, run_vector)


if __name__ == "__main__":
    lean_workflow.run_cli(CONFIG, __doc__)
