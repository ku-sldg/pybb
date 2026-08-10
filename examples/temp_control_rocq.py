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
        [--tamper-admitted] [--tamper-axiom] [--repair]

See examples/rocq_workflow.py for flag semantics.
"""

from pathlib import Path

import rocq_workflow
from rocq_workflow import RocqExampleConfig

REPO = Path(__file__).parent.parent
PACKAGE = REPO / "targets" / "temp-control-rocq"

PROPS_REL = "TempControl/Props.v"
ACCEPTANCE_REL = "TempControl/Acceptance.v"
PROOFS_REL = "TempControl/Proofs.v"

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
    # primitive): tamper -> attribution -> repair -> re-attest, one run
    restart_budget=1,
)

if __name__ == "__main__":
    rocq_workflow.run_cli(CONFIG, __doc__)
