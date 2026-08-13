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

    python examples/temp_control_rocq.py --provision        # bootstrap blessing + goldens (gated by bless_lint)
    python examples/temp_control_rocq.py                    # clean episode
    python examples/temp_control_rocq.py --tamper           # blessed-slice tamper -> attribution names the prop
    python examples/temp_control_rocq.py --tamper --repair  # golden restore + in-session re-attestation
    python examples/temp_control_rocq.py --tamper-admitted  # Admitted: build green, audit names the goal
    python examples/temp_control_rocq.py --tamper-axiom     # smuggled Axiom: everything green EXCEPT the audit
    python examples/temp_control_rocq.py --status           # the goals checklist (quick view)
    python examples/temp_control_rocq.py --ready --status   # + readiness gate; failure poisons every cell
    python examples/temp_control_rocq.py --synthesize       # stub all proofs to Admitted -> portfolio proves all
    python examples/temp_control_rocq.py --break-proof      # corrupt one seed proof -> portfolio repairs it
    python examples/temp_control_rocq.py --synthesize-impl --llm openai --llm-dry-run
                                                            # impl-first arc, spend predicted, no key needed
    python examples/temp_control_rocq.py --synthesize-package --llm anthropic
                                                            # whole-package arc: ONE black box writes impl + proofs

Tests: `tests/test_integration_rocq.py` + `tests/test_rocq_synthesis.py`
(units ungated; toolchain/CVM arcs gated `RUN_ROCQ=1`; live-LLM arcs
`RUN_LLM=1`).

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

## Phase 2 — status, synthesis, and the blessing gate

### `--status`: the checklist is the audit, read per goal

Rows come from the blessed bytes (the signed `Spec` conjunction,
`rocq_spec_conjuncts` splitting on `/\`); witnesses are the live
`Proofs.v` declarations whose STATEMENT references a prop (a prop named
inside a proof body is never a witness). Cells come from the audit's
retained output: the verification term's EXTEND appraiser keeps the
`{status, stdout, stderr}` blob it judged, and section *k* of that
stdout judges `audit_goals[k]` BY NAME (`pybb/attestation/rocq_status.py`):

- `Closed under the global context` → ✓
- `Axioms:` listing the goal itself → ✗ `uses Admitted` (an admitted
  constant is its own axiom)
- `Axioms:` listing another name → ✗ `depends on axiom: <name>` (the
  smuggled-postulate attribution)

Fail-closed tiers below that: a failed `tool::` hash or protocol error
poisons every cell to `?`; a failed BUILD component falls back to
mapping the build stderr's `File "...", line N` into `rocq_decl_spans`
(dune removes a failed file's `.vo`, so the audit after a failed build
judged an incomplete tree — nothing else may stay ✓); an audit compile
failure with the build green is a MISSING WITNESS, attributed via the
failing `Print Assumptions` line; a section-count mismatch poisons
everything. A witness that is live but outside the audited goal set is
`?`, never presumed proved. `--ready --status` failure poisons the
checklist (`BASELINES NOT TRUSTED`).

### `--synthesize`: the audit as the local judge

Same step-4 loop as the Lean goals scenario, Rocq-shaped
(`pybb/attestation/rocq_synthesis.py`). `_stub_proofs` admits every
Theorem/Lemma (`Proof. Admitted.` — the build stays GREEN, which is the
point); `RocqProofSynthesisKS` works the open goals in audit order
(binding witness last, so its candidate can cite the other witnesses).
Candidates are INNER tactic scripts spliced by `splice_proof_rocq`
(statement byte-identical through `Proof.`; `Proof.`/`Qed.` frames
stripped from LLM output; term-style `:=` proofs refused). A candidate
is accepted iff `dune build` is clean AND the audit compiles AND the
goal's own section closes AND no section outside the pre-candidate
failing set opens (the baseline guard — closing your goal by admitting
a neighbor is refused). Rejections feed back into the engine ladder
with the refuting text (build errors, or `depends on axioms: ...`).
Each locally-clean state spends ONE restart; the fresh episode's
build+audit is the judgment.

`RocqTacticPortfolioEngine` (cheap-first, name-agnostic): `unfold
{prop}[, helpers], {impl}` + `repeat match goal with |- context
[?a <? ?b] => destruct (Z.ltb_spec a b) end` (and the hypothesis-side
variant for the safety-direction goal), closed by `first [ reflexivity
| discriminate | lia ]`; helper shape `unfold {helpers} [in *]; intros;
lia.`; binding shape `exact (conj w1 (conj w2 ...)).` from the live
witnesses. Every committed goal is solvable by at least one candidate
(enforced by the RUN_ROCQ headline test).

### `--synthesize-impl`: impl-as-axiom

"Unimplemented" and "unprovable" are the same kernel judgment: the
impl-first stub is `Definition computeFanCmd ... : FanCmd.` +
`Proof. Admitted.` — a well-formed declaration whose body is an axiom.
The goals then genuinely cannot close (the impl is opaque AND assumed),
and `RocqImplSynthesisKS`'s local sense is a scratch
`Print Assumptions computeFanCmd` audit: open while admitted, closed
once a real term lands (`splice_impl_rocq`). Its context is the blessed
statements ONLY — no proofs, no prior body: the properties alone must
determine the implementation, which the proof rung then proves correct.
Two spike facts worth keeping: `Print Assumptions` does NOT traverse an
axiom's type, so admitted proofs shadow the admitted impl in the goal
sections (hence the impl rung's own audit); and the seed `Example`
vectors are kernel-COMPUTED (`reflexivity`), so the impl-first arc stubs
them too — they cannot elaborate over an opaque impl.

### `--synthesize-package`: impl + proofs as one black box

The single-rung alternative to the impl-then-proofs chain: same
starting stubs as the impl-first arc, but the `:verification` fail
route carries ONE `RocqPackageSynthesisKS`. Its engines
(`RocqLlmPackageEngine`; LLM-only, so the arc requires `--llm`) reply
with COMPLETE contents for `Impl.v` and `Proofs.v` together
(`=== FILE: <path> ===` blocks). Acceptance is monotone progress under
the same local senses: a candidate is kept iff the tree is auditable,
nothing closed reopens, and the failing set strictly shrinks; rejected
candidates are reverted and fed back with the refuting text. The trust
story is unchanged — the engine owns the mutable files wholesale
(nothing there was ever trusted on bytes; the sentinels and the blessed
acceptance binding police the rest), and only the restart's fresh
measurement re-establishes standing.

### `--pause`: out-of-band repair (the interactive human/agent rung)

`--pause` inserts `OutOfBandRepairKS` rungs — a black box whose tool is
the world outside the process. On failure the episode BLOCKS with a
work order (the failing components, plus what the live audit says is
still open); the operator repairs out-of-band — hand edit, an
interactive LLM code-agent session in another terminal — and answers
`[r]e-attest` or `[s]kip`. The claim is worthless by design: only the
restart's fresh measurement re-establishes standing, and the sentinels
catch any edit to blessed files. Placement: on `:verification` the
audit-aware rung (`RocqOutOfBandRepairKS`, on_local_clean — claiming
"repaired" while the audit is dirty costs nothing but another look);
on `:model`/`:contracts` a generic rung ahead of the automatic golden
restore, with `also=[:verification]` so a blessed-file fix restarts the
staled sibling. In a synthesis arc the pause rung chains AFTER the
engines: machines first, human on whatever remains. Skipping falls
through to the ordinary chain (restore, or escalation as before).

    python examples/temp_control_rocq.py --tamper-axiom --pause   # fix it yourself, judged by measurement
    python examples/temp_control_rocq.py --break-proof --pause    # engines first, then you

### `--llm`: the armed engines

Same explicit opt-in chain and flag set as the Lean driver (`--llm
{anthropic,openai}`, `--llm-only`, `--llm-model`, `--llm-max-tokens`,
`--llm-effort`, `--llm-dry-run`), now factored into
`pybb.attestation.llm_backends.arm_llm_engines` and shared by both
drivers. `RocqLlmEngine` / `RocqLlmImplEngine` override ONLY the prompt
headers (Rocq 9, Stdlib only; reply with ONLY the tactic script between
`Proof.` and `Qed.` / ONLY the term after `:=`); rejection feedback and
usage accounting are inherited.

### `bless_lint` for `.v`

Blessing (bootstrap or re-bless) is gated: `Props.v` must contain only
Definition/Inductive/Record declarations, import nothing beyond
`Stdlib`, carry no `Proof.`/`Admitted.` scripting, and elaborate
standalone (`rocq compile` on a temp copy — run only when the static
checks pass, so a refusal never needs the toolchain); `Acceptance.v`
must byte-match `acceptance_canon()`.

### `--tamper --repair`: the cross-entry restart

The verification class is always-run, so a blessed-file tamper fails
all THREE entries; verification has no repair chain and escalates. The
repair chain's `RestartEpisodeKS` now carries `also=[<p>:verification]`:
after the golden restore it revives the escalated sibling and restarts
it alongside model/contracts — the tamper–repair run ends with all
three entries in good standing, episode 2, judged by fresh measurement.

## Phase 3 (planned, not landed)

Extraction-based `_build`/`_executable` classes; `--check`/`--promote`
via a `.v` `changed_decls`.
