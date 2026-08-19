# Verus upgrade spike: `--no-cheating` scoping on the isolette crates

2026-08-19. Question: can a newer Verus give us a per-crate (eventually
per-module) `--no-cheating` gate for the isolette attestation demo, and
what would the upgrade cost? Method: download Verus 0.2026.08.09 into a
scratch dir, copy `targets/isolette-microkit/hamr/microkit/crates` beside
it, bump the pins, and test every cell of the matrix. **Nothing in the
repo was modified.**

## Baseline (what blocked us on the pinned toolchain)

The pinned distribution is `verus-arm64-macos` **0.2026.01.23.1650a05**
(rust nightly-2026-01-25 / vstd `=0.0.0-2026-01-25-0057`). Its
`--no-cheating` exists but cargo-verus forwards the flag to **every**
crate in the dependency graph, including vstd — which legitimately uses
admit/external_body — so the gate fails on vstd before the primary crate
is reached, for every crate in the tree. cargo-verus 0.2026.01 has no
per-package scoping (checked CLI and the `[package.metadata.verus]` keys
in the binary: `verify`, `no-vstd`, `is-vstd`, `is-core`, `is-builtin`,
`is-builtin-macros`).

## What upstream added since

| Change | Where | Merged |
|---|---|---|
| `--fwd-verus-args-to all\|roots\|deps` (scope forwarded verus args) | cargo-verus, [PR #2277](https://github.com/verus-lang/verus/pull/2277) | 2026-03-31 |
| `--no-cheating` violations collected as per-function `failed_proof_notes` in `--output-json` | rust_verify, [PR #2199](https://github.com/verus-lang/verus/pull/2199) | 2026-02-22 |
| original `--no-cheating` | [PR #1499](https://github.com/verus-lang/verus/pull/1499) | 2025-03-21 |
| vstd exemption groundwork | [PR #1779](https://github.com/verus-lang/verus/pull/1779) | 2025-07-21 |
| per-module policies (`#![deny(verus::assumptions)]` + `#[allow]` on module decls, function-level "audit the signature only") | [PR #2568](https://github.com/verus-lang/verus/pull/2568), [discussion #1292](https://github.com/verus-lang/verus/discussions/1292) | **open** |

Spike used release `0.2026.08.09.92f466f` — the newest whose matching
vstd (`=0.0.0-2026-08-09-0044`) was on crates.io (0.2026.08.15 was out
but its vstd was not yet published). Requires rust **1.97.1** with
`rust-src`, `llvm-tools-preview` (`rustup install 1.97.1`), and
`RUSTC_BOOTSTRAP=1` for the `-Z build-std` embedded builds (the
run_command_cargo_verus ASP already sets it).

## Results

### The gate works (host crates)

Recipe (two phases; phase 1 builds deps with vstd unverified, matching
how bare `verus` trusts the prebuilt vstd.vir):

```bash
cargo verus verify --fwd-verus-args-to deps  -- --no-verify
cargo verus verify --fwd-verus-args-to roots -- --output-json --no-cheating
```

| Crate | Plain verify | Gated |
|---|---|---|
| `data` | 20 verified / 0 errors | **passes clean** |
| `GUMBO_Library` | 0 obligations / 0 errors | **passes clean** |
| `data` + injected `proof fn spike_cheat() ensures false { assume(false); }` | **21 verified / 0 errors — accepted silently** | **refused**: `error: assume/admit not allowed with --no-cheating` |
| `sys_nominal_proof` | 1862 verified / 0 errors (identical to 0.2026.01) | 26 rejections — exactly its 26 `uninterp spec fn`s in `src/actions.rs` |

Notes:

- The `sys_nominal_proof` rejections are **hard errors**
  (`external_body/assume_specification not allowed`), not #2199 proof
  notes: the JSON carries `obligation_proof_notes` / `failed_proof_notes`
  on all 2142 functions but they stay empty for this violation class
  (notes cover assume-inside-proof obligations). Fine for gate crates
  (errors ≠ 0 refuses); it means the gate stays all-or-nothing for
  crates with any blessed escape until #2568's per-module `allow` lands.
- Registry vstd `2026-08-09` **fails its own verification** under
  cargo-verus (1 error, `GhostSubseq::agree_map` postcondition,
  deterministic, rlimit-independent). The deps-phase `--no-verify`
  sidesteps it.
- cargo-verus arg-order rules: `--fwd-verus-args-to` before the
  forwarded `-Z`/`--target` cargo options; `--lib` after them (verus
  says "Verus-relevant cargo options must precede Verus-irrelevant
  ones"). The component-crate **bin** target no longer builds under
  `verify` (E0463: bin wants std on aarch64-unknown-none) — scope with
  `--lib`.

### The blockers (component crates)

The seven HAMR-generated component crates are **source-incompatible**
with Verus ≥ 0.2026.08, independent of the gate:

1. **New mutable-reference semantics** (`migration-mut-ref.md`): bare
   `self` in an ensures clause of a `&mut self` fn must now be
   `old(self)`/`final(self)`. Hits every generated `bridge/*_api.rs`
   (`ensures old(self).x == self.x, ...`). **Workaround verified**:
   `#![verifier::deprecated_postcondition_mut_ref_style(true)]` at crate
   root restores the old reading — but the attribute is documented as
   temporary.
2. **Ghost-field update tightening** — no workaround found:

   ```
   error: cannot access spec-mode place in executable context
     --> src/bridge/thermostat_rt_mhs_mhs_api.rs:87
      |      self.heat_control = value;
   ```

   `heat_control` is a `pub ghost` field of the generated
   `Application_Api` struct, assigned from exec code — the core of how
   HAMR emits ghost-port tracking, in every component crate.

Both fixes belong in **HAMR codegen** (the files are do-not-edit
generated artifacts; patching them locally is exactly the tampering the
demo refuses). See
[draft_hamr_verus_migration_report.md](draft_hamr_verus_migration_report.md).

### What the upgrade would buy the attestation demo

On the newer toolchain, `--output-json` gains a `func-details` object
**keyed by fully-qualified function name** (2142 entries on
`sys_nominal_proof`). Goldening that key SET — not just the verified
cardinality — would catch drop-and-replace *semantically*: dropping
`…::vc_pre_assert_oi` and adding `…::dropped_and_replaced` changes the
set even at constant count. On the pinned toolchain the evidence is only
the scalar count, so drop-and-replace is caught instead by the
whole-file `sysproof` hash tier (see
[cheat_tier_plan.md](cheat_tier_plan.md) §D and demo scene 10). The
func-details-set golden is the upgrade-gated stronger form, and would
let the `sysproof` hash tier relax to source that legitimately changes.

## Decision

**Upgrade deferred.** The gate mechanism is proven, but the exemplar's
generated component code can't compile under new Verus until HAMR
migrates, and the crate the gate matters most for (`sys_nominal_proof`)
needs #2568's per-module policies anyway. The cheat tier
(`cheat_scan_verus`, scene 9) plus the verified-count golden cover every
crate today. Revisit when (a) HAMR targets a newer Verus, or (b) #2568
merges. Upstream drafts:
[draft_hamr_verus_migration_report.md](draft_hamr_verus_migration_report.md),
[draft_verus_2568_comment.md](draft_verus_2568_comment.md).

Split-toolchain fallback (considered, not taken): keep 0.2026.01 for the
verus tier, add a second hashed 0.2026.08 distribution gating only
`data` + `GUMBO_Library`. Real but modest value — both crates are
already cheat-scanned — at the cost of a second Verus in the trust base.
