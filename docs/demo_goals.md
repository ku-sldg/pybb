# Goal-directed encoding: blessed statements, workflow-owned proofs

The pilot for the goal-directed workflow (`targets/temp-control-goals`,
`examples/temp_control_goals_lean.py`): the administrator blesses a
handful of **abstract goal properties** — statements, not proofs — and
everything else (the implementation, the proofs including any seeds
present at blessing, intermediate lemmas) is **workflow-owned and freely
mutable**. The attestation enforces exactly one invariant throughout:
*the blessed properties remain untouched*.

This is step 1 of the goal-directed roadmap: the **encoding**. Later
steps build on it: per-declaration proof status (the progress signal),
the restart-episode primitive (many verify cycles per session), and the
synthesis knowledge sources that actually try to implement and prove
the blessed goals. Nothing in this step changes the blackboard/KS layer
— the encoding is configuration over the shared Lean driver
(`examples/lean_workflow.py`), plus three small, default-neutral driver
knobs.

## The encoding

The statement/proof split is file-level, and the properties are
**parameterized over the implementation to be synthesized**:

| File | Status | Role |
|---|---|---|
| `TempControl/Props.lean` | **BLESSED** | Self-contained (no imports): `FanCmd`, `SetPoint`, `SetPoint.valid`, the interface shape `abbrev Step`, four goal props `(f : Step) : Prop`, and the bundle `def Spec (f : Step) : Prop` — their conjunction. No theorems, no proofs, no sorry (lint-enforced). |
| `TempControl/Acceptance.lean` | **BLESSED** | The two-line obligation binding: `example : Spec computeFanCmd := spec_holds`. Fails to elaborate if `spec_holds` is missing, renamed, or has any weaker type. |
| `TempControl/Impl.lean` | mutable | The implementation candidate (`computeFanCmd`, of type `Step`). |
| `TempControl/Proofs.lean` | mutable | Seed proofs + `spec_holds : Spec computeFanCmd` + intermediate lemmas. |
| `Main.lean` | mutable | Imports ONLY Impl — provability and behavior stay independent. |

Because the blessed files' bytes never change while the workflow
iterates, the **existing whole-file model blessing enforces the
invariant verbatim** — signed at provisioning, promote-owned, verified
at every readiness gate, laundering refuted by the blessing. Blessing
`Acceptance.lean` (rather than generating it) means tamper of the
coverage check *itself* is caught by the model-class hash and restored
from golden like any blessed file.

Proof bytes need no integrity protection at all: a proof's only value
is that it elaborates, and the kernel re-judges that at every
verification run. That is why mutable files carry **no structural
goldens** — their attested properties are provability (live
elaboration) and behavior (the pinned binary).

## Protocols (prefix `temp_control_goals_lean`)

- `_model` — readfile + hashfile of **both blessed files** under one
  SIG; the provisioning bundle is the blessing; promote-owned.
- `_contracts` — declaration slices of the **blessed files only** (9
  named Props declarations + the acceptance example), the always-run
  sentinel and the refinement rung under `:model`: a violated statement
  is attributed *by prop name*.
- `_verification` — **two** targets: `lake lean TempControl/Proofs.lean
  -- --json` (every proof must elaborate; error diagnostics and
  `hasSorry` refute — a target's JSON stream does not carry imported
  modules' diagnostics, so Proofs must be a target itself) and
  `lake lean TempControl/Acceptance.lean -- --json` (the coverage
  check: is the blessed obligation actually proved?). Toolchain woven
  measure-then-use, as in the classic Lean scenarios.
- `_build` / `_executable` — unchanged pattern: the signed build event
  at provisioning; hash-then-run of the pinned binary on one vector per
  goal case (`hot`/`cold`/`hold`), expecteds AM-owned.

**The blessing gate** (`bless_lint`, run before the model class is
signed at bootstrap or `--promote`): `Props.lean` must elaborate
standalone with clean diagnostics and contain only statement
declarations (`def`/`abbrev`/`structure`/`inductive` — no
theorem/lemma/example/instance); `Acceptance.lean` must match the
canonical binding byte-for-byte.

## Demo arcs

```sh
python examples/temp_control_goals_lean.py                # clean episode
python examples/temp_control_goals_lean.py --validate     # + proofs & behavior
python examples/temp_control_goals_lean.py --provision
python examples/temp_control_goals_lean.py --tamper --repair
python examples/temp_control_goals_lean.py --tamper-semantic
python examples/temp_control_goals_lean.py --check / --promote
```

The arcs the encoding adds over the classic scenarios
(`tests/test_integration_goals.py` pins all of them):

- **Invariant**: corrupt a blessed goal statement live → `:model`
  fails, contracts attribution names `fanOn_when_hot_prop`, whole-file
  repair restores, episode 2 verifies. Laundering (tamper the golden
  tree and re-provision) re-signs the contracts baseline
  self-consistently — only the blessing, which ordinary provisioning
  never refreshes, refutes it at readiness, and attestation never
  starts.
- **Mutability** (the encoding's core claim): rewrite a seed proof and
  introduce an intermediate lemma → every structural measurement stays
  green, and verification still proves. The workflow's room to iterate.
- **Coverage**: retype `spec_holds : True` → `Proofs.lean` still
  elaborates cleanly (each file is individually valid), but the blessed
  Acceptance obligation fails, attributed to the acceptance target. A
  `sorry` inside a seed proof refutes via the Proofs target (`hasSorry`
  — sorry exits 0) while the pinned binary still attests: provability
  and behavior independent, as ever.
- **Lint**: blessing a statements file containing a `theorem`, or a
  non-canonical acceptance binding, is refused before anything is
  signed.

## The progress view (`--status` / `--ready`)

Step 2 of the roadmap: the per-declaration proof status the synthesis
loop will consume, surfaced as the **goals checklist**:

```sh
python examples/temp_control_goals_lean.py --status           # quick view
python examples/temp_control_goals_lean.py --status --ready   # baselines verified first
python examples/temp_control_goals_lean.py --ready            # readiness report only
```

```
goal properties (derived progress view — quick: baselines not verified this run):
  fanOn_when_hot_prop             ✓  (witness: fanOn_when_hot)
  fanOff_when_cold_prop           ✓  (witness: fanOff_when_cold)
  fanHold_in_band_prop            ✗  (fanHold_in_band: declaration uses `sorry`)
  fanOn_only_if_hot_or_held_prop  ✓  (witness: fanOn_only_if_hot_or_held)
  Spec bound (acceptance)         ✓
```

The mechanism (`pybb/attestation/proof_status.py`): the verification
class's EXTEND appraiser retains the `lake lean --json` diagnostic
stream it judged, the verified appraisal summary lifts it per component
(`measured_b64`), and the diagnostics' positions are mapped onto the
proofs file's declaration spans. **Rows come from the blessed bytes**
(the Spec conjuncts, scanned from the model protocol's signed golden —
the changed_decls principle: goldens are launderable, the blessing is
not); witnesses are live declarations whose *statement* references the
prop (an `unfold <prop>` in a proof body does not count).

Four cell states, downgrade-only and fail-closed (the per-contract-join
guardrails): `✓` requires the appraiser's PASS — or, on a FAIL, that
every refuting diagnostic mapped into some *other* declaration's span
(labeled derived); `✗` a refutation mapped into this goal's witness;
`?` unknown — a failed `tool::` hash in the same term, a protocol
error, unmappable diagnostics, or (`--status --ready`) a failed
readiness gate poison every cell rather than guess; `–` no witness
declaration yet (legal mid-synthesis — the binding row still governs).

The quick view is deliberately cheap (one verification run, no
readiness): it is a *progress* signal and says so in its header. The
`--ready` variant verifies every signed baseline first and labels the
checklist accordingly.

## In-session re-attestation (`--repair`, the restart-episode primitive)

Step 3 of the roadmap. In the classic scenarios repair ends escalated —
"repaired from golden — verification pending next episode" — because the
attestation model is episodic: predicates memoize per measurement, and
dispatch latches once per key. The goals scenario's repair chains instead
end in a `RestartEpisodeKS`: after the repair, the chain *requests a
fresh episode*, and the controller (top of the next cycle) forgets the
memoized verdicts for the entry's episode measurements, reseeds the entry
with a fresh KS budget, clears the dispatch latch, and re-evaluates — a
genuinely fresh CVM run judging the repaired state, in the same session:

    python examples/temp_control_goals_lean.py --tamper --repair
    ...
    temp_control_goals_lean:model: all attested components intact
        (temp_control_goals_lean_model passed) — repaired and re-attested
        clean in-session (episode 2)

Trust semantics are unchanged: the repair's word is still worthless, and
only the fresh measurement re-establishes standing — the process
boundary was an implementation artifact, not the trust argument. Halting
is preserved twice over: the chain's `budget` is policy (an exhausted
budget ends the chain, and end-of-route escalation reports "repaired but
re-attestation failed — restart budget exhausted" with the last failing
verdict), and the controller's `max_restarts_per_key` is law, bounding
every requester regardless of politeness.

### Design commitments for the synthesis layer (step 4)

Recorded here because the synthesis KSs inherit them:

- **Restarts are pull-only.** Nothing watches files; mutable-file writes
  change no measurement, so between restarts the memoized verdict makes
  every re-evaluation a free cache hit. A synthesis KS iterates with
  BARE LEAN TOOLS inside its `execute()` — any number of candidate
  writes and local `lake lean` checks (untrusted senses) — and requests
  a restart only for a candidate that locally elaborates. Attestation
  cost is O(1) per accepted candidate, never O(candidates tried); the
  attested run measures the toolchain in the same term
  (measure-then-use), so the judgment is protected regardless of what
  the local loop used.
- **Cross-entry requests.** `request_restart(key, reason)` is callable
  by any KS for any key: an implementation write stales the
  verification verdict, and the sibling entry must be re-measurable.
- **No provisioning from the loop.** During synthesis, the proofs are
  the primary attested judge of the implementation (verification
  elaborates the LIVE `Impl.lean`); behavior vectors are a local,
  unattested guardrail; *attested* behavior of a binary arrives only at
  the human `--promote` gate (rebuild + vectors + re-bless). The rule
  that provisioning is never triggerable from failure handling survives
  intact, and `:executable` is simply off the board mid-synthesis.

## Synthesis (`--synthesize`, step 4 — the workflow takes over)

The workers. `--synthesize` stubs every seed proof to `sorry` (the
goal-directed starting state: goals blessed, nothing proved), puts
`:model` / `:contracts` / `:verification` on the board (`:executable`
stays off — attested behavior arrives only at the human `--promote`
gate), and routes the failing verification entry to `ProofSynthesisKS`:

    Stubbed 6 proofs to sorry in TempControl/Proofs.lean
    ...
      synthesis:proofs: 'fanOn_when_hot' proved (TacticPortfolioEngine)
      synthesis:proofs: 'fanOff_when_cold' proved (TacticPortfolioEngine)
      ...
      synthesis:proofs: 'spec_holds' proved (TacticPortfolioEngine)
    Cycle 3: restarting episode for 'temp_control_goals_lean:verification'
        (synthesis:proofs: locally clean) - fresh measurement ... (episode 2)
    temp_control_goals_lean:verification: all attested components intact
        (...) — repaired and re-attested clean in-session (episode 2)

The step-3 commitments, exercised: the KS iterates with bare `lake lean`
inside `execute()` — engines (a ladder of plain callables: deterministic
`TacticPortfolioEngine` first, the `LlmEngine` slot next, end-of-route
escalation as the human rung) yield candidate proofs per failing goal,
each spliced in (statement kept, proof replaced) and judged locally,
reverted on failure, kept on acceptance. Only a locally-clean state
spends a restart; the fresh episode's measurement is the ONLY thing that
flips standing. The synthesized proofs are ordinary mutable content —
`--keep` retains them, and a plain `--validate` episode passes on them.

Engines never touch the blessed files — and would gain nothing by it:
the model/contracts sentinels and the acceptance obligation judge every
state by measurement. `LlmEngine` ships without a backend (plug
`complete=` in to arm it); an LLM's candidates are untrusted senses like
any other engine's.

### Black-box repair (the AutoVerus shape)

`ProofSynthesisKS` is a specialization of the generic
**`BlackBoxRepairKS`**: a chain rung wrapping an OPAQUE external repair
tool — e.g. AutoVerus for Verus/Rust proof repair. The tool gets a
`RepairContext` (the failing verdict with per-component reasons and
retained measured output, the working file set) and may rewrite files
however it likes; its claim of success is never trusted. The blackboard
machinery is the re-appraisal between its attempts: the KS requests a
restart (`per_attempt`, or `on_local_clean` behind an untrusted local
check), the fresh episode re-measures, and the tool's next attempt sees
the new failure context. A black box needs zero trust — repair cannot
mint trust, and even a rogue edit to blessed files is caught by the
sentinels. Wiring one is pure configuration:

    route(":verus-verification",
          on_fail=[BlackBoxRepairKS(tool=autoverus_adapter,
                                    restart_policy="per_attempt")])

The worked AutoVerus integration LANDED via the `apk` branch merge —
see `demo_autoverus.md`: `pybb/autoverus/AutoVerusRepairKS` (used
directly, not through BlackBoxRepairKS) repairs with AutoVerus's
internal iteration and is judged by a definitive attested Verus run in
a fresh episode (`examples/find_max_verus.py`), behind an explicit
`--autoverus` LLM opt-in.

## Sanctioned change

`--check` diffs the **blessed files only** (`changed_decls(files=...)`)
against the blessed bytes — proof/lemma churn in mutable files is not a
sanctioning question; a live edit to a goal statement is named
precisely. `--promote` is the sanctioning pipeline unchanged: gates
(build + vectors, proofs must prove) → gold moves → full re-blessing —
including the lint — → verification episode.

## The complete arc, and what follows

All four steps are landed: the admin blesses abstract goal properties
(`--provision`, lint-gated), the progress view names what remains
(`--status`), the workflow takes over proving them (`--synthesize`:
engines iterate freely on bare tools, restarts judge each accepted
state by fresh measurement), and the invariant — blessed properties
untouched — is enforced by measurement throughout. A final `--promote`
is the administrator's sanction of the synthesized result (rebuild,
vectors, re-blessing): trust begins and ends with the human.

Natural follow-ups, in rough order of leverage: an armed `LlmEngine`
backend; the AutoVerus adapter on a Verus scenario (the BlackBoxRepairKS
recipe above); implementation synthesis (enumerative candidates over a
small expression grammar — comparisons of `temp` against `sp.low` /
`sp.high`, branches to `On`/`Off`/`latest` — judged by local vectors
then live proofs, with cross-entry restarts because an impl write stales
the verification verdict).
