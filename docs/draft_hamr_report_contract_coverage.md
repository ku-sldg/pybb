# DRAFT — report for the HAMR team: attestation-report contract-slice coverage

Draft note describing a completeness gap in the HAMR attestation
report's Verus-realization slices, to file with the HAMR / Sireum team
(target repo/issue TBD — the K-State HAMR authors). Review and adjust
before posting. Discovered 2026-08-27 while building a lifecycle-
attestation demo over the SysMLv2 → Rust isolette exemplar.

---

## Context

We measure a HAMR-generated seL4/Microkit system (the INSPECTA isolette
exemplar, SysMLv2 frontend) with a remote-attestation framework. The
HAMR attestation report (`sysml_attestation_report.json`) is the
*authority* our measurement protocols are derived from: each GUMBO
contract clause's generated-Rust realization is recorded as a `Slice`
with a source position, and our appraiser re-reads those byte ranges
and compares them against signed golden baselines. So the report's
slice set defines exactly which generated contract bytes are under
integrity measurement.

## The gap

For the developer-owned component app files (e.g.
`thermostat_rt_mhs_mhs_app.rs`), the report emits Verus-realization
slices for some GUMBO clause categories but **not for the
`compute_cases` realizations**. Concretely, in the mhs component the
report emits slices tagged:

- "Verus realization of GUMBO **initializes** contract"
- "Verus realization of GUMBO **general assumes** contract"
- "Verus realization of GUMBO **general guarantees** contract"

…but the `compute_cases` clauses — REQ_MHS_1 through REQ_MHS_5, each a
requirement-shaped `assume`/`guarantee` case — are realized as
implication clauses in the generated `ensures` block (roughly lines
64–99 of the `TIME TRIGGERED ENSURES` marker region) and carry **no
slice at all**. Across the seven contract-bearing component files of
this exemplar that is on the order of ~400 generated contract lines
(the bulk of the ensures blocks) with no report slice.

This is the most consequential category to leave uncovered, because the
`compute_cases` clauses are exactly the ones that trace one-to-one to
the certification requirements (the AR-08-32 REQ_MHS table) — the
clauses an adversary has the most reason to weaken.

## Why it matters for measurement

The model side of each case is protected — the SysML model file is
whole-file signed — but the *generated realization* in the developer-
owned `app.rs` is not, if the report does not slice it. A tamper that
(a) weakens a generated `compute_cases` ensures clause and (b) inverts
the implementation to match is **self-consistent under Verus**
(cargo-verus reports success), and lands entirely in the un-sliced
region — so a measurement framework that trusts the report's slice set
sees nothing. "Verification succeeded" cannot distinguish it, because
the weakened contract is genuinely satisfied by the inverted code.

We closed this on our side with a defense-in-depth byte tier (a marker-
block hash over the whole codegen-managed contract region, plus a
provisioning lint that refuses if any report contract slice falls
outside a marker block). But the clean fix is upstream: the report
should emit a realization slice for every `compute_cases` clause, the
same way it does for the initialize and general clauses.

## Request

- Emit Verus/Rust realization `Slice` entries for `compute_cases`
  clauses (one per case, or one spanning the case block), tagged
  consistently with the existing "Verus realization of GUMBO …
  contract" slices.
- If there is a deliberate reason these are omitted (e.g. the case
  realizations are considered covered elsewhere), we'd value knowing
  it — our lint currently treats the uncovered marker-region bytes as
  an integrity gap to backstop.

Happy to share the exemplar, the exact report, and a minimal
reproduction of the self-consistent tamper if useful.
