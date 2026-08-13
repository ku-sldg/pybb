"""
temp-control_Rocq — the goal-directed encoding on the Rocq Prover: the
administrator blesses abstract goal PROPERTIES (statements, not proofs)
plus the obligation binding; proofs, the implementation, and any
intermediate lemmas are workflow-owned and freely mutable
(targets/temp-control-rocq, dune theory TempControl).

    TempControl/Props.v       BLESSED: self-contained statements file —
                              types, the Step interface shape, four goal
                              props parameterized over any candidate
                              implementation, and the Spec conjunction.
    TempControl/Acceptance.v  BLESSED: the obligation binding —
                              `Definition acceptance : Spec computeFanCmd
                              := spec_holds` fails to elaborate if
                              spec_holds is missing, renamed, or weaker
                              than the blessed obligation.
    TempControl/Impl.v        mutable: the implementation candidate.
    TempControl/Proofs.v      mutable: seed proofs + spec_holds +
                              intermediate lemmas.
    Assumptions.v             the provability audit, at the PACKAGE ROOT,
                              outside the theory: one Print Assumptions
                              per goal, recompiled fresh every episode
                              (dune is silent on warm builds, so the
                              audit cannot live inside the theory).

What the Rocq toolchain changes (vs the Lean goals scenario): Lean's
elaborator reports hasSorry in-band, so `lake lean` alone judges
provability. Rocq's `Admitted.` and `Axiom` COMPILE CLEANLY — exit 0,
green build — so elaboration proves nothing. Provability is judged by
the assumptions audit instead: every goal must be "Closed under the
global context", and a refusal names the goal and the axioms beneath it.
That split is this example's point, and why the verification class is
always-run:

    --tamper-admitted   Admitted. — the build PASSES, the audit refutes
                        the goal by name
    --tamper-axiom      the headline: smuggle `Axiom convenient : ...`
                        and prove by it — every file elaborates cleanly,
                        nothing structural moves, and the audit still
                        refutes the goal, naming `convenient`

This is a THIN CONFIG over examples/rocq_workflow.py; the whole workflow
(protocols, provisioning, episodes, tamper demos) is the shared driver.

Usage:
    python examples/temp_control_rocq.py [--provision] [--tamper]
        [--tamper-admitted] [--tamper-axiom] [--repair] [--pause]
        [--status] [--ready]
        [--synthesize [--keep]] [--break-proof] [--synthesize-impl]
        [--synthesize-package]
        [--llm {anthropic,openai} [--llm-only] [--llm-model ID]
         [--llm-max-tokens N] [--llm-effort E] [--llm-dry-run]]

See examples/rocq_workflow.py for flag semantics and docs/demo_rocq.md
for the demo arcs.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import rocq_workflow
from rocq_workflow import RocqExampleConfig

from pybb.attestation import RocqLlmEngine, RocqTacticPortfolioEngine

REPO = Path(__file__).parent.parent
PACKAGE = REPO / "targets" / "temp-control-rocq"

PROPS_REL = "TempControl/Props.v"
ACCEPTANCE_REL = "TempControl/Acceptance.v"
PROOFS_REL = "TempControl/Proofs.v"
IMPL_REL = "TempControl/Impl.v"

# The blessed statements file admits only statement declarations.
STATEMENT_KINDS = {"Definition", "Inductive", "Record"}

_REQUIRE = re.compile(r"^\s*(?:From\s+(\S+)\s+)?Require\b")


def acceptance_canon() -> str:
    """The canonical obligation binding — Acceptance.v must be exactly
    this (checked at blessing time; its bytes are then blessed, so live
    tamper of the check itself is caught by the model class)."""
    return (
        "(* BLESSED: the canonical obligation binding — fails to elaborate "
        "if\n"
        "   spec_holds is missing, renamed, or weaker than the blessed "
        "Spec. *)\n"
        "Require Import TempControl.Proofs.\n"
        "Definition acceptance : Spec computeFanCmd := spec_holds.\n")


def bless_lint(cfg: RocqExampleConfig) -> None:
    """Refuse a blessing whose statements file is not purely statements,
    imports beyond Stdlib, or does not elaborate standalone — or whose
    obligation binding is not the canonical one. Raises SystemExit with
    every problem found.

    The static checks run first and, when any fails, the standalone
    `rocq compile` is skipped: the refusal is already justified without
    invoking the toolchain."""
    from pybb.attestation.targetmap import rocq_decl_spans

    problems = []
    props = cfg.package_root / PROPS_REL
    text = props.read_text()
    depth = 0
    for i, line in enumerate(text.splitlines(), 1):
        at_start = depth
        depth = max(0, depth + line.count("(*") - line.count("*)"))
        if at_start > 0:
            continue  # inside a block comment
        m = _REQUIRE.match(line)
        if m and m.group(1) != "Stdlib":
            problems.append(
                f"{PROPS_REL}:{i}: '{line.strip()}' — the blessed statements "
                "file may import only Stdlib")
        if re.search(r"\b(Proof|Admitted)\s*\.", line):
            problems.append(
                f"{PROPS_REL}:{i}: proof scripting in the blessed statements "
                "file (statements only — proofs are workflow-owned)")
    for kind, name, start, _end in rocq_decl_spans(text):
        if kind not in STATEMENT_KINDS:
            label = f"{kind} {name}" if name else kind
            problems.append(
                f"{PROPS_REL}:{start}: '{label}' — the blessed statements "
                f"file admits only {'/'.join(sorted(STATEMENT_KINDS))} "
                "(proofs, postulates and implementations are workflow-owned)")
    live = (cfg.package_root / ACCEPTANCE_REL).read_text()
    if live != acceptance_canon():
        problems.append(f"{ACCEPTANCE_REL} differs from the canonical "
                        "obligation binding")
    if not problems:
        # statically clean: the statements must also elaborate standalone
        # (a temp-dir copy — no .vo droppings in the package tree)
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / props.name
            shutil.copy2(props, copy)
            out = subprocess.run(
                [str(rocq_workflow.WORKSPACE_BIN / "rocq"), "compile",
                 props.name],
                cwd=td, capture_output=True, text=True)
        if out.returncode != 0:
            detail = " ".join(out.stderr.split())[:300]
            problems.append(f"{PROPS_REL} does not elaborate standalone "
                            f"(exit {out.returncode}): {detail}")
    if problems:
        raise SystemExit("blessing refused:\n  " + "\n  ".join(problems))

# One Print Assumptions section per goal, in Assumptions.v order — the
# appraiser's assumptions-mode contract.
AUDIT_GOALS = [
    "hot_means_not_cold",
    "fanOn_when_hot",
    "fanOff_when_cold",
    "fanHold_in_band",
    "fanOn_only_if_hot_or_held",
    "spec_holds",
    "acceptance",
]

CONFIG = RocqExampleConfig(
    prefix="temp_control_rocq",
    package_root=PACKAGE,
    theory_name="TempControl",
    blessed_rels=[PROPS_REL, ACCEPTANCE_REL],
    audit_rel="Assumptions.v",
    audit_goals=AUDIT_GOALS,
    tamper_targ="temp_control_rocq_props_fanOn_when_hot_prop_targ",
    proofs_rel=PROOFS_REL,
    tamper_admitted_decl="fanHold_in_band",
    tamper_axiom_decl="fanHold_in_band",
    tamper_axiom_name="convenient",
    tamper_axiom_stmt="Axiom convenient : fanHold_in_band_prop computeFanCmd.",
    # --repair is judged by fresh measurement IN-SESSION (restart-episode
    # primitive): tamper -> attribution -> repair -> re-attest, one run —
    # and the always-run verification entry rides the same restart, so
    # episode 2 ends with ALL THREE entries in good standing
    restart_budget=1,
    # blessing gate: statements-only Props.v (Stdlib imports only,
    # elaborates standalone) + byte-canonical Acceptance.v
    bless_lint=bless_lint,
    # --synthesize: the engine ladder (cheap deterministic tactic search
    # first; the LLM slot ships with no backend — --llm arms it); the
    # audit goals double as the checklist's per-goal audit rows
    synthesis_engines=[RocqTacticPortfolioEngine(), RocqLlmEngine()],
    impl_name="computeFanCmd",
    impl_rel=IMPL_REL,
    break_proof_decl="fanHold_in_band",
)

if __name__ == "__main__":
    rocq_workflow.run_cli(CONFIG, __doc__)
