# Plan: cheat-tier hardening (uninterp + verified-count + proof-crate hash)

**STATUS: implemented** (asp-libs `9de558a`; pybb — cheat/verus/sysproof
tiers, scenes 9–10, tests). All three attack classes validated
end-to-end. Sections below are the as-built design.

Finalized after the Verus-upgrade spike (see
[verus_upgrade_spike.md](verus_upgrade_spike.md)). `--no-cheating`
gating is deferred (blocked on HAMR codegen migration + verus#2568);
these steps run on the pinned 0.2026.01.23 toolchain and close the
axiom/assume + drop-and-replace attack surface.

## A. asp-libs: `cheat_scan_verus` gains `uninterp`
Word-boundary `uninterp` count. Baseline: 26 in
`sys_nominal_proof/src/actions.rs` (component-action abstractions for the
commutativity VCs), 0 elsewhere.

## B. asp-libs: `run_command_cargo_verus` normalizes evidence
Emit canonical `{"verification-results": <obj>}` (brace-scan the JSON out
of stdout — cold-build noise immune — drop timings/version). Deterministic
warm/cold, so it can be goldenbytes-appraised. `run_command_verus_appr`
still finds `verification-results.errors`; `verus_crate_checklist` still
reads `verification-results`. Temp_control/find_max unaffected (they
appraise semantically, not by golden bytes).

## C. isolette verus tier: verified-count golden + system proof crate
- Switch `run_command_cargo_verus`'s companion appraiser to
  `goldenbytes_appr` (exact bytes vs golden). Provisioning goldens each
  crate's `verification-results`; drift (verified-count shrink, errors,
  success/`is-verifying-entire-crate` games) refuses. Drop `--time` from
  `VERUS_ARGS`.
- Add `sys_nominal_proof` as an 8th verus target — host-target `verify`
  (~3s warm, no `-Z build-std`), golden pins `verified: 1862`.

## D. isolette: dedicated `sys_nominal_proof` hash protocol
The report is component-scoped and never names `sys_nominal_proof`
(confirmed: 0 references), so it can't ride l1a's report derivation. Add
an AM-owned hash protocol built like `build_tools_protocol_dir`:
whole-file hash of `sys_nominal_proof/src/**/*.rs` + SIG + APPR,
`goldenbytes_appr`, provisioned + readiness-checked. Whole-file (no
benign-drift region) is correct for a do-not-edit generated crate. This
is the layer that stops drop-one-add-trivial (which preserves the
verified count) — any byte change refuses.

## E. Wiring / docs / tests
Re-provision; clean episode; `--tamper-cheat` scene 9; new checks:
verified-count tamper (comment a VC module → verus tier refuses),
drop-and-replace tamper (→ sys_nominal hash refuses). Update
`demo_isolette*.md` + scene-9 summary; extend `test_cheat_scan.py` +
normalized-evidence shape test. Record the func-details-set golden
(newer toolchain) as the upgrade-gated stronger form of C.

## Coverage recap
Scan (A + existing categories): introduce-an-escape attacks —
assume/admit/external_body(by path)/bare-external/assume_specification/
external_*_specification/axiom/broadcast/uninterp, per-crate vs pinned
counts. Verified-count golden (C): shrink-the-surface attacks (code out
of `verus!{}`, deleted/emptied modules, success-flag games) that carry
no textual tell. Proof-crate hash (D): drop-and-replace at constant
count. Residual gaps (documented): contract-weakening (caught by
l2+props elsewhere), vacuous `requires false` (no native Verus check).
