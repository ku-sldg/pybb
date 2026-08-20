# Plan: cheat-tier hardening (uninterp + verified-count + proof-crate hash)

**STATUS: implemented, then section C SUPERSEDED.** The verified-count
golden (C) was reverted when promotion was decoupled from verification:
a promotion that blesses a broken spec must not capture failing
verification-results as the golden and then match them (a golden of
failure attests green). The Verus tier now judges CORRECTNESS
(`run_command_verus_appr`, errors==0), so a blessed-but-unmet spec
attests RED honestly; surface-shrink coverage moved to the hash tiers
(sysproof for the proof crate; the component-contract-file gap is a
tracked follow-up — see "Superseded" note in C). The cheat scan (A) and
the sysproof hash (D) stand as built. Sections below are the original
as-built design; read C with its superseding note.

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
> **SUPERSEDED** (promotion/verification decoupling). The count golden
> is reverted to `run_command_verus_appr` (errors==0). Rationale: with
> promotion no longer verifying, a broken-spec bless would provision the
> failing `verification-results` AS the golden and then match it →
> false green. Correctness (errors==0) reports RED honestly instead.
> `sys_nominal_proof` stays an 8th verus target (now judged errors==0,
> not a pinned count). `--time` still dropped. Surface-shrink coverage:
> sysproof hash (D) for the proof crate; the 10 unhashed contract-bearing
> component files (incl. the deliberately-unhashed scene-9 cheat site
> `mhs_api.rs`) are a tracked follow-up needing per-file/scene decisions.

*(original plan:)*
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
whole-file hashes of `sys_nominal_proof` (Cargo.toml +
rust-toolchain.toml + `src/**/*.rs`) + SIG + APPR, provisioned +
readiness-checked. Whole-file (no benign-drift region) is correct for a
do-not-edit generated crate. This is the layer that stops
drop-one-add-trivial (which preserves the verified count) — any byte
change refuses.

**Revised to batched form** after the first shape proved prohibitively
slow: 124 per-file `hashfile` targets made a 123-deep bseq chain whose
CVM cost is superlinear in chain length (measured 13→0.09s, 67→6.4s,
124→33s per appraisal pass; balanced tree only halves it), paid at
every readiness gate AND every episode (`--ready` 40s, scene 1 86s).
As-built: ONE `hashfile_many` target ({root, files, walk_dirs} →
canonical {relpath: sha256-b64} map, `hashfile_many_appr` names every
drifted/missing/added path in the refusal). Same coverage plus
ADDED-file detection (the walk self-enumerates, so a new file drifts
the evidence — per-file target lists can't see additions), attribution
preserved in the verdict reason. `--ready` 40s→7s, scene 1 86s→16s.

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
counts. ~~Verified-count golden (C)~~ SUPERSEDED — shrink-the-surface
attacks (code out of `verus!{}`, deleted/emptied modules) are now the
hash tiers' job (D for the proof crate; component-contract-file gap
tracked). Proof-crate hash (D): drop-and-replace at constant
count. Residual gaps (documented): contract-weakening (caught by
l2+props elsewhere), vacuous `requires false` (no native Verus check).
