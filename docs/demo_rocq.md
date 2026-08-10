# temp-control_Rocq — goal-directed attestation over a Rocq spec

The third prover ecosystem (after Lean and Verus): the temp-control
goal-directed scenario encoded in Rocq 9 (`targets/temp-control-rocq`,
dune-built theory `TempControl`). Same blessed-statements design as
`temp-control-goals`: `Props.v` and `Acceptance.v` are BLESSED (signed
statements, promote-owned); `Impl.v` and `Proofs.v` are mutable — their
attested property is provability, not bytes.

## What is different in Rocq — the assumptions audit

Lean's verification tier reads `lake lean --json` diagnostics and
refutes on `hasSorry`. Rocq has no diagnostic stream: `Admitted.`
compiles with exit 0 and **so does a smuggled `Axiom`** — elaboration
alone can never refute either. The verification class therefore judges
provability with the kernel's own dependency audit:

- `Assumptions.v` (package root, deliberately OUTSIDE the dune theory —
  dune is silent on warm builds, so cached `Print` output would vanish)
  runs `Print Assumptions <goal>.` for all six proofs plus the
  acceptance binding, freshly every episode via
  `rocq compile -R _build/default/TempControl TempControl Assumptions.v`.
- `run_command_rocq_appr` (assumptions mode) requires exactly one
  output section per goal, every one `Closed under the global context`;
  an `Axioms:` section fails with a reason naming the goal and its
  axioms. Section-count mismatch fails closed.

This is strictly stronger than the Lean tier: it catches `Admitted`
(the `sorry` analogue) *and* axiom-laundering — replacing a proof body
with `exact convenient` where `Axiom convenient : ... .` was smuggled
into the mutable file. That tamper elaborates cleanly and leaves every
structural measurement green; only the audit refutes it:

    Rocq assumptions audit failed: fanHold_in_band depends on axioms:
    convenient; spec_holds depends on axioms: convenient; acceptance
    depends on axioms: convenient

## Protocol classes

| protocol | class | measurement |
|---|---|---|
| `temp_control_rocq_model` | model | blessed `Props.v` + `Acceptance.v`: readfile content + hashfile per file, one SIG (the provisioning bundle IS the blessing) |
| `temp_control_rocq_contracts` | contracts | 10 decl-named slices of the blessed files (`derive_targets_from_rocq`) — attribution names the property |
| `temp_control_rocq_verification` | verification | `dune build` (build mode: elaboration) + the assumptions audit (provability), tools measured-then-used |

Entries: `:model` (fail → contracts refinement → restore),
`:contracts` always-run (fail → restore), `:verification` always-run
(fail → escalate). Verification is not gated behind `--validate` —
warm dune builds are sub-second, and the audit is the point.

## Demo arcs

    python examples/temp_control_rocq.py --provision        # bootstrap blessing + goldens
    python examples/temp_control_rocq.py                    # clean episode
    python examples/temp_control_rocq.py --tamper           # blessed-slice tamper -> attribution names the prop
    python examples/temp_control_rocq.py --tamper --repair  # golden restore + in-session re-attestation
    python examples/temp_control_rocq.py --tamper-admitted  # Admitted: build green, audit names the goal
    python examples/temp_control_rocq.py --tamper-axiom     # smuggled Axiom: everything green EXCEPT the audit

Tests: `tests/test_integration_rocq.py` (fixtures-consistency ungated;
arcs gated `RUN_ROCQ=1`).

## Rocq facts the design leans on (verified on Rocq 9.0.1)

- `Require Import` is not transitive for names — the package uses
  `Require Export` down the Props ← Impl ← Proofs chain (the Lean
  `import` semantics the shared workflow shape assumes).
- Stdlib is a separate logical root in Rocq 9: `From Stdlib Require
  Import ZArith`, and the dune stanza needs `(theories Stdlib)`.
- `if` needs `bool`: the impl guards with `Z.ltb` (`<?`) while the
  blessed props state `Z.lt` — `Z.ltb_spec` bridges, which keeps the
  proofs honest (they are not definitional unfolding).
- rocq/dune report errors on stderr with nonzero exit and are silent on
  success — evidence is one JSON blob `{status, stdout, stderr}`.

## Phase 2/3 (planned, not landed)

bless_lint for `.v`; `--status` checklist backed by per-goal audit
sections; `splice_proof` for `Proof. ... Qed.` blocks + a Rocq tactic
portfolio + the LLM engines (the synthesis experiments rerun natively);
extraction-based `_build`/`_executable`; `--check`/`--promote` via a
`.v` `changed_decls`.
