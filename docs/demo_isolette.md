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
