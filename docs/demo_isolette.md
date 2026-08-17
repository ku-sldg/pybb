# Isolette example: the INSPECTA seL4/Microkit exemplar

`targets/isolette-microkit` vendors the isolette from
[INSPECTA-models](https://github.com/loonwerks/INSPECTA-models): the AADL
model with GUMBO contracts (`aadl/`, 16 packages, system
`Isolette.Single_Sensor`) plus the generated-and-implemented
Microkit/Rust tree with its HAMR attestation report — report and crates
coherent from one generation. This is the scale validation of the
report-driven workflow the temp-control-microkit example established, and
the first carrier of the signed golden-spec (props) design.

The report is the authority (13 files, 67 slices: 40 Model / 23 Verus /
4 Rust; a fixtures-consistency test enforces committed == derived):

    isolette_aadl_rust_l1a    13 whole-file hashes (AADL packages + contract-bearing Rust)
    isolette_aadl_rust_l2     67 slices: GUMBO contracts in AADL + Verus/Rust realizations
    isolette_aadl_rust_props  5 blessed model files — the AADL packages the 40 Model
               slices live in, signed whole-file at provisioning
    isolette_aadl_rust_verus  [--validate] cargo-verus verify of the 7 contract-bearing
               crates: the generated contracts must PROVE (91 verified /
               0 errors on the implemented tree; a freshly generated
               SKELETON is correctly refuted — postconditions unprovable
               with empty developer regions)

Every episode's readiness gate verifies the three signed baselines before
attestation (`signed baselines verified (isolette_aadl_rust_l1a, isolette_aadl_rust_l2, isolette_aadl_rust_props)`).

```sh
python examples/isolette_rust.py [--check] [--provision]
    [--tamper-verus] [--repair] [--validate]
```

**The demo script**: `examples/demo_isolette.sh` walks the eight-scene
demo workflow (the Rocq demo's outline) on the SysML frontend — see
[demo_isolette_script_summary.md](demo_isolette_script_summary.md).
The scenes ride on additional driver flags: `--ready` / `--status`
(readiness gate and the per-crate proof checklist), `--verify` (the
always-run verification + report-rendering entries), `--bless-props`
(spec-first re-blessing under `--provision`), `--immutable-model` /
`--repair-granularity slice` / `--restore-crates` / `--repair-impl` /
`--regen-report` (repair rungs with in-session re-attestation),
`--pause` (the out-of-band rung), and the `--tamper-*` arcs the scenes
exercise.

Arcs: `--tamper-verus --repair` corrupts a Verus contract slice in
`thermostat_rt_mhs` — l1a detects, l2 attributes the exact slice,
whole-file repair restores from golden, episode 2 verifies. `--validate`
confirms a passing l1a with the Verus tier (warm caches recommended; cold
builds are multi-minute and RUN_VERUS-gated in tests). The laundering
negative — re-provisioning the measurement baselines over a tampered
golden tree, refuted only by the administrator's blessing — is an
automated test; see `signed_baselines.md`.

Toolchain identity (see `signed_baselines.md`): `isolette_aadl_rust_verus` hashes the
verus toolchain in the same term, before the verifications; `hamr_tools`
(sireum.jar + OSATE plugins) is blessed measure-in-place and re-measured
by the promotion gate immediately before codegen.

## SysML v2 frontend (`--frontend sysml`)

HAMR's attestation reporter is frontend-agnostic: the same Microkit
backend plugin emits `aadl_attestation_report.json` or
`sysml_attestation_report.json` depending only on the model language it
was fed, and INSPECTA ships BOTH reports over its single implemented
tree. `targets/isolette-microkit` therefore vendors both frontends —
the AADL workspace (`aadl/`) and the SysML v2 model (`sysml/`, textual,
no OSATE/phantom required for codegen) — and
`examples/isolette_rust.py --frontend sysml` runs the identical
workflow off the SysML report under its own protocol namespace:

    isolette_sysmlv2_rust_l1a (13 hashes) / isolette_sysmlv2_rust_l2 (67 slices) / isolette_sysmlv2_rust_props (5 blessed
    model files) / isolette_sysmlv2_rust_verus (7 crates) — entries isolette_sysmlv2_rust:files / isolette_sysmlv2_rust:ready

Verified properties:

- **Slice parity**: the two reports' Verus/Rust realization slices are
  SET-EQUAL over the shared implemented crates; only the 40 Model-kind
  slices move (5 `.aadl` workspace files vs 4 `.sysml` files — plus, in
  both reports, one Model-classified Verus spec fn in a generated
  app.rs, which the blessing covers in both; the report's kind
  classification is the authority, not the file extension).
- Both baselines coexist: each frontend has its own signed blessing and
  goldens; shared crate files provision byte-identical golden copies.
- AM detection speaks SysML: `changed_contracts(model_suffix=".sysml")`
  names a revised GUMBO guarantee in `Regulate.sysml`
  position-independently.
- The default (`--frontend aadl`, implied) is byte-identical to the
  pre-SysML behavior — regeneration reproduces the committed `isolette_aadl_rust_*`
  fixtures exactly.

Codegen from SysML (not needed for attestation; the committed report is
the authority) is a single call — no OSATE:
`sireum hamr sysml codegen -p Microkit --workspace-root-dir sysml ...`
with the santoslab sysml-aadl-libraries on `--sourcepath`, **pinned no
newer than the Sireum release** (newer library commits crash older
frontends with an empty `halt("")` in
`Instantiate.allowedDataComponentMembers`). A `--promote` with real
SysML codegen is the natural follow-up; the regeneration-coherence
story for the implemented crates (developer-owned app.rs) is the open
piece.

## Sanctioned change: `--promote` (SysML frontend exercised; AADL wired)

Both artifacts the AM owns — the props blessing and the report-derived
baseline — change only through `--promote` (or first-time bootstrap):
an ordinary `--provision` re-blesses measurements but keeps the model
blessing, so an unsanctioned model change followed by re-provisioning
leaves a stale blessing that readiness refutes.

The pipeline (gates before gold, two blackboard runs — no provision
request exists until the promote outcome is known good):

1. **Tool gate**: the HAMR toolchain and, for SysML, the pinned
   `sysml-aadl-libraries` (codegen INPUT measured like a tool — 17
   library files, `sysml_libs` protocol) hashed live against blessed
   goldens immediately before use. Contract laundering through a
   library edit is refused here, before any codegen runs.
2. **Real codegen, in place**: `sireum hamr sysml codegen -p Microkit`
   regenerates the tree AND the report — the one step re-provisioning
   alone can never do. No OSATE. (The AADL frontend's phantom+codegen
   path is wired for parity but its first supervised migration has not
   been run.)
3. **Proof gate**: the Verus tier must prove against the regenerated
   contracts (interpreted exactly as an episode would).
4. Report-driven target regeneration → gold moves → full provisioning
   including the props re-blessing → verification episode.

**The first supervised migration (2026-08-04)** brought the vendored
tree from INSPECTA's generation to Sireum v4.20260720: two crates
renamed (`domain_monitor`, `sys_nominal_proof`; orphaned old-name dirs
removed), generated files regenerated, and — notably — codegen
re-spliced contract MARKER REGIONS inside two developer-owned app.rs
files (model/toolchain drift in a REQ_MRI_9 ensures clause; the
implemented behavior still proves, 7/7 crates). The realization slices
kept their positions, so the AADL/SysML report parity held; the AADL
measurement baseline was re-provisioned over the migrated tree (its
props blessing covers untouched files and stayed valid).

The migration also surfaced — and forced the fix of — a latent
appraiser bug: COLD cargo-verus builds pollute stdout ahead of the
verification JSON, and the post-codegen proof gate is ALWAYS cold, so
the gate refused spuriously on first run (fail-closed, wrong reason).
`run_command_verus_appr` (asp-libs) now extracts the JSON robustly;
verdicts depend only on verification results, never build temperature.
