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

> Preliminaries → The Isolette (5 acts) → Other Ecosystems → AI in the
> Loop → Close

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
  **manifests** declare who may measure what; dispatches ASPs;
  appraises results
- **asp-libs** — its own layer box under CVM: the
  measurement/appraisal primitives (hash, readfile, signature, golden
  comparison); still one spoken clause at most, not a talking point
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
  a formal object with an evidence semantics." Measure the five
  blessed model files, sign the evidence, appraise it.
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

**Content**: workflow diagram:

- Measurements arrive as **blackboard entries**; three segments:
  **provision** (requests; no repair chains — failures escalate
  immediately), **certify** (working entries), **escalate** (needs a
  human)
- The **controller cycle**: evaluate predicates — each predicate *is*
  an attestation episode — then dispatch entries onto
  **outcome-routed chains** (on_pass / on_fail)
- **Knowledge sources** = repair rungs: attempt, re-verify, hand off
  on failure; **restart-episode** forces genuine re-measurement; end
  of ladder = escalation
- Callout box (the one idea to land): **the repair ladder** — a rung's
  *exhaustion is the diagnosis* that a different artifact is at fault,
  and every repair is judged only by re-measurement

**Checklist legend** (corner box — the demo is read through these
glyphs):

> ✓ attested · ✗ refuted · ? poisoned, fail-closed

**Speaker notes**: keep the vocabulary minimal — entry, episode,
knowledge source, ladder, escalate. Everything else is detail the
scenes show live. The legend earns its space: every scene's checklist
frames render through it.

**Decisions**: legend added (2026-08-25) since the format is live
terminal — the audience will literally read ✓/✗/? in scene output.

---

## Slide 6 — Artifact classes: the map the scenes get pinned to — DRAFTED

**Timing**: ~1 min.

**Content**: single table, columns in the **class → measured how →
judged by → repair species** shape (the same shape capstone slide B
reuses):

| Class | Measured how | Judged by | Repair species |
|---|---|---|---|
| **Model** | blessed, signed spec files (whole-file) | appraisal vs the signed golden | restore from golden — or *bless* (sanctioned change) |
| **Contract** | declaration-named slices | slice-level appraisal, attributed by name | slice splice |
| **Implementation** | developer-owned code | the contracts that must hold of it | re-derivation from spec / restore |
| **Proof / Verification** | live verification run | the kernel / Verus — fresh, never cached | proof synthesis; regeneration |
| **Toolchain** *(cross-cutting)* | hashed **measure-then-use** | the tool hash, taken in the same term | out-of-band restore only |
| **Trust state** *(cross-cutting)* | bundles, goldens, signatures | signature · anchor · derivability | **principled refusal** — out-of-band re-bless |

**Speaker notes**

- The last two rows are the surprising ones — scenes 6–7 exist for
  them.
- **"This table is deliberately incomplete — the demo will show why."**
  (The cheat / sysproof / gensrc tiers are capstone slide C's
  punchline: attacks forced them into existence. Do not pre-introduce
  them here.)

**Decisions**: third column ("judged by") added to align with slide
B's table shape; incompleteness is a spoken hook, never on-slide text.

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
