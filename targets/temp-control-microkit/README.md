# temp-control-microkit

The temp-control tutorial model ported to the **seL4 Microkit / Rust /
Verus** HAMR pipeline, plus its generated output — including the
**attestation report**, which is the authoritative source of this
example's measurement targets and golden slices
(`hamr/microkit/attestation/aadl_attestation_report.json`).

Same GUMBO contracts as the JVM variant; the port required (each a
general lesson for models headed to this pipeline):

- `HAMR::Microkit_Language => Rust;` per thread — Rust is opt-in, the
  default is C, and only rusty+GUMBO components appear in the report
- a bound processor (`TC_Processor`, Frame/Clock periods) and
  process-per-thread structure with `CASE_Scheduling::Domain` per process
- uniform port categories (Fan: event data -> data, Sporadic -> Periodic)
- **integer contracts**: Verus has no floating point, so `degrees` is
  `Base_Types::Integer_32` and GUMBO literals use `s32"N"` syntax
  (this is why isolette is integer-first)

Layout: `aadl/` (the ported model, with OSATE `.project`/`.system` for
phantom) and `hamr/microkit/` (generated: Rust crates incl. Verus
contract realizations and `*_GUMBOX.rs` oracles, the microkit system
description, and the attestation report).

Regenerate with the standalone Sireum toolchain (see
`examples/microkit_attestation.py --promote`):

    sireum hamr phantom -f air.json aadl
    sireum hamr codegen -p Microkit --workspace-root-dir aadl \
        --output-dir hamr air.json

Semantic tier: `tcmk_verus` (cargo-verus verify of both crates; the
behavior bodies are implemented and fully prove — 10 verified, 0 errors
each). The model carries a `validSetPoint` compute assume standing in for
the SetPoint data invariant, which Microkit codegen does not yet realize.

Known coverage boundaries (documented findings): the report covers only
rusty+GUMBO components' contract slices — data invariants and the
microkit platform layer (`microkit.system`, generated C queues,
non-contracted crates, GUMBOX.rs test oracles) are not in the report and
not yet measured.
