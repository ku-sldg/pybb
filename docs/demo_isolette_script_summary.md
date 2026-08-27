# `examples/demo_isolette.sh` — what it exercises

An interactive walkthrough of the attestation workflow on the SysMLv2 ->
Rust isolette (the INSPECTA seL4/Microkit exemplar,
`targets/isolette-microkit`), driven end-to-end through
`isolette_rust.py --frontend sysml`. The scene outline mirrors
[demo_rocq_script_summary.md](demo_rocq_script_summary.md) on the Rocq
example; where the ecosystems differ, the scene says so and shows the
isolette's honest counterpart.

**At a glance**: fourteen scenes; repair species exercised: whole-file
restore, content-aligned slice splice, crate restore, marker-block
contract restore (scene 14), sanctioned codegen catch-up,
regeneration-from-model (the report in scene 8, the generated sources
in scene 12), out-of-band pause, freshness restoration (scene 11's
content-keyed dep guard), and the principled refusal; three refusal
properties at one gate (signature, anchor, derivability); two coverage
invariants — every verification-surface `.rs` byte-anchored (l1a,
gensrc, or sysproof) AND every contract-block byte of a
contract-bearing file covered by the l1b marker tier with every report
slice inside a marker block (the marker-coverage lint, both checked at
provisioning). Keyless throughout — every repair is deterministic or
out-of-band.

**Running it**: `./examples/demo_isolette.sh` (interactive; `--help`
for flags — `--scenes`, `--drift`, `--auto`, `--repair-strategy`,
`--fast` for unattended, `--restore-tools` recovery). Fresh machine:
`scripts/install.sh` builds the stack and provisions the baselines —
see [INSTALL.md](INSTALL.md). Warm cargo-verus caches recommended:
every Verus tier run genuinely re-verifies its 8 primary crates
(cargo-verus never serves a cached verdict for the crate under
verification — ~0.7 s each warm); what the cache holds is the
*dependencies* (vstd, build-std, the foundation crates), which is why
a cold start is multi-minute and — because dep freshness is
mtime-gated — why scene 11 exists. Scene 3's codegen beats add
~1-2 min each.

## Setup

- Bootstrap provisioning if no blessed baseline exists. Provisioning
  is gated by the **byte-coverage completeness invariant**: every `.rs`
  file of the verification surface must be covered by exactly one byte
  tier (l1a, gensrc, or sysproof), with the developer-owned exclusions
  explicit and the non-covered crates named as the postponed executable
  class — a codegen version that emits a new uncovered file refuses
  loudly instead of silently reopening the scene 9/11 coverage hole.
- The readiness gate: protocol configuration checks plus verification
  of every **signed golden baseline** (l1a hashes, l2 slices, the
  blessed props model files, the verus tool hashes, the cheat tier's
  proof-escape counts, the gensrc and sysproof hash maps) before any
  attestation runs.

## Scene 1 — clean baseline

- One attestation episode over every artifact class: **files** (13
  whole-file hashes: SysML packages + contract-bearing Rust),
  **contracts** (67 report slices), **verification** (cargo-verus over
  8 crates — the 7 component crates + the system proof crate — an
  ALWAYS-RUN entry judging CORRECTNESS, errors==0, so a
  blessed-but-unmet spec attests RED honestly), the **cheat tier**
  (per-crate proof-escape counts
  over 10 crates — see scene 9), the **sysproof tier** (whole-file
  hashes of the system proof crate, batched into one
  relpath→sha256 evidence map — see scene 10), the **gensrc tier**
  (whole-file hashes of the generated do-not-edit sources of the
  verification surface — bridge, GUMBOX, FFI glue, foundation dep
  crates — one batched map per crate, l1a-owned files excluded so
  developer-owned code keeps its slice-rescue semantics — see scenes
  9, 11, 12), and the **report rendering** every protocol is derived
  from, with the verus toolchain hashed measure-then-use in the same
  term.
- The per-crate proof checklist, all green.

## Scene 2 — implementation tamper: the ladder repairs the right artifact

- A **pre-generated dummy bad implementation** replaces the
  developer-owned compute logic wholesale ([diff&nbsp;D1](#d1); heat
  ON in INIT and FAILED modes, both NORMAL responses inverted): it
  compiles fine, but the blessed contracts are genuinely **false** of
  it, so no contract-side repair can help.
- The ladder diagnoses before it repairs: the contracts-intact rung
  finds every contract slice of the failing crate byte-identical to
  golden — the exhaustion *is the diagnosis* that the implementation is
  the artifact at fault — and hands off to the impl rung, which
  restores the implementation (crate-scoped, from golden, standing in
  for a future spec-guided Rust engine). The restarted episode
  re-attests; the model and contract slices end untouched.

## Scene 3 — spec drift: escalate, examine, rule

- A GUMBO contract edit (operator's choice of three flavors):
  **benign** — semantically equivalent restatement in `Regulate.sysml`
  ([diff&nbsp;D2](#d2)); **breaking** — REQ_MHS_1's initialize
  guarantee flipped Off -> Onn ([diff&nbsp;D3](#d3)), which codegen
  accepts but the implementation cannot honor; or **range**
  (`--drift range`) — the Table A-12 upper-alarm ceiling widened
  102 -> 103 in the shared `GUMBO_Library.sysml` constant, so the
  operator interface's guarantee and the monitor's assumes move
  *together* and a bless survives the catch-up: promote regenerates
  the shared-library realization and the episode re-proves clean.
  Even this benign-by-construction change fails model appraisal until
  ruled on — the appraiser judges *sanction, not semantics*.
- Detection and escalation with attribution: the l2 refinement names
  the changed slices; interactive ruling over the diff — **revert**, or
  **bless**: spec-first sanctioning (`--provision --bless-props`
  re-signs the props class only; no codegen).
- After a bless, model and contracts attest clean while the generated
  realization still renders the OLD statements. The catch-up is the
  **sanctioned pipeline** (`--promote`): tool gate (HAMR + pinned
  sysml-aadl-libraries hashed just before use) -> **real SysML
  codegen** (re-splices the contract marker regions inside the
  developer-owned app.rs) -> gold moves -> props re-blessed.
  **Promotion never verifies**: blessing is an authority act, and
  whether the implementation proves against the blessed spec is the
  following episode's honest measurement.
  - **Benign**: the regenerated contracts prove, the episode confirms
    clean (Verus green), with the codegen re-splice shown as a diff
    ([diff&nbsp;D4](#d4)).
  - **Breaking**: gold **moves** (no verification gate); the episode
    against the new baseline reports the **Verus tier RED** — both the
    `mhs` crate and the `sys_nominal_proof` system proof that composes
    it cannot honor the flipped REQ_MHS_1. This is the honest state:
    a spec blessed that the implementation does not yet meet. The exits
    are an implementation fix (scene 2's ladder) or walking the
    sanction back (restore the tree, re-bless the original spec).

## Scene 4 — restore, at two grains

- **Whole-file** (`--immutable-model`): the ruling for automated
  pipelines — measured files never drift ([diff&nbsp;D5](#d5)); the
  failed l1a hash appraisal IS the repair order, restore + re-attest
  **in-session**, no interaction, no l2 examination.
- **Slice** (`--repair-granularity slice`): the repair unit is the
  measurement unit ([diff&nbsp;D6](#d6)) — only the violated contract
  slice is spliced back, located by **content alignment** (difflib
  against golden; insertion-robust), benign drift elsewhere in the
  same file survives,
  and the files entry ends attested clean *via the l2 contracts
  refinement* — the terminal proof the note survived re-measurement.

## Scene 5 — verification failure, repair by selectable strategy

- The implementation drifts in its **developer-owned region** — the
  INSPECTA exemplar's own seeded bug (REQ-MHS-2 response inverted,
  [diff&nbsp;D7](#d7)). Every contract slice is intact, so integrity
  attests clean at finer
  granularity; the always-run verus tier refutes the crate: the
  generated contracts are genuinely **false** of the drifted behavior.
- Strategy chosen at the prompt or `--repair-strategy`: **restore**
  (the failing crate's hashed files from golden — crate-scoped, judged
  by fresh measurement in-session) or **pause** (out-of-band: the
  episode blocks on a work order, *you* repair in another terminal, and
  only fresh measurement — never your claim — re-establishes standing).
- Rocq's tactic-portfolio / LLM strategies have no honest counterpart
  here: Verus contracts are generated artifacts, so "repairing" them
  would launder the spec, and repairing the *implementation* was
  scene 2's ladder.

## Scene 6 — baseline tamper: the repair that must refuse

- Three beats, one gate, three attributed refusals: a **flipped byte of
  signed bundle evidence** ([diff&nbsp;D8](#d8); record integrity — the
  signature refutes), a **hand-edited installed golden**
  ([diff&nbsp;D9](#d9); installation consistency — the anchor refutes,
  signature silent), and **laundering** — a tampered spec
  ([diff&nbsp;D5](#d5) again) re-provisioned into fully
  self-consistent measurement baselines,
  refuted by semantic lineage: every hash and slice golden must be
  *derivable from the blessed signed bytes*, and ordinary provisioning
  cannot refresh the props blessing.
- Each stops attestation before it starts — the ready entry's failure
  chain is empty by design, so the only exit is the administrator's
  out-of-band re-bless.

## Scene 7 — toolchain tamper: measure-then-use catches the tool

- A **functionality-preserving** edit to the cargo-verus wrapper
  ([diff&nbsp;D10](#d10)): every verification still runs and looks fine,
  but the tool hash — taken in
  the same term, before use — refutes, and every proof cell poisons to
  `?` fail-closed. Readiness still passes: the stored record is
  coherent; the *live* tool drifted.
- Hash-only artifacts are unrepairable from goldens by design: the
  repair is the out-of-band pause rung — you restore the wrapper, fresh
  measurement re-establishes standing. (`--restore-tools` is the
  recovery hatch: reinstall the canonical wrapper, prove it against the
  blessed golden, confirm readiness.)

## Scene 8 — report tamper: the rendering anchored and regenerated

- The attestation report is the **authority** every protocol dir is
  derived from — measurement targets bind to contracts only through its
  structure — so the report itself is hashed measure-then-use as its
  own always-run entry. Beat 1: a **deleted slice**
  ([diff&nbsp;D11](#d11); a re-derived protocol would measure one
  target fewer than the blessing intended). Beat 2: a slice span
  **substituted** for a different contract's ([diff&nbsp;D12](#d12)) —
  counts stay right, structure stays plausible; only the byte anchor
  refutes.
- The repair is the regeneration species — neither restore nor
  synthesis: the report is a **rendering of the model through the
  measured codegen toolchain**, so the rung re-emits it (tool gate
  first, then real codegen) and the restarted episode re-attests.

## Scene 9 — proof cheat: verification success is not proof

Two beats, two proof escapes that pass every OUTCOME-based tier because
they change no proof outcome. Each beat opens with a **two-grid view**
(`--status --cheat-status`): the verus grid shows cargo-verus passing
every crate (the escape changes no outcome), while the proof-escape
grid refuses the exact crate and **names the drifted construct**
(`assume 0 → 1` for the admit, `broadcast 0 → 1, external_body 0 → 1`
for the smuggle) — the ✗/✓ from the appraiser, the construct
annotation from re-scanning the crate against its golden count map. Both sites are byte-anchored by the
**gensrc tier** now, so two detectors refuse together — the byte anchor
says *something* changed, the cheat scan (counting escape
**constructs**) says *what kind* — and the gensrc ladder's diagnosis
rung correlates the two refusals into "a proof ESCAPE appeared". The
cheat scan is not made redundant by byte coverage: it alone guards the
**promote boundary**, where gold legitimately moves and byte-blessing
would bless whatever codegen emitted.

- **Beat 1 — ADMIT** ([diff&nbsp;D13](#d13)): `assume(false)` admits a
  verified contract inside a bridge file the report never names
  (`thermostat_rt_mhs_mhs_api.rs` — outside every l1a and l2 target).
  files/contracts green, and cargo-verus reports the **same success**
  over the hollow proof — the Verus tier (errors==0) is green (an admit
  changes no proof outcome). The cheat tier refuses:
  `cheat_scan_verus` re-counts the proof-escape surface (assume, admit,
  external_body by path class, bare external, assume_specification,
  axiom, broadcast, uninterp — the constructs Verus's own
  `--no-cheating` flag names, textually scanned), and the drift
  (assume 0 → 1) fails the exact-bytes golden, attributing the crate;
  the gensrc anchor refuses in the same episode, naming the file
  (`hash drift: src/bridge/thermostat_rt_mhs_mhs_api.rs`).
- **Beat 2 — SMUGGLE** ([diff&nbsp;D14](#d14)): an `external_body`
  `broadcast proof fn` with `ensures false` planted in the shared
  `GUMBO_Library` foundation crate. It verifies clean on its own (the
  body is trusted) and is **inert until a `broadcast use`** pulls it
  in, so it changes no proof outcome: files, contracts, the **Verus
  tier** (errors==0), the sysproof hash, and the report all stay green.
  The cheat scan catches it at the staging point before any proof
  consumes it, naming `GUMBO_Library` (broadcast 0 → 1,
  external_body.other 0 → 1), and the gensrc anchor names the file —
  the construct scan remains the robust *semantic* detector: it sees
  the escape even when every outcome is clean, and it would still see
  one that arrived through sanctioned regeneration, where the hashes
  move with gold.
- No repair rung **on purpose** (either beat): a proof escape is never
  machine-repairable — the refusal escalates to the administrator, and
  the driver restores the tamper site from a pre-episode snapshot (the
  cheat sites have no golden mirror, deliberately).
- The honest baseline the golden blesses: 86 `external_body` sites,
  all in generated bridge/component platform-boundary files; zero
  assume/admit/axiom/broadcast anywhere. The scan covers the seven
  component crates, the system proof crate, and the shared foundation
  crates (`data`, `GUMBO_Library`), where the only blessed escape is
  26 `uninterp` action fns in `sys_nominal_proof/actions.rs`.

## Scene 10 — the hollow system proof: verification vs bytes

- `sys_nominal_proof` is the **system-level compositional proof**
  (~1862 obligations, one empty-bodied VC each, discharged by Verus).
  Two attacks that add **no escape construct** (cheat scan silent) AND
  change **no verification outcome** (the Verus tier judges
  correctness — does it verify? — not surface size) — a demonstration
  that "verification succeeded" is not enough, and neither is "no
  cheats present." Only the bytes tell.
- **Beat 1 — SHRINK** ([diff&nbsp;D15](#d15)): comment out a proof
  module. The smaller crate **still verifies** (0 errors), so the
  Verus tier stays green — the shrink carries no verification signal.
  Only the whole-file **sysproof hash** refuses (lib.rs changed),
  naming the file ("hash drift: src/lib.rs"). A cleaner demonstration
  of why the hash tier exists: correctness and surface-integrity are
  different questions.
- **Beat 2 — SWAP** ([diff&nbsp;D16](#d16)): drop a real VC and add a
  trivial `ensures true` one. The crate still verifies and the cheat
  scan stays silent (no escape construct) — **only** the whole-file
  **sysproof hash** refuses, naming the swapped file ("hash drift:
  src/normal_display_temp/vc_sequential.rs" — the batched appraiser
  carries per-file attribution in its reason). Bytes anchor what a
  proof outcome cannot. The sysproof crate is do-not-edit generated, so
  whole-file hashing with no benign-drift allowance is correct; no
  repair rung — the refusal escalates.

## Scene 11 — the stale dependency cache: a verdict that never looked

- The premise, measured on the pinned toolchain: the Verus tier's 8
  **primary** crates genuinely re-verify every run (cargo-verus never
  serves a cached verdict for the crate under verification), but the
  foundation crates (`data`, `GUMBO_Library`) are consumed as **cargo
  dependencies**, and cargo's dep freshness is **mtime-gated** — a
  content change with the mtime preserved nanosecond-exact is served
  stale.
- **Beat 0** — the coherent warm cache the attack needs: one
  gated-clean checklist run, then the guard's freshness record is
  seeded over that known-coherent state (trust-on-first-use).
- **Beat 1 — the horror: the tiers disagree** ([diff&nbsp;D17](#d17)):
  a spec predicate in `GUMBO_Library` flipped *semantically*
  (`isValidTempWstatus_spec` `==` -> `!=`; no construct-count change),
  mtime preserved. The cheat scan counts no new escape, the sysproof
  bytes are untouched — and the verus tier stays green because every
  re-verified primary consumes the stale cached artifact. The **gensrc
  byte anchor refuses** (bytes always tell), which is what exposes the
  Verus verdict: the byte tier says the foundation changed while the
  Verus tier sits green over a system proof that is **false of the
  live bytes** — "verification succeeded" is a verdict about bytes the
  verifier last *looked* at. A refusing byte tier keeps the *system*
  honest; the green Verus cell is still misleading *evidence*, which
  is what beat 2 repairs. The stale-green gate doubles as a regression
  canary for the toolchain's cache behavior.
- **Beat 2 — the guard**: `--fresh-deps` re-keys dep freshness on
  **content** — digest the foundation crates' sources against the
  seeded sidecar, attribute the drift (`content drift in
  GUMBO_Library`), bump mtimes so cargo-verus must re-verify the
  dependency from the live bytes. The forced-fresh episode reports the
  **Verus tier RED**: `sys_nominal_proof` consumes the predicate
  load-bearingly and 8 of its VCs refute — the verdicts agree again.
  Stated honestly: attribution names the *consumer*, not the tampered
  dependency — the guard restores freshness, it does not attribute.
- No repair rung on purpose: a poisoned foundation escalates. The
  driver's restore is **mtime-aware both ways**: after beat 1 (no
  rebuild happened — the caches still hold pre-tamper artifacts) it
  restores bytes *and* mtime, leaving every warm cache coherent for
  free; after beat 2 it restores bytes with a **fresh** mtime, because
  the guard's forced rebuilds consumed the tampered bytes and an
  mtime-gated cache must be *told* the restore happened — restoring
  the old mtime would leave the poisoned artifacts being served over a
  clean tree (the closing gated checklist exists to catch exactly
  that, and did during development). It proves the tree green from
  live re-verification.
- The guard is **demo-scoped by choice**: outside this scene the verus
  tier's *evidence* trusts cargo's dep cache — the gensrc byte anchor
  keeps the system honest, but honest evidence needs the guard. The
  sidecar is cache state, not trust state — it lives outside `golden/`
  and is deleted at scene end and on script exit. The always-on
  **attested** guard (a measured ASP with a blessed record) is
  postponed by design.

## Scene 12 — the unverified foundation: bytes under the proof tower

- **Beat 1 — invert the command under the proofs**
  ([diff&nbsp;D18](#d18)): every verified put flows through
  `unsafe_put_heat_control` — plain unverified Rust behind an
  `external_body` boundary Verus never reads. The tamper inverts the
  heat command right there: **every proof passes** (they are about the
  ghost model; the body was always trusted), the **cheat scan counts
  no new escape** (the escape surface is unchanged — `external_body`
  was already blessed), and no report-named file moved. Only the
  **gensrc byte anchor** refuses, naming the file (`hash drift:
  src/bridge/extern_c_api.rs`), and the ladder's diagnosis rung
  classifies the drift: *bytes drifted with cheat counts CLEAN — a
  semantic edit no construct scan can see*. This drift kind is the
  reason the gensrc ladder **never rescues** on a clean cheat scan: in
  a do-not-edit generated file, every byte is measured semantics.
- **Beat 2 — repair by regeneration**: the gensrc files are, like the
  report, *renderings of the model through the codegen toolchain*, so
  the repair is scene 8's species, not restore-from-golden: tool gate
  (HAMR + pinned libraries hashed immediately before use) -> real
  SysML codegen re-emits the generated sources from the blessed model
  -> `RestartEpisode` -> the fresh measurement judges the regenerated
  bytes (`repaired and re-attested clean in-session`). Standing comes
  from measurement, never from the repair's claim.
- The ladder in full, contrasted with l1→l2: the files entry's ladder
  can end **attested clean at finer granularity** because
  developer-owned files have unmeasured regions; the gensrc ladder
  ends only in *diagnosed*, *regenerated-and-remeasured*, or
  *escalated* — pass-via-refinement is unsound where there is no
  benign region for drift to hide in.

## Scene 13 — implementation drift: benign, re-verified

- A **semantically equivalent** rewrite of the developer-owned
  NORMAL-mode guard (`currentTemp.degrees > upper.degrees` →
  `upper.degrees < currentTemp.degrees`), landing **outside every
  contract marker block**. Every l2 contract slice and every l1b
  marker block stays byte-identical; only the whole-file l1a hash
  moves.
- The files entry passes **via the l2 refinement at finer
  granularity**, the marker-block `contracts` entry stays clean, and
  the confirmation chain **re-verifies the rewritten implementation**:
  the benign change *survives*, no restore. The mirror of scene 3's
  benign spec restatement, one artifact class down — integrity is
  about blessed bytes, but a developer-owned region has no blessed
  bytes to match; its attested properties are the contracts (intact)
  and provability (re-verified live).

## Scene 14 — contract drift: breaking, restored

- The **model is untouched**. In the developer-owned `app.rs`, the
  generated **REQ_MHS_2 ensures is weakened** (admit both heat-control
  states) *and* the implementation is inverted to the very behavior
  the weakening covers for. Run alone, cargo-verus **succeeds** — the
  pair is self-consistent — yet the contract has drifted from what the
  blessed model renders. "Verification succeeded" cannot see this.
- The detector is the **l1b marker tier** (a new Copland protocol:
  `readfile_marker_range` over every codegen-managed `BEGIN/END
  MARKER` contract block, appraised against a signed golden). It
  exists because the attestation report emits Verus-realization slices
  for the *initialize* and *general* GUMBO clauses but **none for the
  `compute_cases` realizations** — so the weakened REQ_MHS_2, an
  implication clause at ensures lines ~70–76, lands *between* the
  report's l2 slices. The marker tier measures every contract-block
  byte regardless, refuses, and its repair rung **splices the golden
  contract block back** (located by marker anchor; developer regions
  untouched).
- The scene ends on the **honest exposure**: the restored true
  contract now **refutes the still-inverted implementation** — the
  Verus refusal the laundering was hiding
  (`thermostat_rt_mhs_mhs_verus_targ` [Appraisal was not successful]).
  Restoring the contract is what makes the hidden implementation bug
  *measurable*; the implementation repair itself is scene 2's ladder.
- **Discovered while building this demo** (2026-08-26): the
  contract-launder tamper slipped the report's slice coverage until
  the marker tier and its provision-time **marker-coverage lint**
  (every report contract slice must lie inside a marker block; every
  contract-bearing `.rs` must have marker coverage — ~400 marker lines
  per baseline carry no report slice) closed the hole. The report's
  missing `compute_cases` slices are an upstream HAMR
  report-emission gap; the l1b tier is pybb's defense-in-depth
  backstop.

## Throughout

- **Opt-in VSCode diffs** at every artifact-modification beat: the
  seeded behavior bug (scene 5), the wrapper edit (scene 7), the
  deleted and substituted report slices (scene 8, pretty-printed
  JSON, shown BEFORE the arc — "see how innocent the tamper looks"),
  the admitted contract and the smuggled foundation axiom (scene 9's
  two beats, same before-the-arc reveal), the mtime-preserving semantic
  flip (scene 11, previewed as a pure text transform so the live file's
  mtime is never disturbed), the inverted FFI command (scene 12, same
  pure-transform preview),
  the dummy-bad-impl inversion (scene 2), the codegen re-splice after
  a benign bless (scene 3), and scene 6's trust-state attacks — the
  flipped evidence byte and the hand-edited golden (both
  pretty-printed JSON), and the blessed-vs-laundered spec —
  `[v]iew diff / Enter to continue`, terminal fallback, skipped in
  unattended runs. Scene 3's ruling diff (golden vs proposed) is
  always shown. This document links the same diffs statically — see
  the [appendix](#appendix-artifact-diffs).
- Every scene gates on expected output (including no-✗/no-? checks on
  clean checklists), so regressions — or a dirty starting tree — abort
  loudly.
- Self-cleaning: tampered targets restore at every driver exit;
  bundles, goldens, wrapper, and any demo blessing are restored on
  script exit (scene 3's codegen catch-up requires a git-clean
  `targets/isolette-microkit` and restores through git).

Postponed by design: episode-triggering monitor, wall-clock repair
timeouts, the executable artifact class (`domain_monitor`,
`thermostat_mt_dmf_dmf`, `thermostat_rt_drf_drf` — named explicitly by
the gensrc coverage invariant, measured by no tier yet), blessing the
report under the props class (so a laundered report is refuted by
lineage, not just by the live hash), a real spec-guided Rust
implementation engine, the always-on attested dependency-freshness
guard (scene 11's guard as a measured ASP with a blessed record,
instead of a demo-scoped helper), and lineage anchoring for the
re-captured cheat and gensrc goldens across promote (today they
inherit trust from the measured toolchain that emitted the code they
describe).

## Appendix: artifact diffs

The same diffs the script offers interactively (`[v]iew diff … / Enter`), statically. Paths are relative to `targets/isolette-microkit/` (model + generated tree) or the pybb repo root (trust state).

<a id="d1"></a>
### D1 — scene 2: the pre-generated dummy bad implementation

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -114,28 +114,25 
 
           // ----- INIT Mode --------
           Regulator_Mode::Init_Regulator_Mode => {
-              // REQ-MHS-1
-              currentCmd = On_Off::Off;
+              // DUMMY BAD IMPL: heat left ON during initialization
+              currentCmd = On_Off::Onn;
           },
 
           // ------ NORMAL Mode -------
           Regulator_Mode::Normal_Regulator_Mode => {
               if (currentTemp.degrees > upper.degrees) {
-                  // REQ-MHS-3
+                  // DUMMY BAD IMPL: inverted response when too hot
+                  currentCmd = On_Off::Onn;
+              } else if (currentTemp.degrees < lower.degrees) {
+                  // DUMMY BAD IMPL: inverted response when too cold
                   currentCmd = On_Off::Off;
-              } else if (currentTemp.degrees < lower.degrees) {
-                  assert(api.current_tempWstatus.degrees < api.lower_desired_temp.degrees);
-                  // REQ-MHS-2
-                  //currentCmd = On_Off::Off; // seeded bug/error
-                  currentCmd = On_Off::Onn;
               }
-              // otherwise currentCmd defaults to lastCmd (REQ-MHS-4)
           },
 
           // ------ FAILED Mode -------
           Regulator_Mode::Failed_Regulator_Mode => {
-              // REQ-MHS-5
-              currentCmd = On_Off::Off;
+              // DUMMY BAD IMPL: heat left ON after failure
+              currentCmd = On_Off::Onn;
           }
       }
 
```

<a id="d2"></a>
### D2 — scene 3 (benign): the `lower_is_lower_temp` restatement

Semantically equivalent (`x <= y` -> `y >= x`), in both components carrying the guarantee; the regenerated contracts still prove.

```diff
--- a/sysml/Regulate.sysml
+++ b/sysml/Regulate.sysml
 -188,7 +188,7 
                 // general guarantee between outgoing port values
                 guarantee lower_is_lower_temp "Derived requirement, not in AR-08-32: MHS unconditionally assumes the
                                               |Desired Range is well-ordered,.":
-                    lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                    upper_desired_temp.degrees >= lower_desired_temp.degrees;
 
                 compute_cases
                     // ====== Regulator Status ======    
 -460,7 +460,7 
             //  ====== C o m p u t e    E n t r y    P o i n t   Behavior Constraints =====      
             compute
                 // assumption on set points enforced within the Operator Interface
-                assume lower_is_lower_temp: lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                assume lower_is_lower_temp: upper_desired_temp.degrees >= lower_desired_temp.degrees;
             
                 // the lastCmd state variable is always equal to the value of the heat_control output port
                 guarantee lastCmd "Set lastCmd to value of output Cmd port":
```

<a id="d3"></a>
### D3 — scene 3 (breaking): REQ_MHS_1's initialize guarantee flipped

Codegen accepts it and gold moves (promotion never verifies); the implementation initializes the heat control Off, so the episode against the new baseline reports the Verus tier RED.

```diff
--- a/sysml/Regulate.sysml
+++ b/sysml/Regulate.sysml
 -455,7 +455,7 
                 guarantee REQ_MHS_1 "If the Regulator Mode is INIT, the Heat Control shall be
                                     |set to Off.
                                     |https://www.faa.gov/sites/faa.gov/files/aircraft/air_cert/design_approvals/air_software/AR-08-32.pdf#page=110 ":
-                    heat_control == Isolette_Data_Model::On_Off.Off;
+                    heat_control == Isolette_Data_Model::On_Off.Onn;
             
             //  ====== C o m p u t e    E n t r y    P o i n t   Behavior Constraints =====      
             compute
```

<a id="d4"></a>
### D4 — scene 3 (benign, blessed): the codegen re-splice

What `--promote` wrote back into the developer-owned file's marker region — the realization catching up with the blessed restatement.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -54,7 +54,7 
       requires
         // BEGIN MARKER TIME TRIGGERED REQUIRES
         // assume lower_is_lower_temp
-        old(api).lower_desired_temp.degrees <= old(api).upper_desired_temp.degrees,
+        old(api).upper_desired_temp.degrees >= old(api).lower_desired_temp.degrees,
         // END MARKER TIME TRIGGERED REQUIRES
       ensures
         // BEGIN MARKER TIME TRIGGERED ENSURES
```

<a id="d5"></a>
### D5 — scene 4 beat 1: the model drift (also scene 6's laundered edit)

```diff
--- a/sysml/Regulate.sysml
+++ b/sysml/Regulate.sysml
 -188,7 +188,7 
                 // general guarantee between outgoing port values
                 guarantee lower_is_lower_temp "Derived requirement, not in AR-08-32: MHS unconditionally assumes the
                                               |Desired Range is well-ordered,.":
-                    lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                    lower_desired_temp.degrees < upper_desired_temp.degrees;
 
                 compute_cases
                     // ====== Regulator Status ======    
 -460,7 +460,7 
             //  ====== C o m p u t e    E n t r y    P o i n t   Behavior Constraints =====      
             compute
                 // assumption on set points enforced within the Operator Interface
-                assume lower_is_lower_temp: lower_desired_temp.degrees <= upper_desired_temp.degrees;
+                assume lower_is_lower_temp: lower_desired_temp.degrees < upper_desired_temp.degrees;
             
                 // the lastCmd state variable is always equal to the value of the heat_control output port
                 guarantee lastCmd "Set lastCmd to value of output Cmd port":
```

<a id="d6"></a>
### D6 — scene 4 beat 2: one corrupted slice + the benign note

Slice restore splices back ONLY the violated block; the note survives, and the files entry passes via the l2 refinement.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -11,7 +11,7 
 
   pub struct thermostat_rt_mhs_mhs {
     // BEGIN MARKER STATE VARS
-    pub lastCmd: Isolette_Data_Model::On_Off,
+// TAMPERED: verus contract weakened
     // END MARKER STATE VARS
   }
 
 -175,3 +175,5 
   }
 
 }
+
+// engineering note: candidate sensor swap under review
```

<a id="d7"></a>
### D7 — scene 5: the seeded behavior bug

The INSPECTA exemplar's own seeded bug: in NORMAL mode below the lower bound, command Off instead of On.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/component/thermostat_rt_mhs_mhs_app.rs
 -126,8 +126,8 
               } else if (currentTemp.degrees < lower.degrees) {
                   assert(api.current_tempWstatus.degrees < api.lower_desired_temp.degrees);
                   // REQ-MHS-2
-                  //currentCmd = On_Off::Off; // seeded bug/error
-                  currentCmd = On_Off::Onn;
+                  currentCmd = On_Off::Off; // seeded bug/error
+                  //currentCmd = On_Off::Onn;
               }
               // otherwise currentCmd defaults to lastCmd (REQ-MHS-4)
           },
```

<a id="d8"></a>
### D8 — scene 6 beat 1: one flipped byte of signed evidence

Pretty-printed and truncated; the change is a single character inside one RawEv slot of the props bundle.

```diff
--- a/golden/_bundles/isolette_sysmlv2_rust_props/provision_bundle.json
+++ b/golden/_bundles/isolette_sysmlv2_rust_props/provision_bundle.json
 -8,5 +8,5 
     "Ly8gTW9uaXRvci5zeXNtbApwYWNrYWdlIE1vbml0b3IgewogIAo…[truncated]…ogIH0KfQo=",
     "cGFja2FnZSBPcGVyYXRvcl9JbnRlcmZhY2UgewogIAogIHByaXZ…[truncated]…8KICB9Cn0K",
-    "Ly8gUmVndWxhdGUuc3lzbWwKCnBhY2thZ2UgUmVndWxhdGUgewo…[truncated]…CAgIH0KfQo="
+    "Ly8gUmVndWAhdGUuc3lzbWwKCnBhY2thZ2UgUmVndWxhdGUgewo…[truncated]…CAgIH0KfQo="
    ]
   },
```

<a id="d9"></a>
### D9 — scene 6 beat 2: one hand-edited installed golden

The bundle stays authentic; only the anchor to the signed evidence refutes.

```diff
--- a/tests/fixtures/isolette_sysmlv2_rust_props/asp_args.json
+++ b/tests/fixtures/isolette_sysmlv2_rust_props/asp_args.json
 -33,5 +33,5 
    "filepath": "/Users/adampetz/Claude_workspace/pybb/ta…[truncated]…late.sysml",
    "asp_targid": "isolette_sysmlv2_rust_props_regulate_targ",
-   "golden_b64": "Ly8gUmVndWxhdGUuc3lzbWwKCnBhY2thZ2UgUm…[truncated]…AgIH0KfQo=",
+   "golden_b64": "Ly8gUmVndWAhdGUuc3lzbWwKCnBhY2thZ2UgUm…[truncated]…AgIH0KfQo=",
    "golden_ts": "2026-08-17 09:04:12"
   }
```

<a id="d10"></a>
### D10 — scene 7: the functionality-preserving wrapper edit

```diff
--- a/~/Claude_workspace/bin/cargo-verus
+++ b/~/Claude_workspace/bin/cargo-verus
 -3,3 +3,4 
 # (CVM child processes see this via CvmConfig.path_prepend).
 export PATH="$HOME/Claude_workspace/verus-dist:$HOME/.cargo/bin:$PATH"
 exec "$HOME/Claude_workspace/verus-dist/cargo-verus" "$@"
+# drifted: innocuous-looking edit
```

<a id="d11"></a>
### D11 — scene 8 beat 1: the deleted report slice

Pretty-printed; one Verus slice quietly gone from the authority.

```diff
--- a/attestation/sysml_attestation_report.json
+++ b/attestation/sysml_attestation_report.json
 -36,19 +36,4 
         "length": 121
        }
-      },
-      {
-       "type": "Slice",
-       "kind": "Verus",
-       "meta": "Verus realization of GUMBO initializes contract",
-       "pos": {
-        "type": "Position",
-        "uri": "../crates/thermostat_rt_mri_mri/src/component/thermostat_rt_mri_mri_app.rs",
-        "beginLine": 25,
-        "beginCol": 11,
-        "endLine": 26,
-        "endCol": 72,
-        "offset": 567,
-        "length": 73
-       }
       }
      ]
```

<a id="d12"></a>
### D12 — scene 8 beat 2: the substituted slice span

Slice count unchanged; the slice now points at a different contract's lines in the same file.

```diff
--- a/attestation/sysml_attestation_report.json
+++ b/attestation/sysml_attestation_report.json
 -29,7 +29,7 
         "type": "Position",
         "uri": "../../../sysml/Regulate.sysml",
-        "beginLine": 176,
+        "beginLine": 182,
         "beginCol": 16,
-        "endLine": 177,
+        "endLine": 186,
         "endCol": 111,
         "offset": 9738,
```

<a id="d13"></a>
### D13 — scene 9: the admitted contract

One injected line: `put_heat_control`'s real `ensures` still stands in
the text, but the proof context now contains `false` — everything
downstream is vacuously provable, and cargo-verus reports the same
success.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/bridge/thermostat_rt_mhs_mhs_api.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/bridge/thermostat_rt_mhs_mhs_api.rs
 -85,6 +85,7 
         self.heat_control == value,
     {
+      assume(false); // TAMPERED: proof admitted
       self.api.unverified_put_heat_control(value);
       self.heat_control = value;
     }
```

<a id="d14"></a>
### D14 — scene 9 beat 2: the smuggled foundation axiom

An `external_body` `broadcast proof fn` with `ensures false`, planted in
the shared `GUMBO_Library`. The body is unchecked, so it verifies clean;
inert until a `broadcast use` pulls it in, so no verified count moves.
Only the construct scan sees it.

```diff
--- a/crates/GUMBO_Library/src/lib.rs
+++ b/crates/GUMBO_Library/src/lib.rs
 -172,6 +172,11 
     value.status == Isolette_Data_Model::ValueStatus::Valid
   }
+  // TAMPERED: smuggled proof-context poison (false, unchecked body)
+  #[verifier::external_body]
+  pub broadcast proof fn smuggled_axiom()
+    ensures false
+  {}
   // END MARKER GUMBO VERUS MARKER
```

<a id="d15"></a>
### D15 — scene 10 beat 1: the shrunken proof surface

One commented module: the crate still verifies (0 errors) but proves
fewer obligations, so the verified count drops below the golden 1862.

```diff
--- a/crates/sys_nominal_proof/src/lib.rs
+++ b/crates/sys_nominal_proof/src/lib.rs
 -49,1 +49,1 
-pub mod normal_display_temp;
+// pub mod normal_display_temp;  // COUNT TAMPER: module dropped
```

<a id="d16"></a>
### D16 — scene 10 beat 2: drop-and-replace at constant count

A real VC dropped, a trivial one added — the verified count stays 1862,
so the verus tier is blind; only the whole-file hash sees the change.

```diff
--- a/crates/sys_nominal_proof/src/normal_display_temp/vc_sequential.rs
+++ b/crates/sys_nominal_proof/src/normal_display_temp/vc_sequential.rs
 -19,7 +19,7 
 verus! {
+pub proof fn dropped_and_replaced() ensures true {}
 
-/** VC[1]: Pre-Assert -- before_oi |- OI compute assumes */
-pub proof fn vc_pre_assert_oi(st: SystemState)
-  requires
-    true /* before_oi has no assertion */,
-  ensures
-    true /* no assertions at out-places */,
-{}
-
 /** VC[2]: Next-Assert (task) ... */
 pub proof fn vc_next_assert_task_oi(pre: SystemState, post: SystemState)
```

<a id="d17"></a>
### D17 — scene 11: the mtime-preserving semantic flip

One flipped comparison in a shared foundation spec fn, written back with
the file's mtime restored nanosecond-exact. Freshly verified, 8
system-proof VCs refute it; served from the warm mtime-gated dep cache,
every tier stays green.

```diff
--- a/crates/GUMBO_Library/src/lib.rs
+++ b/crates/GUMBO_Library/src/lib.rs
 -167,7 +167,7 
 
   pub open spec fn isValidTempWstatus_spec(value: Isolette_Data_Model::TempWstatus_i) -> bool
   {
-    value.status == Isolette_Data_Model::ValueStatus::Valid
+    value.status != Isolette_Data_Model::ValueStatus::Valid
   }
   // END MARKER GUMBO VERUS MARKER
```

<a id="d18"></a>
### D18 — scene 12: the inverted command in the unverified FFI glue

Plain Rust behind an `external_body` boundary — Verus never reads this
body, so every proof passes over it, and the escape-construct surface
is unchanged. Only the gensrc byte anchor sees it.

```diff
--- a/crates/thermostat_rt_mhs_mhs/src/bridge/extern_c_api.rs
+++ b/crates/thermostat_rt_mhs_mhs/src/bridge/extern_c_api.rs
 -57,7 +57,13 
 pub fn unsafe_put_heat_control(value: &Isolette_Data_Model::On_Off) -> bool
 {
   unsafe {
-    return put_heat_control(value as *const Isolette_Data_Model::On_Off as *mut Isolette_Data_Model::On_Off);
+    // TAMPERED: command inverted at the unverified FFI boundary
+    let inverted = match value {
+      Isolette_Data_Model::On_Off::Onn => Isolette_Data_Model::On_Off::Off,
+      _ => Isolette_Data_Model::On_Off::Onn,
+    };
+    return put_heat_control(&inverted as *const Isolette_Data_Model::On_Off
+                            as *mut Isolette_Data_Model::On_Off);
   }
 }
```

