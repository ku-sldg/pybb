# Signed golden baselines: integrity of the golden spec

The goldens an attestation episode compares against are themselves
artifacts on disk — `golden_b64` values in `asp_args.json`, bytes under
`golden/`. Before this work they were protected only by policy (the
provision partition's single-writer rule). Now they are protected by
evidence: every provisioning run produces a **signed Copland evidence
bundle**, every episode **verifies** the bundles before attesting, and the
contract artifacts themselves are **blessed at file granularity by an
administrator signature** that the per-slice goldens must be derivable
from.

## Lifecycle: when things are measured, signed, provisioned, verified

```
DERIVE      report / syntax scan -> target definitions (asp_args, term).
            No measurement, no goldens.

CAPTURE     TargetSnapshot.capture: live files -> golden/ mirror.
            The deliberate out-of-band trust decision; nothing else
            writes golden/.

PROVISION   one CVM run per protocol, against the golden COPIES:
            the attestation term with APPR stripped and SIG KEPT.
              isl_l1a:   hashfile x13        -> SIG over the hashes
              isl_l2:    readfile_range x67  -> SIG over the slice bytes
              isl_props: readfile x5 (whole model files, raw bytes)
                                             -> SIG over the file contents
            Each run's signed evidence package is stored as
            golden/_bundles/<pid>/provision_bundle.json, and each
            target's golden_b64 is EXTRACTED FROM THE BUNDLE — an
            installed golden is, at birth, a fragment of signed evidence.

VERIFY      every episode's readiness gate (and examples/verify_baseline.py):
            an APPRAISAL-ONLY CVM run per bundle — TERM = APPR, EVIDENCE =
            the stored bundle, session ASP_Comps dispatching companions:
              sig_appr            bundle signature over the evidence bytes
              goldenbytes_appr    installed golden == signed evidence
                                  (l1a/l2 anchoring)
              model_slices_appr   installed hash + slice goldens DERIVABLE
                                  from blessed whole-file content (props)
            Failures escalate as a DISTINCT baseline-integrity category,
            before any attestation runs.

ATTEST      measurement ASPs against the LIVE tree (SIG + APPR in-run),
            appraised against the installed goldens — unchanged.
```

## The props design: whole files blessed, slices derived

A `<prefix>_props` protocol measures the **whole model file** (`readfile`,
raw bytes) — isolette: the 5 AADL packages the report's 40 GUMBO `Model`
slices live in; lean: `TempControl/Spec.lean`. Its provision bundle is the
administrator's blessing of the file **as a unit** (sanctioning happens per
artifact, not per clause).

Slices are then *views*: at verification, `model_slices_appr` receives the
blessed file bytes as evidence and the current measurement protocols'
goldens as args, and checks each is **extractable from blessed content** —
the file's `hashfile` golden by recomputing SHA-256, each `readfile_range`
slice golden by re-extracting with the measurement ASP's exact semantics
(1-based inclusive lines, terminators stripped, no separator). Slice
definitions are appraiser inputs checked against signed bytes, never
independently trusted labels; re-deriving positions (promotion, report
regeneration) cannot invalidate a blessing while content is unchanged.

A model slice's bytes are therefore under signature twice, independently:
directly in the l2 bundle (per-protocol measurement provenance), and
derivably from the props bundle (administrator sanction).

## What this refutes

The scenario the design exists for, proven as automated tests
(`test_laundered_measurement_baselines_refuted_by_blessing`,
`test_laundered_theorem_refuted_by_blessing`): tamper a contract in the
**golden tree** and re-provision the measurement protocols. Their bundles
re-sign; their baselines verify **self-consistently** — per-protocol
verification cannot object. The blessing, which was not re-provisioned,
refutes: *"file hash golden not derivable from blessed content"*, plus the
laundered slice, attributed to the file. A sanctioned restore +
re-provision returns every baseline to verified.

Also caught, at the earlier layers: a hand-edited `golden_b64`
(signature OK, anchor fails, target named); a flipped byte in a stored
bundle (signature fails); a target added since signing ("not covered by
the signed bundle — re-provisioning required" — the bundle must cover
exactly the current target map, so re-provisioning is the only way to
admit new targets).

## Auditing

```sh
python examples/verify_baseline.py
```

prints the verifying key fingerprint and, per protocol: bundle path,
goldens anchored, provisioning timestamp. All protocols with bundles are
loaded as anchor sources, so props bundles are audited with full
hash-and-slice anchoring. Exit 1 on any failure.

## Tool identity: measure-then-use

The verifier toolchains themselves are measured targets
(`pybb/attestation/tools.py` — the parameterizable registry of what
constitutes each tool's identity):

| Tool | Artifacts | Measured when |
|---|---|---|
| `lean` | 6: workspace wrapper → elan shim → pinned toolchain binaries → `libleanshared.dylib` (the pin is read from the package's `lean-toolchain`, itself hash-anchored) | woven into `lean_check` / `lean_exec` |
| `cargo-verus` | 4: wrapper + distro `cargo-verus`, `rust_verify`, `verus` | woven into `isl_verus` / `tcmk_verus` |
| `hamr` | 9: `sireum.jar` + the 8 `org.sireum` OSATE plugins | promotion gate, immediately before codegen |

**Weaving** (`weave_tool_measurements`): the tool's artifacts are hashed
in the SAME term as the tool invocation, sequenced before the use —
`lseq( lseq( lseq( bseq(hashfile×N), body ), SIG ), APPR )` — so the
evidence order witnesses "the tool was in this state immediately before
it ran". A verdict produced by an unsanctioned tool fails attestation
attributed to the `tool::` target, regardless of the tool's output
(demonstrated: a byte appended to the lake wrapper fails both Lean tiers).

**Provisioning** is measure-in-place: tool artifacts are hashed live at
blessing time (no golden copies — toolchains are not golden-restorable
and 128M jars do not belong in the repository); the installed hash
goldens are protected by the bundle signature like every other golden.

**The promotion gate** (`make_tool_gate` + `make_promotion_predicate`'s
`tool_gate`): the HAMR toolchain is re-measured against its blessed
hashes immediately before `codegen_fn` runs, and promotion is refused on
drift — every attestation-report emission is bound to a measured emitter.
This is the A2′ upgrade of the audit argument: "the translation performed
by THE MEASURED TOOL is faithful", falsifiable by substitution.

**Cadence** is the optimization parameter (`TOOL_CADENCE` in the
drivers): `per_use` (default; ~123 ms lean / ~21 ms verus per woven term
with the asm-accelerated hashfile — in vivo, +0.41 s on a 1.13 s
validated Lean episode, of which ~150 ms is readiness verifying the
tiers' new bundles), `per_episode` (a standalone tools entry), or
`provision_only` (blessed hashes, no live re-measurement).

**Deliberately out of scope** (recorded decision): the attestation stack
itself (cvm binary, ASP executables). Self-measurement is drift
detection, not a root of trust; a system mechanism (e.g. TPM-backed boot
attestation) is the right tool for that layer, and the registry accepts
it later without redesign.

## Recorded limitations

- **Key custody is the real trust root.** The signing keypair is the demo
  `unsecure_*_dont_use` pair compiled into the sig/sig_appr binaries; the
  separation between "tooling re-provisions measurements" and
  "administrator re-blesses the spec" is procedural today (props is
  excluded from re-provisioning flows), not cryptographic. A distinct
  blessing key held apart from the attestation host is the follow-up; the
  architecture is shaped for it (props is a separate protocol with a
  separate bundle).
- The RSA signature covers the concatenated evidence **bytes**; the
  evidence tree's target labels remain unsigned metadata (a CVM-side
  fix). For the model files this is now mitigated: props reduces the
  spec's trust to one signed blob per file with no per-slice labels to
  swap.
- The CVM splices appraisal reasons into response JSON unescaped
  (fix in progress on the CVM side); appraisers emit sanitized
  single-line reasons meanwhile.
