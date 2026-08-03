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

    isl_l1a    13 whole-file hashes (AADL packages + contract-bearing Rust)
    isl_l2     67 slices: GUMBO contracts in AADL + Verus/Rust realizations
    isl_props  5 blessed model files — the AADL packages the 40 Model
               slices live in, signed whole-file at provisioning
    isl_verus  [--validate] cargo-verus verify of the 7 contract-bearing
               crates: the generated contracts must PROVE (91 verified /
               0 errors on the implemented tree; a freshly generated
               SKELETON is correctly refuted — postconditions unprovable
               with empty developer regions)

Every episode's readiness gate verifies the three signed baselines before
attestation (`signed baselines verified (isl_l1a, isl_l2, isl_props)`).

```sh
python examples/isolette_attestation.py [--check] [--provision]
    [--tamper-verus] [--repair] [--validate]
```

Arcs: `--tamper-verus --repair` corrupts a Verus contract slice in
`thermostat_rt_mhs` — l1a detects, l2 attributes the exact slice,
whole-file repair restores from golden, episode 2 verifies. `--validate`
confirms a passing l1a with the Verus tier (warm caches recommended; cold
builds are multi-minute and RUN_VERUS-gated in tests). The laundering
negative — re-provisioning the measurement baselines over a tampered
golden tree, refuted only by the administrator's blessing — is an
automated test; see `signed_baselines.md`.

Toolchain identity (see `signed_baselines.md`): `isl_verus` hashes the
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
`examples/isolette_attestation.py --frontend sysml` runs the identical
workflow off the SysML report under its own protocol namespace:

    isy_l1a (13 hashes) / isy_l2 (67 slices) / isy_props (5 blessed
    model files) / isy_verus (7 crates) — entries isy:files / isy:ready

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
  pre-SysML behavior — regeneration reproduces the committed `isl_*`
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
