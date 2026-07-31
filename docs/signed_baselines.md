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

## Executable provenance: the build event (C6)

The built executable is a measured artifact whose golden is **born linked
to the evidence of its production** (`pybb/attestation/build.py`). A build
protocol makes the build itself an attested event — one term, one
signature:

    lean_build = lseq( lseq( lseq( lseq( bseq(hashfile: lean toolchain ×6),
                                         bseq(hashfile: input sources ×6) ),
                                   run_command_lean(lake build) ),
                             bseq(hashfile: output binary) ),
                       SIG )

Run at PROVISIONING only (building is a blessing-time act; episodes never
rebuild). The bundle is the build-provenance record: the evidence order
witnesses "this toolchain existed, these inputs existed, then the build
ran, then this output existed". The exec tier's binary golden is
extracted from this bundle (install_build_outputs) — a fragment of signed
build evidence at birth.

**Cross-link verification** (build-mode in verify_bundle, selected by the
events' provenance roles `tool::` / `build_in::` / `build_out::`): each
build-bundle event is anchored against ANOTHER protocol's golden — inputs
against the source baseline (lean_l1a, itself blessed via props), tools
against the blessed toolchain goldens, the output against the runtime
protocol that enforces it. Failures are precise: an input outside the
measured set, an unenforced output, anchor protocols disagreeing on a
golden, or a stale build (sources re-blessed after the build — its input
evidence no longer matches the baseline). The audit statement this
licenses: *the binary the exec tier runs is byte-identical to the output
of a signed build event whose inputs were the blessed sources and whose
builder was the blessed toolchain.*

**Hash-then-run**: lean_exec hashes the PINNED artifact against its
build-anchored golden in the same term that then executes it directly
(`lake env <binary>` — no rebuild). A swapped binary fails at the binary
target regardless of what the replacement prints. Consequence worth
stating: an implementation edit without a rebuild is refuted by the
proofs while the exec tier correctly reports the pinned binary intact —
the deployed artifact IS still the blessed one; and laundering that
re-runs the build produces a binary refuted by the AM-owned expected
vectors. Evidence-only gating (recorded decision): the hash event
precedes execution and appraisal refuses trust afterward, but a drifted
binary is not blocked from executing during the episode.

Isolette: the seL4/Microkit image build requires the Microkit SDK (not on
this host); the machinery is example-agnostic and the image build event is
the designed follow-up when an SDK lands.

## The verified appraisal summary: episode interpretation with a theorem

Episode responses are interpreted by copland-spec's formally verified
`do_appraisal_summary` (via the CakeML-extracted copland-evidence-tools
binary), not by Python evidence-walking. The summary re-partitions the
flat RawEv into one entry per appraisal event — `(measurement ASP,
appraiser, EvidenceT, RawEv slice)` — under a machine-checked correctness
theorem: every input slot is accounted for (Permutation — the fail-open
dropped-verdict hazard is eliminated by proof) and every entry's
appraiser is the session-declared ASP_Comps companion of its measurement
(provenance). Typing and slot-size preconditions fail closed inside the
tool.

pybb's role is per-entry LOCAL interpretation only: decode the verdict
slot, read the target id from the stored EvidenceT's `asp_targid` (every
target's args carry their own id, derivation-time injected and
drift-guarded at load — attribution is a field read), and lift the
retained measured output of EXTEND-forwarded appraisers
(ComponentResult.measured_b64 — the per-contract join material). Both
episode attestation and baseline verification interpret this way; the
legacy Python walker remains only for hosts without the tool, and unit
tests with fabricated responses pin it explicitly (the summarizer rightly
refuses non-evidence).

Transport note: real evidence exceeds the CakeML runtime's ~64KB argv
buffer; the tool gained a `--req_file` mode (workspace patch, upstream
candidate).

**Episode archives**: with `archive_dir` set on the attestation
predicate, every raw response is archived gzipped under a timestamped
episode directory, before interpretation and regardless of verdict;
`Verdict.evidence_ref` names the artifact, and re-summarizing an archived
response reproduces its verdicts (audit replay, tested).

**Evidence size (measured)**: raw evidence bytes are tiny (<1KB); 95-99%
of a response is the evidence-TYPE tree, which grows O(events²) because
every appraiser — REPLACE and EXTEND alike — embeds a full provenance
copy of the pre-appraisal tree (lean_l2, plain REPLACE, is the largest
measured response at 177KB/257 nodes for 15 events). EXTEND's marginal
cost is small (per-branch retained incoming evidence + the measured
outputs themselves). The trees are highly self-similar: gzip compresses
25-57x, so archives are ~1-2KB per response. The principled fix for the
quadratic term is upstream (DAG-sharing of evidence-type subtrees in the
CVM's serialization); until then, wide protocols (hundreds of targets)
should be split.

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
