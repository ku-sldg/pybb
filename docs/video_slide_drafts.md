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

> **Lifecycle Attestation with pybb**
> *Measured trust across models, contracts, implementations, and proofs*
>
> Presenter name · affiliation · date

**Visual**: clean title card; optional footer for program context
(INSPECTA).

**Decisions**: subtitle names the four core artifact classes on
purpose — it is the deck's first echo of the artifact-class table
(slide 6).

---

## Slide 2 — What is lifecycle attestation? — DRAFTED

**Timing**: ~1.5 min.

**Content**

- Traditional remote attestation: **did system components boot into a
  predictable state?** (boot-time, static runtime)
- Layered, runtime attestation: extend boot-time trust via dynamic
  measurement of system components **and their context/dependencies**
- Lifecycle attestation: extends this notion to **artifacts of the development lifecycle**:
  models, contracts, implementations, proofs, toolchains 
  - ...including the attestation infrastructure and evidence itself
  - …and to lifecycle **events**:
    - specification drift (sanctioned or not)
    - artifact tampering
    - artifact synthesis
    - artifact repair
- Motivation: the **proliferation of AI-generated software
  artifacts**, amid the need for rapid re-certification of systems (one clause, no dedicated bullet — the seed the
  AI-in-the-loop capstone pays off)

**Banner** (bottom, styled, the deck's recurring element):

> **Every trust decision is grounded in cryptographic attestation
> evidence.**
> *trust is NOT anchored in the following: developer claims, untrusted
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
"every … decision" plus the NOT-anchored subline.

---

## Slide 3 — Roadmap strip (design element + first appearance) — DRAFTED (headers provisional)

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

---

## Slide 4 — The core attestation stack — DRAFTED

**Timing**: ~1.5 min.

**Content**: layered diagram, top to bottom, one phrase of "what this
layer contributes" each:

- **Copland** — attestation protocols as formal terms with an evidence
  semantics: *what* was measured, in *what order*, signed by *whom*
- **CVM** (Copland Virtual Machine) — executes Copland phrases;
  dispatches ASPs according to **manifest** configurations; appraises
  results
- **asp-libs** — its own layer box under CVM: the
  measurement/appraisal primitives (hash, readfile, signature, golden
  comparison, …); still one spoken clause at most, not a talking point
- Output arrow: **signed evidence bundles**, appraised against
  **golden baselines**

**Copland snippet** (visual texture, sidebar): the isolette's actual
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
  snippet (20pt, three lines): "measure the five blessed model files →
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
  in the measured loop), "bless ⇒ provision" arrow into the provision
  lane
- **measurement → Blackboard** (three lanes: provision / certify /
  escalate) → **Controller (evaluate = episode)** → dispatch → **KS 1
  → KS 2 → KS n**
- **Green paths (on-pass)**: every KS returns to the Controller —
  "re-verify · restart-episode ⇒ fresh measurement"; provision lane →
  measurement ("provisioned ⇒ re-measure")
- **Red paths (on-fail)**: KS→KS handoff on exhaustion (changes
  restored); route exhausted → escalate lane; provision → escalate
  ("no repair chain: fail ⇒ escalate" — the readiness-gate refusal)
- **Controller → measurement** loop along the bottom: "evaluate ⇒ run
  measurement"
- Callout box (bottom, navy — visual rhyme with slide 2's banner):
  **The repair ladder:** a rung's exhaustion is a ***local
  diagnosis*** of failure — every repair is judged only by ***fresh
  re-measurement*** (wording per deck edit 2026-08-25)

**Checklist legend** (bottom-right corner box, monospace — the demo is
read through these glyphs):

> ✓ attested · ✗ refuted · ? poisoned, fail-closed

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

---

## Slide 5b — pybb key components — DRAFTED (content pending review)

**Timing**: ~1 min. Follows the architecture diagram; gives the
vocabulary the scenes will use, one line per term.

**Content** (term bold, one-line description each):

- **Blackboard** — the shared store: every measurement lands as an
  entry with its condition and standing; three segments (provision ·
  certify · escalate) plus a full history of every change
- **Blackboard Entry (Key)** — one measurement under judgment,
  identified by its key: the measurement, its condition, its standing,
  its repair history
- **Episode** — one full judgment of an entry: the attestation runs
  once and its verdicts are memoized until the episode ends — or is
  restarted for genuinely fresh measurement
- **Partition** — the division of blackboard entries among different
  workflow stages: each knowledge source watches its own collection of
  keys, and an entry sits in the partition of whichever rung currently
  owns it
- **Controller** — the cycle: evaluates every entry (provision first),
  dispatches keys onto outcome-routed chains, advances or hands off,
  escalates; halts only when everything is in good standing
- **Knowledge source (KS)** — a repair rung: operates only on entries
  in its partition (optionally a single component), bounded by
  max_attempts; its work is always re-judged, never trusted
- **Route** — the per-key chains: **on_fail** = the repair ladder,
  **on_pass** = a confirmation chain before an entry may rest in good
  standing
- **History / Ledger** — the blackboard's running record of every
  change across all segments — measurements, repairs, verdicts — the
  audit trail of the repair lifecycle

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

## Slide 7 — Isolette intro (stats) — STUB

The section-2 transition slide. Numbers ready in the outline: INSPECTA
seL4/Microkit exemplar, SysMLv2 → HAMR → Verus-verified Rust; 13
measured files, 67 contract slices, 8 verified crates, ~1862
system-proof obligations. Roadmap strip highlights "The Isolette".

## Slides 8–12 — Act transitions I–V — STUB

Template: roadmap strip + act title + one "what to watch for" line.
Act titles from the outline: I the honest baseline · II sanctioned
change · III unsanctioned change, repaired · IV attacks on trust
itself · V "verification succeeded" is not enough. The
"what to watch for" lines double as the narration skeleton for the
terminal captures. Optional: Act IV/scene 7 reprises the verus-tier
measure-then-use phrase (see slide 4 decisions).

## Slide 13 — Other ecosystems — STUB

Compress the outline's five bullets (Rocq · Lean · AADL-Slang ·
diverse repair strategies · the section's point) into one or two
slides; density decision pending.

## Slides 14–16 — Capstone A / B / C — DRAFTED (in the outline)

Content finalized at slide level in the outline's section-3 capstone
(three tables + kickers). Will migrate here verbatim when the .pptx
pass starts, to keep one source of truth.

## Slide 17 — Close — STUB

Recap the banner; roadmap-as-principled-scope: episode-triggering
monitors, the executable artifact class, attested freshness guards,
lineage anchoring across promote.
