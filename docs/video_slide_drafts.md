# Slide drafts — "Lifecycle Attestation with pybb"

Slide-level source of truth for the video presentation, one section per
slide: content, visuals, speaker notes, and the decisions behind them.
The talk-level plan (timing, scene selection, act structure) lives in
[video_presentation_outline.md](video_presentation_outline.md); this
file is what the eventual .pptx is generated from. Status per slide is
marked **DRAFTED** / **STUB**.

Global decisions:

- **Thesis banner** (locked): *"Every trust decision is grounded in
  cryptographic attestation evidence."* Subline: *"trust is NOT
  anchored in the following: developer claims, untrusted tools, LLM
  outputs, cached verdicts."* Installed on slide 2, echoed verbatim by
  the capstone slides.
- **Roadmap strip**: a thin horizontal position indicator on
  transition slides (see Slide 3); section header titles on it are
  provisional and expected to change.
- **Format**: slides for preliminaries and transitions; live/captured
  terminal for the isolette scenes; VSCode diffs at tamper beats.
- Total runtime target ~20 min; per-section timing in the outline.

---

## Slide 1 — Title — DRAFTED

**Content**

> **Lifecycle Attestation with pybb** *(**py**thon **b**lack**b**oard)*
> *Measured trust across models, contracts, code, and proofs in*
> *high assurance, LLM-assisted development pipelines* (centered, two lines)
>
> Adam Petz¹, Isaac Amundson², Timothy Barclay², David Hardin², Jason Belt³, John Hatcliff³, Anakha Krishna¹, Ina Harris¹, Perry Alexander¹
> ¹University of Kansas    ²Collins Aerospace    ³Kansas State University
> September 2026    *Supported by the DARPA PROVERS effort (contract FA8750-24-9-1000)*

**Visual**: clean title card; optional footer for program context
(INSPECTA).

**Decisions**: subtitle names the four core artifact classes on
purpose — it is the deck's first echo of the artifact-class table
(slide 6). Author block (2026-09-03) taken from the paper's IEEE
author list with numbered-superscript affiliations; Will Thomas and
Amer Tahat deliberately excluded per user. More authors to be added;
the author box is bottom-anchored so a second line grows upward.
Date is a placeholder until the presentation date is fixed. Sponsor
footer (2026-09-03) right-aligned on the date line; wording copied from
the HCSS 2026 paper's `\thanks{}` (hcss26.tex). Tool-name gloss
(2026-09-03): "(python blackboard)" inline after pybb on the title line,
lowercase, 22pt Calibri italic in the subtitle's ice color, so it reads
as an aside rather than a separate caption (a stacked caption line was
tried first and rejected). User edits in PowerPoint (2026-09-03), ported
to the generator: the py/b/b letters of the gloss enlarged to 36pt bold
so the acronym pops; subtitle reworded ("code" for "implementations",
plus the "in high assurance, LLM-assisted development pipelines" tail)
and set as two centered lines.

---

## Slide 2 — Roadmap strip (design element + first appearance) — DRAFTED (deck position 2 since 2026-09-03)

**Timing**: ~15 s on first appearance; ~free thereafter (it rides on
transition slides).

**Content**: a thin horizontal strip, five segments, current section
highlighted:

> Preliminaries → Demo: Isolette (SysMLv2 → Rust) → Other Ecosystems →
> AI in the Loop → Close

(The demo segment renders as two lines in its chip: "Demo:" /
"Isolette (SysMLv2 → Rust)" — per deck edits 2026-08-25.)

**Decisions**

- Reused as the act-transition template in section 2 (the strip
  highlights position; the act title and "what to watch for" line sit
  below it) — one design, not one extra slide per transition.
- **Header titles are provisional** — expect tweaks as sections firm
  up; keep the strip's text in one master/layout so a rename is a
  single edit.
- User edits (2026-09-03): the on-slide "Section headers provisional"
  caption was removed, and the strip now precedes the lifecycle
  attestation slide (deck positions 2 and 3 swapped).

---

## Slide 3 — What is Lifecycle Attestation? — DRAFTED (deck position 3 since 2026-09-03)

**Timing**: ~1.5 min.

**Content**

- Traditional remote attestation: did system components boot into a
  predictable state? (boot-time, static runtime)
- Layered, runtime attestation: extend boot-time trust via dynamic
  measurement of system components and their context/dependencies
- Lifecycle attestation: extends this notion to **artifacts of the development lifecycle**:
  models, contracts, implementations, proofs, toolchains 
  - ...including the attestation infrastructure and evidence itself
  - …and to natural lifecycle events:
    - specification drift
    - toolchain updates
    - artifact updates, synthesis, repair
- Motivation: the **proliferation of AI-generated software
  artifacts**, amid the need for **rapid re-certification of systems** (one clause, no dedicated bullet — the seed the
  AI-in-the-loop capstone pays off)

**Banner** (bottom, styled, the deck's recurring element):

> **Every trust decision is grounded in cryptographic attestation
> evidence.**
> *Trust is NOT anchored in the following: developer claims, untrusted
> tools, LLM outputs, cached verdicts*

**Visual**: a three-stage progression, left to right, each stage
widening the measurement scope (mirrors the first three bullets):

1. **Boot-time** — a single system box with a boot-chain arrow into
   it; one measurement hook (static, once).
2. **Layered runtime** — the same system box now surrounded by its
   context/dependencies (libraries, config, peer components), dynamic
   measurement hooks on the running pieces.
3. **Lifecycle** — the full loop (model → contracts → implementation →
   proofs → deploy) enclosing the runtime picture, measurement hooks
   on every edge — including one on the evidence/infrastructure
   itself.

Consistent hook glyph across all three stages so "widening scope"
reads visually, not just verbally.

**Speaker notes**

- Promise the audience every demo scene echoes the banner.
- The administrator's *bless* survives "every": authority enters the
  system only *as* signed evidence (the blessed baseline), never by
  assertion — scene 6's laundering beat proves exactly that.
- Subline payoffs, for the presenter's own map: developer claims →
  scenes 5/7 · untrusted tools → scene 7 · LLM outputs → capstone
  slides A/B · cached verdicts → scene 11.

**Decisions**: banner wording locked (2026-08-25 session); "sole" and
"remain" deliberately avoided; the exclusivity claim is carried by
"every … decision" plus the NOT-anchored subline. User edits in
PowerPoint (2026-09-03), ported to the generator: title capitalized
("Lifecycle Attestation"), event list reworded to natural lifecycle
events (drift / toolchain updates / artifact updates, synthesis,
repair), banner nudged up (y 5.55 → 5.36), subline capitalized; slide
moved after the Roadmap so the strip is seen first. Bolding reduced:
lead-in labels and "did system components…", "and their
context/dependencies" un-bolded; "rapid re-certification of systems"
bolded (generator briefly re-added the old bolding; fixed same day).

---

## Slide 4 — The core attestation stack — DRAFTED

**Timing**: ~1.5 min.

**Content**: layered diagram, top to bottom, one phrase of "what this
layer contributes" each:

- **Copland** — attestation protocols as formal terms with an evidence
  semantics (the "*what* was measured, in *what order*, signed by *whom*"
  tail dropped 2026-09-03)
- **Copland Virtual Machine (CVM)** — executes Copland phrases;
  dispatches ASPs according to **manifest** configurations; appraises
  results
- **asp-libs** — its own layer box under CVM: the
  measurement/appraisal primitives (hash, readfile, signature, golden
  comparison, …); still one spoken clause at most, not a talking point
- Output arrow: **signed evidence bundles**, appraised against
  **golden baselines**

**Copland snippet** (visual texture, sidebar; captioned "Copland
protocol from the demo — the Isolette model class:"): the isolette's actual
model-class protocol (`tests/fixtures/isolette_sysmlv2_rust_props/term.json`),
rendered in concrete syntax:

```
( readfile Regulate.sysml
  +<+ readfile Monitor.sysml
  +<+ readfile Operator_Interface.sysml
  +<+ readfile oip_oit_app.rs
  +<+ readfile GUMBO_Library )
-> SIG -> APPR
```

**Speaker notes**

- On the snippet: "you don't need to read this — you need to know it's
  a formal object with an evidence semantics." Caption below the
  snippet (20pt, three lines): "measure five blessed model files →
  / sign the evidence (SIG) → / appraise it (APPR)".
- asp-libs gets one spoken clause at most; its inventory returns as a
  star of capstone slide B.

**Decisions**

- asp-libs demoted from a talking point to a visual-only layer
  (reclaims ~0.5 min): first drafted as a label inside the CVM box,
  then given its own layer box under CVM (2026-08-25) — it appears in
  the stack but gets at most one spoken clause.
- Snippet candidate chosen: the **props protocol** — the simplest real
  phrase (three constructs: `+<+` branch-sequence, `SIG`, `APPR`).
  The verus-tier phrase (hash the toolchain `->` run cargo-verus over
  8 crates `->` SIG) was considered and held back: it is the
  **measure-then-use** pattern and belongs to scene 7's reveal, not
  the preliminaries. Optionally reprise it on Act IV/scene 7's
  transition slide.

---

## Slide 5 — pybb: a blackboard architecture for attestation — DRAFTED

**Timing**: ~2 min.

**Content**: process-flow diagram (layout candidate 1, chosen from
three sketched candidates 2026-08-25), left to right:

- **Administrator blessing (signs golden spec)** — dashed white box
  above the board (a human, out-of-band authority act, not a component
  in the measured loop), arrow into the provision lane (its "bless ⇒
  provision" label removed 2026-09-03)
- **measurement → Blackboard** (three lanes: provision / certify /
  escalate) → **Controller (evaluate = episode)** → dispatch → **KS 1
  → KS 2 → KS n**
- **Green paths (on-pass)**: every KS returns to the Controller —
  "on-pass: restart-episode ⇒ fresh measurement"; provision lane →
  measurement ("provisioned ⇒ re-measure")
- **Red paths (on-fail)**: KS→KS handoff — "on-fail: handoff to next
  repair KS (attempts spent, changes restored)"; route exhausted →
  escalate lane; provision → escalate ("on fail: no repair chain =>
  escalate" — the readiness-gate refusal)
- **Controller → measurement** loop along the bottom: "evaluate ⇒ run
  measurement"
- Callout box (bottom, navy — visual rhyme with slide 2's banner):
  **The repair ladder:** a rung's exhaustion is a ***local
  diagnosis*** of failure — every repair is judged only by ***fresh
  re-measurement*** (wording per deck edit 2026-08-25)

**Checklist legend**: moved off this slide 2026-09-03 to the Act I
transition slide (see Slides 8–12), reworded there.

**Speaker notes**: keep the vocabulary minimal — entry, episode,
knowledge source, ladder, escalate. Speaker-note-only details cut from
the slide: on_pass/on_fail dispatch mechanics, success-driven handoff
for component-wise entries, max_attempts per rung. The legend earns
its space: every scene's checklist frames render through it.

**Decisions**

- Layout: candidate 1 (process flow) chosen over classic-blackboard
  and hybrid-ladder sketches; semantics verified against the pybb
  README control flow, with three corrections applied: repairs return
  to the *Controller* (standing is re-established only by its
  re-evaluation, never by a KS writing to the board); the provision
  lane shows both exits (green to measurement, red straight to
  escalate — no repair chains); KS→KS arrows are failure handoff, not
  a pipeline.
- Blessing box label discussed and locked: "Administrator blessing
  (signs golden spec)"; dashed border = out-of-band human act (the
  only exit from a refused baseline, scene 6).
- Legend added since the format is live terminal — the audience will
  literally read ✓/✗/? in scene output.
- "dispatch" label nudged left (x 8.28→8.20) for spacing, per deck
  edit.
- User edits 2026-09-03 (ported): arrow labels set in plain (not
  italic) type and reworded — "on-pass: restart-episode ⇒ fresh
  measurement" (the "re-verify ·" dropped), "on-fail: handoff to next
  repair KS / (attempts spent, changes restored)" replaces the
  "red → =" key, "on fail: no repair chain => escalate" moved right
  beside the escalate lane; "bless ⇒ provision" label deleted; legend
  box removed (now on the Act I transition slide).

---

## Slide 5b — pybb key components — DRAFTED (content pending review)

**Timing**: ~1 min. Follows the architecture diagram; gives the
vocabulary the scenes will use, one line per term.

**Content** (term bold, one-line description each):

- **Blackboard** — a collection of entries: the shared measurement
  store updated cooperatively by blackboard components
- **Blackboard Entry (Key)** — a measurement under judgment: its
  measurement content, current standing, repair history
- **Episode** — one full judgment of an entry: attestation records
  verdicts, must be restarted for fresh measurement
- **Partition** — the division of blackboard entries among different
  workflow stages (i.e. provision, certify, escalate)
- **Controller** — evaluates every entry (once provisioned),
  dispatches keys onto outcome-routed chains, advances or hands off,
  escalates, halts only when entries are in good standing
- **Knowledge source (KS)** — operates only on entries in its
  partition (optionally a single component), bounded by max attempts;
  its work is always re-judged, never trusted
- **Route** — the per-key control flow chains: `on_fail` = the repair
  ladder, `on_pass` = a confirmation chain before good standing
  (chain names in monospace on-slide)
- **History / Ledger** — the blackboard's running record of every
  change across all partitions (measurements, repairs, verdicts),
  documenting the audit trail of the repair lifecycle

**Parked — currently OFF the slide** (out of place in the component
list; decided 2026-08-25 to leave off for now, placement TBD — e.g. a
small "evaluation primitives" strip at the bottom, or annotations
pointing at the slide-5 diagram):

- **Predicate** — the judge: a registered callable per entry key; for
  attestation predicates, one evaluation *is* one attestation episode
- **Restart-episode** — the freshness primitive: forget memoized
  verdicts, reset the entry, re-evaluate — genuinely fresh measurement

**Visual**: text slide; each term could carry a small color chip
matching its element on the slide-5 diagram (board = ice, controller =
mid navy, KS = navy, green/red for the route arrows) so the two slides
read as a pair.

**Speaker notes**: this is the audience's glossary for the terminal
scenes — point back at the diagram while reading it. Entry keys in the
real demos are the provisioned protocols — `ready` (the readiness
gate), `isolette_sysmlv2_rust_props` (blessed model), `…_l1a` (file
hashes), `…_l2` (contract slices), `…_verus`, `…_cheat`, `…_sysproof`,
`…_gensrc`, `…_report` — and every row of the checklist the audience
is about to watch is one of these keys. Terms deliberately excluded
(README-level detail): partition mechanics, component-wise entries and
success handoff, dispatch latching, max_cycles.

**Decisions**

- Added 2026-08-25 as a companion to the architecture diagram;
  numbered 5b to keep downstream slide numbers stable.
- Budget note: +1 min to preliminaries (~5.5 total). Offset option if
  the 20-min cap binds: the architecture slide's talk time drops
  2 → 1.5 min since the glossary now carries the vocabulary load.
- User edits 2026-09-03 (ported): all eight definitions tightened;
  the Route entry sets `on_fail` / `on_pass` in Courier New.

---

## Slide 6 — Artifact classes: the map the scenes get pinned to — DRAFTED

**Timing**: ~1 min.

**On-slide title**: "Artifact classes" (shortened per deck edit
2026-08-25; "the map the scenes get pinned to" is spoken, not
on-slide).

**Content**: single table, columns in the **class → measured how →
judged by → repair species** shape (the same shape capstone slide B
reuses):

| Artifact Class | Measured how | Judged by | Repair type |
|---|---|---|---|
| **Model** | whole-file hash of spec files | appraisal vs the signed golden | restore from golden — or *bless* (sanctioned change) |
| **Contract** | syntax-guided file slices | slice-level appraisal, attributed by name | restore golden slice |
| **Implementation** | developer-owned code | tests + verification of contracts | code synthesis/repair |
| **Proof / Verification** | live verification run | verification kernel — fresh, never cached | proof synthesis/repair |
| **Toolchain** *(cross-cutting)* | hashed **measure-then-use** | the tool hash(es), taken in the same term | out-of-band or pre-sanctioned restore |
| **Trust state** *(cross-cutting)* | bundles, goldens, signatures | appraisal vs the signed golden or derived | **principled refusal** — out-of-band re-bless |

**Speaker notes**

- The last two rows are the surprising ones — scenes 6–7 exist for
  them.
- **"This table is deliberately incomplete — the demo will show why."**
  (The cheat / sysproof / gensrc tiers are capstone slide C's
  punchline: attacks forced them into existence. Do not pre-introduce
  them here.)

**Decisions**: third column ("judged by") added to align with slide
B's table shape; incompleteness is a spoken hook, never on-slide text.
Table wording per manual markdown edits 2026-08-25 (syntax-guided
slices, code/proof synthesis-repair, sanctioned toolchain restore,
golden-or-derived trust-state appraisal); generated into the deck as
position 7 the same day.

---

## Slide 7 (deck position 8) — The isolette — DRAFTED

**Timing**: ~1 min. This slide IS the section transition into the
demo: the roadmap strip rides at the top with the "Demo:" segment
highlighted.

**On-slide title**: "The Isolette Example" (was "The isolette";
user edit 2026-09-03).

**Left half — what it is** (four beats):

- **The system**: infant-incubator thermostat that regulates and
  monitors a newborn's environment to maintain a safe temperature
  range (heat control on/off).
  - sub-bullet, small italic: requirements traceable to FAA AR-08-32
    (the REQ-MHS-* family the scenes will tamper with). (Sub-bullets
    use PowerPoint's default Courier New "o" glyph and indents; the
    generator patches these in post-build to stay faithful.)
- **The relevance**: the INSPECTA program's seL4/Microkit HAMR-based
  pipeline. (Lead-in renamed from "The provenance" per deck edit
  2026-08-25; wording and sub-bullet structure per user edit
  2026-09-03.)
  - sub-bullet: current, safety-critical development artifact, not a
    toy example.
- **The pipeline** (small horizontal graphic, not a bullet; moved up
  to sit under the bullets, 2026-09-03): SysMLv2 model + GUMBO
  contracts → HAMR codegen → Verus-verified Rust → seL4 + Microkit
  target.
- **Why this example**: every artifact class from the previous slide
  is present and measured — blessed model, generated contracts,
  developer-owned implementation, machine-checked proofs, pinned
  toolchain.

**Right half — big-number callouts** (the "the measured surface"
heading above them removed 2026-09-03):

- **13** measured files (SysMLv2 packages, Verus-contract-bearing Rust)
- **67** contract slices
- **8** crates re-verified every episode (7 components and the
  system-level proof)
- **1,862** system-proof obligations
- **30** toolchain + dependency files hashed measure-then-use (4 Verus
  · 9 HAMR · 17 SysML libs)
- **8** attestation tiers — the blackboard's entry keys:
  `props` · `l1a` · `l2` · `verus` · `cheat` · `sysproof` · `gensrc` ·
  `report`

**References footer** (bottom, 8.5pt muted; K-State HAMR/isolette
credits, in addition to the AR-08-32 citation in the system beat):

1. Hatcliff & Belt, *The Isolette System: Illustrating End-to-End
   Artifacts for Rigorous Model-Based Engineering*, Springer LNCS
   15240, 2025. doi:10.1007/978-3-031-73887-6_9
2. Hatcliff, Belt, Robby, McKenzie, Liang, *End-to-End Formal Methods
   Integrated Development with SysMLv2 Using HAMR*, Springer, 2025.
   doi:10.1007/978-3-032-00942-5_13
3. Hatcliff, Belt, Robby, Carpenter, *HAMR: An AADL Multi-platform
   Code Generation Toolset*, ISoLA 2021, LNCS 13036, pp. 274–295.
   doi:10.1007/978-3-030-89159-6_18

(DOIs kept here for the record; on-slide the footer shows authors,
italic title, venue, year only.)

**Speaker notes**

- The tiers callout is the bridge: these keys are the glossary's
  "entry keys," and every checklist row in the scenes is one of them.
- Spoken line on the why-beat: "the table you just saw, instantiated."
- Held back on purpose (scene 9's reveal): the cheat-tier depth stats
  — 86 blessed `external_body` sites, 10 scanned crates.

**Decisions**

- Big-number callouts chosen over a per-tier table (avoids reading as
  a second artifact-classes table one slide later); cheat-tier stats
  held back; AR-08-32 on-slide as a citation line (2026-08-25).
- Numbers verified against live sources 2026-08-25 and exact (not
  approximate): 13 = l1a `hashfile` targets, 67 = l2 `readfile_range`
  slices, 8 = `run_command_cargo_verus` targets in the verus term,
  1,862 = `pub proof fn` count in `sys_nominal_proof/src`, 30 = tool
  hashfile targets (4 in the verus term: cargo-verus wrappers ×2,
  rust_verify, verus; 9 in `hamr_tools`: sireum.jar + OSATE/GUMBO
  plugin jars; 17 in `sysml_libs`: pinned sysml-aadl-libraries). They
  are provision-dependent — re-verify before recording day.

## Slides 8–12 — Act transitions I–V — DRAFTED (generated into deck positions 9–13, 2026-08-26)

Layout per slide: compact roadmap strip (Demo active) · "ACT N" label
(letter-spaced, muted) · descriptive title (40pt) · scene tag ·
watch-for line (20pt italic — the VO opener) · capture invocation as a
monospace presenter footer. Speaker notes carry the per-act beats from
the recording plan.

Template (per the isolette intro slide): compact roadmap strip at top
("Demo" segment active) + act title + one **"what to watch for"**
line, which doubles as the opening narration line over the terminal
capture. Presenter footer (small, muted) carries the exact capture
invocation. Eight captures across seven acts (Acts II–VI in consistent
active-verb tense; III/V paired as benign/breaking implementation
drift; see [video_recording_plan.md](video_recording_plan.md) for the
runbook):

| Act | Title | What to watch for | Invocation |
|---|---|---|---|
| I | The consistent baseline *(scene 1)* | "All artifacts start in a “pass” state: all artifacts have integrity against golden values and implementations meet their contracts." | `./examples/demo_isolette.sh --scenes 1` |
| II | Spec drift: benign, promote then re-verify *(scene 3, range)* | "A benign change in requirements — the temperature alarm range widened — model appraisal fails quickly. Administrator re-blesses new spec, all contract appraisals again pass." | `./examples/demo_isolette.sh --scenes 3 --drift range` (ruling: bless) |
| III | Implementation drift: benign, re-verify *(scene 13)* | "A developer rewrites implementation logic — semantically equivalent. The hash moves, but **every contract slice maintains integrity**, and the proofs re-verify: the benign change survives." | `./examples/demo_isolette.sh --scenes 13` |
| IV | Contract drift: breaking, restore then attempt re-verification *(scene 14)* | "The model is untouched, but a Verus contract is weakened (***after codegen, but before verification***) and the code is inverted to match — verus checks pass. Contract repair (restoring the true Verus contract) exposes the verification failure." | `./examples/demo_isolette.sh --scenes 14` |
| V | Implementation drift: breaking, diagnose then repair *(scene 2)* | "Implementation code (developer-owned) changes, breaking a Verus contract. Blackboard loop diagnoses, repairs (simulated for demo), then ***returns the artifact to good standing only by re-measurement***." | `./examples/demo_isolette.sh --scenes 2` |
| VI | Baseline drift: tampered evidence bundle, protocol, tooling *(scenes 6 + 7)* | "The signed golden evidence bundle, an installed golden value in the protocol ASP ARGS, then the verifier itself — each tamper attributed, each refused by cryptographic checks." | `./examples/demo_isolette.sh --scenes "6 7"` |
| VII | Axiom drift: semantic measurement detects axioms and unsound proof techniques *(scenes 9 + 12)* | "Proofs verify, but measurement detects **subtle ways that proof attempts cheat** to undermine verification soundness." | `./examples/demo_isolette.sh --scenes "9 12"` |

**Decisions**

- **Act II reverted to the single benign beat** (2026-08-27): the
  user's hand-edited slide 10 ("Spec drift: benign, promote then
  re-verify", scene 3 `--drift range` only) — recovered from git HEAD
  after a regeneration clobbered it, and ported into the generator.
  The breaking-spec ending was dropped: breaking now lives in Act IV
  (contract) and Act V (implementation), so Act II stays the clean
  benign-model story.
- **Scenes 13 and 14 added as Acts III and IV** (2026-08-26/27); old
  III–V renumbered V–VII. Act IV is the contract-launder scene whose
  drift the report's `compute_cases` slice gap missed — the l1b marker
  tier (a Copland protocol) and its coverage lint, built in-session,
  closed the hole; it ends on the exposed Verus refusal (no
  auto-repair — the exposure IS the beat). A capstone slide-C row.
- Active-tense titles (2026-08-27): II "promote then re-verify", III
  "re-verify", IV "restore then attempt re-verification", V "diagnose
  then repair", VI "refuse"; I (noun opener) and VII (thesis closer)
  left as-is.
- Uncaptured scenes accounted for: 9–11 → capstone slide C's attack
  table; 4/5/8 → the coverage beat.
- Act VII absorbs scene 9 (the axiom attacks) as beat 1
  (2026-08-27): the cheat-scan two-grid view (verus all green beside
  the proof-escape grid naming the construct) precedes the scene-12
  FFI beat, making Act VII a three-detector escalation (outcome →
  construct scan → byte anchor). Uses the new `--cheat-status` grid.
- Act timings: I 1.25 · II 1.75 · III 1.25 · IV 1.75 · V 1.5 ·
  VI 2.25 · VII 2.75 (scene 9 beat 1 + scene 12 beat 2) + 15 s
  coverage ≈ 13.75–14 min (total video ≈ 24). Offsets if the cap
  tightens: fold III into II, drop VI's scene 7, or show one of scene
  9's two axiom beats.

**Checklist legend on Act I** (user edit 2026-09-03, ported): the
✓/✗/? glyph legend formerly on slide 5 now sits bottom-right of the
Act I transition slide only, as three monospace lines — "✓ attested /
✗ refuted / ? poisoned (untrustworthy)" — where the first checklist
frames appear.

---

## Ecosystems — "One blackboard, many artifact pipelines" — DRAFTED (deck slide 16)

**Layout**: title + one-line thesis (blackboard / controller / repair
ladder / artifact classes invariant; only the pipeline swaps — modeling
language, prover, target runtime, **and the attestation primitives**),
then a **2×2 card grid**. Each card: title = the artifact pipeline,
caption = example system(s), 3–4 bullets. The isolette card is
highlighted navy.

- **SysML v2 → HAMR → Rust / Verus** — *isolette (◀ the demo)*:
  SysMLv2 GUMBO component contracts · seL4/Microkit runtime target ·
  every artifact class measured
- **AADL → HAMR → Slang / Logika** — *temp-control*: AADL GUMBO
  contracts · JVM runtime target · same blackboard, similar Copland
  protocols
- **Standalone Rust / Verus** — *find-max-verus*: contracts + proofs
  written directly in Verus · no model/codegen (impl + proof classes
  only) · proof-repair experiments: AutoVerus, KU Dogtreat linear
  planner
- **Interactive Theorem Provers: Lean / Rocq** — *landing-gear,
  temp-control*: blessed theorem statements, workflow-owned
  implementations + proofs · tactic- and LLM-driven proof repair ·
  goal-directed invariant · ITP-specific axiom checks

**Decisions**: iterated from a pipeline-chips version to the card grid
(2026-08-27..30); title carries the pipeline, examples become captions
(user edits). Four cards: added a standalone Rust/Verus card and
combined Lean+Rocq to stay at four. Repair-strategy breadth surfaced
per-card (AutoVerus/Dogtreat on the Verus card; tactic/LLM on the ITP
card) rather than a global footer. Content is the user's hand-edited
eco_edited.pptx, ported verbatim into the generator.

## Slides 14–16 — Capstone A / B / C — DRAFTED (in the outline)

Content finalized at slide level in the outline's section-3 capstone
(three tables + kickers). Will migrate here verbatim when the .pptx
pass starts, to keep one source of truth.

## Slide R — References (deck final slide) — DRAFTED

The collection point for every reference in the deck — always the last
slide; keep it current as sections are added. Grouped:

- **The isolette & HAMR (Kansas State)**: the three Hatcliff et al.
  papers (see slide 7's reference list for full details + DOIs),
  Lempia & Miller DOT/FAA/AR-08/32, and the INSPECTA models repo
  (github.com/loonwerks/INSPECTA-models).
- **Attestation foundations**: Ramsdell, Rowe, Alexander, Helble,
  Loscocco, Pendergrass, Petz, *Orchestrating Layered Attestations*,
  POST 2019, LNCS 11426. doi:10.1007/978-3-030-17138-4_9
- **Verification & platform**: Lattuada, Hance, Cho, Brun, Subasinghe,
  Zhou, Howell, Parno, Hawblitzel, *Verus: Verifying Rust Programs
  using Linear Ghost Types*, PACMPL 7 (OOPSLA1), 2023.
  doi:10.1145/3586037 · Klein et al., *seL4: Formal Verification of an
  OS Kernel*, SOSP 2009.

**Decisions**: Copland/Verus/seL4 seeded ahead of their sections
(2026-08-25); candidates to add later: the GUMBO contract-language
paper (HILT '22), CVM/attestation-manager papers, cheat_scan
provenance.

## Slide 17 — Close — STUB

Recap the banner; roadmap-as-principled-scope: episode-triggering
monitors, the executable artifact class, attested freshness guards,
lineage anchoring across promote.
