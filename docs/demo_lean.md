# Lean example: attesting a specification and its executable

The temp-control model ported to a third verification ecosystem — Lean 4 —
alongside the JVM/Logika and Microkit/Verus examples. Nothing in the
blackboard/KS layer changed to admit it: the Lean ecosystem entered as two
ASPs (asp-libs `run_command_lean` / `run_command_lean_appr`), one targetmap
backend (`derive_targets_from_lean`), and four protocol dirs. That is the
architectural claim this example validates.

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
| `lean_l1a` | 6 whole-file hashes: 4 `.lean` sources + `lakefile.toml` + `lean-toolchain` — the toolchain the proofs were checked under is inside the trust boundary | `hashfile` vs provisioned goldens |
| `lean_l2` | 15 declaration slices (Impl: 4, Spec: 8, Main: 3) | `readfile_range` vs provisioned goldens |
| `lean_check` | Provability: every theorem must still prove | `lake lean TempControl/Spec.lean -- --json` (builds imports first); appraiser fails on any `error` diagnostic **or `hasSorry` warning** — a `sorry` exits 0, so exit codes alone would bless it |
| `lean_exec` | Behavior of the **pinned** built binary: hash vs the build-anchored golden, then one vector per GUMBO case — `(101, 70–90, Off)→On`, `(60, 70–90, On)→Off`, `(80, 70–90, On)→On` | hash-then-run: `hashfile(binary)` then `lake env <binary> <vector>` (never rebuilt); appraiser compares stdout to `expected` in the measurement args |
| `lean_build` | Executable provenance: toolchain → input sources → `lake build` → output binary, one signature; the exec tier's binary golden is born from this bundle (see `signed_baselines.md`) | build event at provisioning; cross-linked baseline verification at every readiness gate |
| `lean_props` | The administrator-blessed golden spec: `Spec.lean` signed whole-file at provisioning; the spec's hash and declaration-slice goldens must be derivable from blessed content (see `signed_baselines.md`) | `readfile` + SIG at provisioning; `model_slices_appr` at every readiness gate |

Three always-run entries, three independent trust questions:

    lean:files     eval lean_l1a: fail -> lean_l2 refines (which declaration)
                                       -> [--repair] WholeFileRestoreKS
    lean:proofs    [--validate] eval lean_check: fail escalates directly
    lean:behavior  [--validate] eval lean_exec:  fail escalates directly

## Demo arcs

```sh
python examples/lean_attestation.py                # clean episode
python examples/lean_attestation.py --validate     # + proof & behavior tiers
python examples/lean_attestation.py --provision    # regenerate + re-provision
python examples/lean_attestation.py --tamper --repair
python examples/lean_attestation.py --tamper-semantic
python examples/lean_attestation.py --check        # AM: declaration diff
python examples/lean_attestation.py --promote      # AM: sanction a change
python examples/lean_attestation.py --promote --expect hot=fanCmd=Off
```

**Structural tamper + repair** (`--tamper --repair`, log:
`demo_runs/2026-07-30_lean_tamper_repair.log`): a corrupted proof line makes
`lean_l1a` fail on exactly `lean_spec_targ`; `TierKS(lean_l2)` refines to
`lean_spec_fanOn_when_hot_targ` (metadata `TempControl.Spec::fanOn_when_hot`
— the violated *theorem*, by name); `WholeFileRestoreKS` restores from
golden; the episode ends escalated as "repaired from golden — verification
pending next episode"; episode 2 attests clean. Repair cannot mint trust.

**Laundered semantic tamper** (`--tamper-semantic`, log:
`demo_runs/2026-07-30_lean_tamper_semantic.log`): the hot branch of
`computeFanCmd` is flipped `.On -> .Off` and the tree **re-provisioned** —
every hash measurement now blesses the tampered state:

    lean:files:    all attested components intact (lean_l1a passed)
    lean:proofs:   integrity violation — lean_check failed;
                   failing components: lean_spec_check_targ
    lean:behavior: integrity violation — lean_exec failed;
                   failing components: lean_exec_hot_targ

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

- the **`lean_props` blessing**: ordinary provisioning (including a
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
(`lake build` + vectors vs sanctioned expecteds) → proof gate (`lean_check`
must prove, toolchain measured in the same term) → syntax-scan target
regeneration (a new theorem becomes a new *named* l2 target) → gold moves →
full provisioning including the props re-blessing → verification episode.
A refused gate leaves the old baseline fully in place: the promote request
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
