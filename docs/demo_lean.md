# Lean example: attesting a specification and its executable

The temp-control model ported to a third verification ecosystem — Lean 4 —
alongside the JVM/Logika and Microkit/Verus examples. Nothing in the
blackboard/KS layer changed to admit it: the Lean ecosystem entered as two
ASPs (asp-libs `run_command_lean` / `run_command_lean_appr`), one targetmap
backend (`derive_targets_from_lean`), and four protocol dirs. That is the
architectural claim this example validates.

The workflow itself lives in the shared driver `examples/lean_workflow.py`;
`examples/temp_control_lean.py` is a thin `LeanExampleConfig` over it. A
second Lean scenario is pure configuration — see `demo_gear.md`
(landing-gear retraction interlock, `examples/landing_gear_lean.py`).
A third scenario pilots the GOAL-DIRECTED encoding — blessed statements,
workflow-owned proofs — see `demo_goals.md`
(`examples/temp_control_goals_lean.py`).

## The target

`targets/temp-control-lean` — a Lake package (core Lean v4.31.0, no
dependencies):

| File | Role |
|---|---|
| `TempControl/Impl.lean` | Implementation: `FanCmd`, `SetPoint`, `computeFanCmd`. Deliberately proof-free. |
| `TempControl/Spec.lean` | Specification: the GUMBO compute contracts as theorems (`fanOn_when_hot`, `fanOff_when_cold`, `fanHold_in_band`, safety property `fanOn_only_if_hot_or_held`), the `SetPoint.valid` data invariant, three kernel-evaluated `decide` examples. |
| `Main.lean` | The executable. Imports **only** `TempControl.Impl`; `computeFanCmd` is the only logic. |
| `lakefile.toml`, `lean-toolchain` | Build configuration and toolchain pin. |

The Impl/Spec split is load-bearing: because `Main` never imports the
specification, `lake exe` never elaborates the theorems — a tamper that
breaks a proof cannot fail the executable's build. Provability and behavior
stay **independent measurements** (demonstrated below).

## Measurements

Targets derive from a syntax scan of the package (`derive_targets_from_lean`,
block-comment aware). l2 slices are **named by declaration**, so attribution
names the tampered theorem.

| Protocol | Measures | How |
|---|---|---|
| `temp_control_lean_model` | 6 whole-file hashes: 4 `.lean` sources + `lakefile.toml` + `lean-toolchain` — the toolchain the proofs were checked under is inside the trust boundary | `hashfile` vs provisioned goldens |
| `temp_control_lean_contracts` | 15 declaration slices (Impl: 4, Spec: 8, Main: 3) | `readfile_range` vs provisioned goldens |
| `temp_control_lean_verification` | Provability: every theorem must still prove | `lake lean TempControl/Spec.lean -- --json` (builds imports first); appraiser fails on any `error` diagnostic **or `hasSorry` warning** — a `sorry` exits 0, so exit codes alone would bless it |
| `temp_control_lean_executable` | Behavior of the **pinned** built binary: hash vs the build-anchored golden, then one vector per GUMBO case — `(101, 70–90, Off)→On`, `(60, 70–90, On)→Off`, `(80, 70–90, On)→On` | hash-then-run: `hashfile(binary)` then `lake env <binary> <vector>` (never rebuilt); appraiser compares stdout to `expected` in the measurement args |
| `temp_control_lean_build` | Executable provenance: toolchain → input sources → `lake build` → output binary, one signature; the exec tier's binary golden is born from this bundle (see `signed_baselines.md`) | build event at provisioning; cross-linked baseline verification at every readiness gate |
| `temp_control_lean_model` | The administrator-blessed golden spec: `Spec.lean` signed whole-file at provisioning; the spec's hash and declaration-slice goldens must be derivable from blessed content (see `signed_baselines.md`) | `readfile` + SIG at provisioning; `model_slices_appr` at every readiness gate |

Three always-run entries, three independent trust questions:

    temp_control_lean:model     eval temp_control_lean_model: fail -> temp_control_lean_contracts refines (which declaration)
                                       -> [--repair] WholeFileRestoreKS
    temp_control_lean:verification    [--validate] eval temp_control_lean_verification: fail escalates directly
    temp_control_lean:executable  [--validate] eval temp_control_lean_executable:  fail escalates directly

## Demo arcs

```sh
python examples/temp_control_lean.py                # clean episode
python examples/temp_control_lean.py --validate     # + proof & behavior tiers
python examples/temp_control_lean.py --provision    # regenerate + re-provision
python examples/temp_control_lean.py --tamper --repair
python examples/temp_control_lean.py --tamper-semantic
python examples/temp_control_lean.py --check        # AM: declaration diff
python examples/temp_control_lean.py --promote      # AM: sanction a change
python examples/temp_control_lean.py --promote --expect hot=fanCmd=Off
```

**Structural tamper + repair** (`--tamper --repair`, log:
`demo_runs/2026-07-30_lean_tamper_repair.log`): a corrupted proof line makes
`temp_control_lean_model` fail on exactly `temp_control_lean_spec_targ`; `TierKS(temp_control_lean_contracts)` refines to
`temp_control_lean_spec_fanOn_when_hot_targ` (metadata `TempControl.Spec::fanOn_when_hot`
— the violated *theorem*, by name); `WholeFileRestoreKS` restores from
golden; the episode ends escalated as "repaired from golden — verification
pending next episode"; episode 2 attests clean. Repair cannot mint trust.

**Laundered semantic tamper** (`--tamper-semantic`, log:
`demo_runs/2026-07-30_lean_tamper_semantic.log`): the hot branch of
`computeFanCmd` is flipped `.On -> .Off` and the tree **re-provisioned** —
every hash measurement now blesses the tampered state:

    temp_control_lean:model:    all attested components intact (temp_control_lean_model passed)
    temp_control_lean:verification:   integrity violation — temp_control_lean_verification failed;
                   failing components: temp_control_lean_spec_check_targ
    temp_control_lean:executable: integrity violation — temp_control_lean_executable failed;
                   failing components: temp_control_lean_exec_hot_targ

The laundered change is refuted **twice, independently**: `fanOn_when_hot`
(and the kernel-evaluated `decide` example) no longer prove, and the binary
answers `fanCmd=Off` to the hot vector against expected `On`. The `expected`
vectors are AM-owned protocol config, not provisioned goldens — laundering
cannot reach them. A `sorry` shows the converse separation: proofs fail,
behavior still passes (`tests/test_integration_lean.py`).

**Sanctioned change** (`--check` / `--promote`, the out-of-band attestation
manager): the system is intent-blind — a provable, well-meant spec addition
fails episodes exactly like tamper until the administrator sanctions it.
Two artifacts change ONLY through `--promote`:

- the **`temp_control_lean_model` blessing**: ordinary provisioning (including a
  laundering pass) never re-signs it, so a spec change without promotion
  leaves a stale blessing that baseline verification refutes at readiness
  ("hash golden not derivable from blessed content") — attestation never
  starts;
- the **exec expecteds**: `--promote` re-runs the behavior vectors against
  the sanctioned build and refuses on divergence; a deliberate behavior
  change is sanctioned with `--expect KEY=VALUE`.

`--check` is the sanction review: a declaration-level diff of the live
sources against the baseline, matched by declaration *name* (added /
removed / modified / moved — a moved declaration is not a changed one; the
line-shifted `decide` examples report as moved, not violated). For
`Spec.lean` the baseline side is scanned from the **blessed signed bytes**,
not the l2 goldens — the goldens are launderable by re-provisioning, the
blessing is not (`changed_decls(props_protocol=...)`,
`tests/test_integration_lean.py::test_check_sees_through_laundered_l2_goldens`).

`--promote` is the sanctioning pipeline, gates before gold: behavior gate
(`lake build` + vectors vs sanctioned expecteds) → syntax-scan target
regeneration (a new theorem becomes a new *named* l2 target) → gold moves →
full provisioning including the props re-blessing → verification episode.
Promotion NEVER verifies: blessing is an authority act, and whether the
implementation proves against the blessed spec is that episode's honest
measurement (RED for a blessed-but-unmet spec).
A refused gate (behavior/codegen) leaves the old baseline fully in place: the promote request
runs alone on the blackboard, and provision requests are only written after
its outcome is known good. There is no `codegen_fn` for Lean — the
sanctioned build plays that role.

## Notes for appraiser authors

- `lean --json` emits one JSON diagnostic per line on stdout; a clean run
  emits nothing. A `sorry` is severity `warning`, kind `hasSorry`, exit 0.
- `lake` build progress goes to stderr; `lake exe` stdout stays pure even
  when the run triggers a rebuild. Non-JSON stdout lines are skipped by the
  diagnostics appraiser regardless (the cargo-verus cold-build lesson).
- Appraisal failure reasons travel unescaped inside the CVM's response JSON
  (fix pending on the CVM side): `run_command_lean_appr` sanitizes reasons
  to single-line, quote-free, bounded strings.

## Tests

- `tests/test_targetmap.py` — scanner shapes (block-comment false positive
  covered), live-tree derivation, declaration-named attribution.
- `tests/test_integration_lean.py` — fixtures-consistency (committed maps
  must equal the scan), clean attestation, tamper→attribution→repair→verify
  (auto-run when the CVM stack is present); the toolchain tiers — clean,
  sorry-separation, laundered double refutation — gated behind `RUN_LEAN=1`;
  sanctioned change — declaration diff (named add, moved examples),
  blessing-authoritative detection through laundered goldens, AM-owned
  expecteds with `--expect` sanction, and the full promote-and-rebless arc
  on scratch copies (`RUN_LEAN=1`).

**Toolchain identity** (see `signed_baselines.md`): both tiers hash the
lean invocation chain (wrapper → elan shim → pinned binaries →
elaborator library, 6 artifacts) in the same term, before invoking lake —
a tampered artifact anywhere on the chain fails both tiers attributed to
the `tool::` target, regardless of the tool's output.

## Artifact-class scheme (2026-08-04 restructure)

The protocol family was reorganized onto the common pipeline **full model
-> contracts -> verification -> executable**, one protocol per artifact
class (the Lean family is the pilot; ids above reflect it):

- `_model` merges the old props blessing and the model-file hash into ONE
  promote-owned protocol: per model file, readfile (blessed content) +
  hashfile (cheap episode check) under one SIG. Episodes re-run it; the
  provisioning bundle is the blessing.
- `_contracts` is the old l2 (declaration slices), now an ALWAYS-RUN
  entry as well as the refinement rung under `:model` — contract-region
  tamper cannot hide behind a passing hash tier.
- Realization files are NOT whole-file hashed anymore (design ruling):
  their attested property is that contract regions match the blessed
  baseline; the rest is developer-owned. Non-contract drift is caught
  where it matters — proofs run over live code, the binary is pinned.
- `_verification` and `_build`/`_executable` are the old check/build/exec
  renamed; build config and the toolchain pin are attested as build
  inputs. Build inputs without a source baseline self-anchor to the
  build bundle's own signed golden (model files still cross-link to the
  blessing).

## End-to-end lifecycle: blessing to attested verdict

The complete temp-control_Lean workflow (landing-gear_Lean is identical
modulo names — the shared driver's guarantee), from the administrator's
first blessing to a final attested verdict, with the specific Copland
protocols and ASPs at each step.

### Phase 0 — Derivation (configuration, no trust yet)

`derive_targets_from_lean` syntax-scans the Lake package and emits the
**contracts** target map: one `readfile_range` slice per top-level
declaration, *named by declaration*
(`temp_control_lean_spec_fanOn_when_hot_targ`, metadata
`TempControl.Spec::fanOn_when_hot`). The **model** protocol is assembled
from config (the spec file), the **verification/executable** tiers from
AM-owned config (the check command, the behavior vectors), and the
**build** protocol's inputs from `lean_package_files` (all sources +
`lakefile.toml` + `lean-toolchain`). Nothing here is trusted — these are
target *definitions*.

### Phase 1 — Provisioning: the administrator's blessing

`--provision` (bootstrap) or `--promote` (re-blessing) captures the
watched files into `golden/` and runs each protocol's **measurement-only
term (APPR stripped) against the golden copies**, signed by the CVM.
Each signed response becomes
`golden/_bundles/<pid>/provision_bundle.json`, and golden values are
extracted **from the signed evidence** (via the `extract_golden_slice`
ASP for slices) into the installed `asp_args.json` — goldens are born
from blessings, never alongside them.

Per protocol, at provisioning:

- **`temp_control_lean_model`** —
  `bseq(readfile⟨model_spec⟩, hashfile⟨model_spec_hash⟩) → SIG`. Signing
  the whole-file `readfile` content **is the administrator's blessing**
  of `Spec.lean`; the `hashfile` golden freezes with it under the same
  signature. Promote-owned: ordinary re-provisioning skips this protocol
  entirely, so laundering can never refresh it.
- **`temp_control_lean_contracts`** — `bseq(readfile_range ×15) → SIG`:
  the 15 declaration-slice goldens extracted from signed evidence.
- **`temp_control_lean_build`** — the executable class's provenance
  event, run *only* here: `bseq(hashfile ×6 toolchain) →
  bseq(hashfile ×6 package inputs) → run_command_lean("build") →
  hashfile(output binary) → SIG`. Evidence *order* witnesses
  tools→inputs→build→output under one signature. The executable tier's
  binary golden is then **cross-installed from this bundle's output
  evidence** (`install_build_outputs`) — the pinned binary is anchored
  to its build, not independently trusted.
- **`temp_control_lean_verification` / `_executable`** — provisioning
  hashes their six woven toolchain artifacts *measure-in-place* (live
  `lake` wrapper → elan shim → pinned `lean`/`lake`/`leanchecker` →
  `libleanshared.dylib`; no golden copies — the signed bundle protects
  the hashes) and, because provisioning runs the full term, the blessing
  bundle **contains an actual proof run and vector run** at signing
  time.

### Phase 2 — Readiness: every episode's gate

Before any attestation entry runs, the `temp_control_lean:ready` entry
(predicate `protocol_check`) validates config **and re-verifies every
signed baseline** via `verify_bundle`: an *appraisal-only CVM run* per
protocol — `TERM=APPR`, `EVIDENCE=` the stored bundle. The session's
`ASP_Comps` dispatch the appraisers over the signed evidence:

- **`sig_appr`** verifies the bundle signature over the raw evidence
  bytes.
- **`goldenbytes_appr`** anchors each installed golden (hashes, slices)
  to the signed measurement it came from.
- **`model_slices_appr`** does the deep check on the model blessing:
  injected with the hash golden and *every contract slice golden the
  contracts protocol installs for `Spec.lean`*, it re-extracts them with
  `readfile_range`'s exact semantics from the **blessed bytes** —
  proving all derived views are consequences of what the administrator
  signed.
- The **build bundle** verifies in cross-link mode: each event is
  anchored against *another* protocol's golden by role — tools ↔ the
  blessed toolchain hashes, the output ↔ the executable tier's enforced
  golden, and inputs ↔ a source baseline where one exists (`Spec.lean` ↔
  the model blessing) or the bundle's own signed golden otherwise.

A stale blessing (unsanctioned model change + re-provision) fails here —
*attestation never starts*.

### Phase 3 — The attestation episode: four entries, the pipeline verbatim

`StartAttestationKS` writes four entries; each runs its protocol through
`CvmSubprocessClient`, and responses are interpreted by the **formally
verified appraisal summary** (`copland_evidence_tools`'s
`do_appraisal_summary`, with its Permutation and provenance theorems) —
attribution is an `asp_targid` field read; every raw response is
gzip-archived to `evidence/` before interpretation.

1. **`temp_control_lean:model`** — runs the model term live: `hashfile`
   appraised by `goldenbytes_appr` against the blessed hash, `readfile`
   appraised by `model_slices_appr`'s content-equality check against the
   blessed bytes. **On fail**: `TierKS` re-points the entry to
   `temp_control_lean_contracts` — the slices name *which declaration*
   drifted — then (with `--repair`) `WholeFileRestoreKS` restores
   confirmed-violated files from golden, escalating as "repaired —
   verification pending next episode" (repair never mints trust).
2. **`temp_control_lean:contracts`** — the same contracts protocol as an
   **always-run sentinel** (each `readfile_range` slice vs
   `goldenbytes_appr`): contract-region tamper in developer-owned files
   can't hide behind a passing model hash. Both roles share one memoized
   CVM run.
3. **`temp_control_lean:verification`** (`--validate`) —
   measure-then-use: six toolchain `hashfile`s *sequenced before*
   `run_command_lean` executes `lake lean TempControl/Spec.lean --
   --json`; `run_command_lean_appr` (EXTEND-forwarded, so the tool's
   output survives into the response) fails on any `error` diagnostic
   **or `hasSorry`** — a `sorry` exits 0, so exit codes alone would
   bless it. Every theorem must prove *against the live implementation*.
4. **`temp_control_lean:executable`** (`--validate`) — hash-then-run:
   toolchain hashes, then `hashfile` of the **pinned** binary vs its
   build-anchored golden, then `run_command_lean` executes it directly
   (`lake env <bin>`, never rebuilt) on one vector per GUMBO case;
   `run_command_lean_appr` in expected-mode compares stdout to the
   `expected` values — which are **AM config, not provisioned goldens**,
   so laundering can't reach them.

`trust_summary` then renders the verdict per entry — the passing case is
the pipeline line by line: model, contracts, verification, executable
all intact.

### Phase 4 — Sanctioned change: `--check` / `--promote`

`--check` diffs live declarations against the **blessed model bytes**
(not the launderable contract goldens) via `changed_decls` —
added/removed/modified/moved, by name. `--promote` runs gates before
gold: `lake build` + behavior vectors vs sanctioned expecteds
(`--expect` is the only way to change them) → the verification protocol
must prove (interpreted exactly as an episode would) → contracts
re-derived → gold moves → **everything re-provisioned including the
model re-blessing** → a fresh verification episode. A refused gate
leaves the old baseline fully intact — the promote request runs alone on
the blackboard, and no provision request exists until its outcome is
known good.

### ASP roster

Measurement — `readfile`, `hashfile`, `readfile_range`,
`run_command_lean`, `sig`; appraisal — `sig_appr`, `goldenbytes_appr`,
`model_slices_appr`, `run_command_lean_appr`; provisioning support —
`extract_golden_slice`. The three independent trust questions never
collapse: provability (`verification`, live elaboration), behavior
(`executable`, pinned binary), and integrity (`model` + `contracts`,
blessed baseline) can each fail alone — which is exactly what the
tamper, sorry, and laundering demos exercise.
