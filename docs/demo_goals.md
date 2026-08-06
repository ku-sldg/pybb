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

## Sanctioned change

`--check` diffs the **blessed files only** (`changed_decls(files=...)`)
against the blessed bytes — proof/lemma churn in mutable files is not a
sanctioning question; a live edit to a goal statement is named
precisely. `--promote` is the sanctioning pipeline unchanged: gates
(build + vectors, proofs must prove) → gold moves → full re-blessing —
including the lint — → verification episode.

## Where this leads (steps 2–4)

The encoding gives the synthesis workflow its contract: a synthesis KS
may write anything in the mutable files, and *cannot* touch the goals —
not by policy but by measurement (any blessed-byte drift fails `:model`
/ `:contracts`; a dodged obligation fails Acceptance). "Done" is
already judged by the existing tiers: verification clean (no errors, no
sorry) + acceptance clean + vectors green. What remains is the loop:
per-declaration proof status as the progress signal, restart-episode to
re-attest candidates in-session, and the synthesis KSs themselves.
