# DRAFT — upstream report: HAMR-generated Verus code vs Verus ≥ 0.2026.02

Draft for an issue against the HAMR Rust/Microkit codegen (or
INSPECTA-models, wherever generated-code compatibility is tracked).
Findings from building the isolette exemplar's generated crates
(`isolette-microkit`, HAMR SysMLv2→Rust, pinned Verus
0.2026.01.23.1650a05) against Verus 0.2026.08.09.92f466f. Review and
adjust before posting.

---

**Title**: Generated Verus contracts don't compile under Verus ≥ 0.2026.08
(new mut-ref postcondition semantics; exec-context ghost-field updates)

**Summary.** The Rust/Microkit codegen emits two patterns that recent
Verus releases reject. The generated crates therefore pin
`nightly-2026-01-25` / vstd `0.0.0-2026-01-25-0057` and cannot move to
current Verus, which now ships features relevant to certification
workflows (scoped `--no-cheating` via cargo-verus
`--fwd-verus-args-to`, verus-lang/verus#2277; structured
`failed_proof_notes` in `--output-json`, verus-lang/verus#2199).

**Pattern 1 — bare `self` in `&mut self` postconditions** (every
generated `bridge/*_api.rs`):

```rust
pub fn put_heat_control(&mut self, value: Isolette_Data_Model::On_Off)
  ensures
    old(self).current_tempWstatus == self.current_tempWstatus,  // <-- here
    self.heat_control == value,
```

Under the first-class mut-ref migration
(`source/docs/migration-mut-ref.md`) this is now an error: "to
dereference a mutable reference parameter in a postcondition,
disambiguate by wrapping it in either `old` or `final`". Fix: emit
`final(self).…` (or migrate per the doc). Stopgap that works today:
emit `#![verifier::deprecated_postcondition_mut_ref_style(true)]` at
the crate root — but Verus documents the attribute as temporary.

**Pattern 2 — exec-context assignment to `ghost` fields** (every
generated `bridge/*_api.rs`; no compatibility attribute found):

```rust
pub struct thermostat_rt_mhs_mhs_Application_Api<API: …> {
  pub api: API,
  pub ghost heat_control: Isolette_Data_Model::On_Off,
  …
}
…
self.api.unverified_put_heat_control(value);
self.heat_control = value;        // error: cannot access spec-mode
                                  // place in executable context
```

Newer Verus requires the ghost update to be wrapped (e.g.
`proof { self.heat_control = value; }` — to be confirmed against
current idiom). This is the ghost-port tracking pattern, so it affects
every component crate.

**Also observed** (minor): under `cargo verus verify` on
`aarch64-unknown-none`, the generated **bin** target now fails with
E0463 (bin requires std); scoping with `--lib` works. Worth confirming
what the recommended invocation is for no_std bin crates.

**Environment.** Verus 0.2026.08.09.92f466f (rust 1.97.1,
`RUSTC_BOOTSTRAP=1`, `-Z build-std=core,alloc,compiler_builtins
--target aarch64-unknown-none`), vstd `=0.0.0-2026-08-09-0044`.
Positive control: the generated `sys_nominal_proof` crate (no `&mut
self` contracts, no ghost-field exec updates) verifies unchanged on the
new toolchain — 1862 verified / 0 errors, identical to 0.2026.01.

**Ask.** Emit new-Verus-compatible syntax for the two patterns (or gate
by a target-Verus-version codegen option), so generated projects can
track current Verus releases.

---

*(End of draft.)*
