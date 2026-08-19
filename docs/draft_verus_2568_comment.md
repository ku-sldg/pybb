# DRAFT — comment for verus-lang/verus#2568 ("nuanced no-cheating policies")

Draft comment describing the remote-attestation use case, to post on
[PR #2568](https://github.com/verus-lang/verus/pull/2568) (or the linked
[discussion #1292](https://github.com/verus-lang/verus/discussions/1292)).
Review and adjust before posting.

---

Adding a use case from a remote-attestation / certification setting, in
case it helps shape the policy design.

We measure a HAMR-generated seL4/Microkit system (the INSPECTA isolette
exemplar) with an attestation framework: an appraiser periodically
re-verifies the Verus crates and compares evidence against signed golden
baselines. "Verification succeeded" alone is not enough evidence — a
`assume(false)` smuggled into a proof body verifies with the same
"N verified / 0 errors" — so we also measure *how* verification
succeeded: the crate's proof-escape surface
(assume/admit/external_body/uninterp/axiom counts) against a blessed
baseline.

`--no-cheating` is the semantic version of that check, and with
cargo-verus `--fwd-verus-args-to roots` (#2277) it now works well as a
hard gate on crates with **zero** escapes: any introduced cheat fails
verification itself, which our appraisal machinery picks up with no
extra logic.

Where we hit its limits — and where this PR seems aimed:

1. **Trusted-module allowlists.** Our system-level proof crate
   (`sys_nominal_proof`, ~1900 verified declarations) is escape-free
   except for one generated module of 26 `uninterp spec fn`s — component
   behaviors abstracted for commutativity VCs, proved for all
   interpretations. Today `--no-cheating` rejects the whole crate on
   those 26 declarations, so the crate where the gate would matter most
   can't use it. `#![deny(verus::assumptions)]` +
   `#[allow(verus::assumptions)] mod actions;` is exactly the shape we
   need, and the transitive-closure/file-level-module auditability rules
   fit an attestation setting well (the allowlist itself becomes part of
   the measured, signed baseline).

2. **Machine-readable policy violations.** #2199's `failed_proof_notes`
   are great for assume-class violations, but external_body /
   assume_specification / uninterp rejections surface only as fatal
   diagnostics. For appraisal we'd love *all* no-cheating violations
   (and, ideally, the accepted-because-allowlisted items) reported
   structurally in `--output-json` — that would let a remote appraiser
   golden-compare the full escape inventory semantically, rather than
   falling back to textual scanning of the source.

3. **Snapshot/tamper angle.** The PR discussion mentions snapshotting
   trusted definitions to detect tampering — that is precisely our
   workflow (signed golden baselines, drift refuses), so a stable,
   canonical serialization of "the trusted surface" (allowlisted
   modules, exempted signatures) would slot straight into evidence
   comparison.

Happy to provide more detail on the setup or test candidate designs
against it.

---

*(End of draft.)*
