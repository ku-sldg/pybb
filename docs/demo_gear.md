# Landing-gear example: a second Lean scenario as pure configuration

The classic avionics retraction interlock — the lever may command
retraction, but the gear must never retract on the ground
(weight-on-wheels) or below the configured retraction speed — modeled in
Lean 4 at `targets/landing-gear-lean` and attested by the same six-protocol
workflow as the temp-control Lean example.

The architectural claim this example validates: **the second scenario is
pure configuration.** `examples/landing_gear_lean.py` is a
`LeanExampleConfig` (~40 lines of data: package root, protocol prefix,
spec file, binary name, behavior vectors, tamper spots) over the shared
driver `examples/lean_workflow.py`, which was factored out of the
temp-control example without behavior change. Every flag —
`--check/--provision/--promote/--expect/--tamper/--tamper-semantic/
--repair/--validate` — and every trust mechanism (scan-derived targets,
signed baselines, JIT tool measurement, build-event provenance, the
props/expecteds AM-ownership rules) comes free.

## The target

`targets/landing-gear-lean` — a Lake package (core Lean v4.31.0, same
toolchain pin as temp-control, so the blessed tool set is shared):

| File | Role |
|---|---|
| `LandingGear/Impl.lean` | `GearLever`, `GearCmd`, `Config{retractSpeed}`, `computeGearCmd`. Proof-free. Lever Down always extends; lever Up retracts only airborne at or above `retractSpeed`, else holds. |
| `LandingGear/Spec.lean` | The contracts as theorems: `Config.valid` (envelope bounds), `extend_when_commanded` (extension is never inhibited), **`no_retract_on_ground`** (the star), `no_retract_below_speed`, `retract_when_safe`, and the safety converse `retract_only_when_safe` (retraction ⇒ lever Up ∧ airborne ∧ at speed); three kernel-evaluated `decide` examples. |
| `Main.lean` | Imports **only** Impl. `landing-gear <speed> <retractSpeed> <Up\|Down> <wow\|air>` → `gearCmd=<Retract\|Extend\|Hold>`. |

## Protocols and entries

`gear_l1a` (6 whole-file hashes) / `gear_l2` (18 declaration slices, named
— attribution reads `LandingGear.Spec::no_retract_on_ground`) /
`gear_props` (the blessed spec) / `gear_check` (proofs must prove) /
`gear_exec` (hash-then-run, one vector per contract case) / `gear_build`
(the build event; the exec binary golden is born from its bundle).

Behavior vectors (`expected` is AM config — laundering cannot reach it):

    ground    80 140 Up wow  -> gearCmd=Hold     (the interlock)
    airborne  180 140 Up air -> gearCmd=Retract
    extend    200 140 Down air -> gearCmd=Extend

Entries: `gear:files` (fail → `gear_l2` refines → `--repair` restores),
`gear:proofs`, `gear:behavior`.

## Demo arcs

```sh
python examples/landing_gear_lean.py --validate
python examples/landing_gear_lean.py --tamper --repair
python examples/landing_gear_lean.py --tamper-semantic
python examples/landing_gear_lean.py --check
python examples/landing_gear_lean.py --promote
```

**Structural tamper + repair**: a corrupted proof line is attributed to
`gear_spec_no_retract_on_ground_targ` — the violated safety theorem, by
name — restored from golden, verified clean by episode 2.

**Laundered interlock removal** (`--tamper-semantic`): the Up/wow arm of
`computeGearCmd` flips `Hold -> Retract` — the gear retracts on the
ground — and the whole tree is re-provisioned, build event included, so
every hash measurement blesses it. Refuted anyway, fail-closed at
readiness, four times over by proof and once by behavior:

- `no_retract_on_ground`, `no_retract_below_speed`, and
  `retract_only_when_safe` no longer prove;
- `decide` **proves the on-ground proposition false** (a decidable
  counterexample, not a mere proof failure);
- the rebuilt binary answers `gearCmd=Retract` to the ground vector
  against expected `Hold`.

**Sanctioned change** (`--check`/`--promote`): identical machinery to the
temp-control example (see `demo_lean.md`) — declaration-name diffs against
the blessed spec bytes, promotion gates before gold, `gear_props` and the
exec expecteds change only through `--promote`.

## Tests

`tests/test_integration_gear.py` — fixtures-consistency (committed maps
must equal the scan), clean attestation, interlock tamper →
attribution → repair → verify, config-driven AM detection and expecteds;
gated behind `RUN_LEAN=1`: tiers clean with woven tools, and the
interlock removal refuted by proof while the pinned binary stands.
