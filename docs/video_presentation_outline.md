# Video outline: "Lifecycle Attestation with pybb" (~20 min)

Target: ~20 minutes max. Audience: mixed / general technical (every
section self-contained). Format: live terminal captures with slide
interludes — slides for preliminaries and act transitions, captured
runs of `examples/demo_isolette.sh` for the scenes, VSCode diffs shown
at tamper beats.

## 0. Framing — slide (1.5 min)

- Classical remote attestation asks: *is the running system what we
  blessed?* **Lifecycle attestation** extends the same
  measure-and-appraise discipline to the artifacts of the development
  lifecycle — models, contracts, implementations, proofs, toolchains,
  and the evidence itself — and to lifecycle **events**: drift, tamper,
  sanctioned change (bless/promote), repair.
- The recurring thesis, stated once here and echoed by every scene:
  **standing comes from fresh measurement, never from a claim.**

## 1. Preliminaries — slides (5 min)

### 1a. Core attestation stack (2 min)

One architecture slide: Copland (attestation protocols as terms with an
evidence semantics) → CVM (executes phrases; manifests, ASPs,
appraisal) → asp-libs (the measurement/appraisal primitives: hash,
readfile, signature, golden comparison). Output: **signed evidence
bundles** appraised against **golden baselines**. For a mixed audience
this stays at the "what each layer contributes" level, no Copland
syntax.

### 1b. pybb architecture (2 min)

One workflow diagram: measurements land as blackboard entries; segments
(provision / certify / escalate); the controller cycle evaluates
predicates — which *are* attestation episodes; **knowledge sources**
are repair rungs on outcome-routed chains; failure handoff,
restart-episode, escalation. The one idea to land hard: the **repair
ladder** — a rung's exhaustion is the *diagnosis* that a different
artifact is at fault, and every repair is judged only by
re-measurement.

### 1c. Artifact classes (1 min)

A single table slide: **model** (blessed, signed), **contract** (named
slices), **implementation**, **proof/verification** — plus the two
cross-cutting classes: **toolchain** (hashed measure-then-use) and
**trust state** (bundles, goldens). Each row paired with its repair
species: restore, slice splice, re-derivation, regeneration-from-model,
out-of-band pause, principled refusal. This table becomes the map the
scenes get pinned to.

## 2. The isolette — live terminal, slide transitions between acts (10 min)

One transition slide introduces the target: the INSPECTA seL4/Microkit
isolette exemplar, SysMLv2 → HAMR codegen → Verus-verified Rust; 13
measured files, 67 contract slices, 8 verified crates, ~1862
system-proof obligations. Scene numbers below refer to
[demo_isolette_script_summary.md](demo_isolette_script_summary.md).

### Act I — the honest baseline: Scene 1 (1.5 min)

One episode over every artifact class, the per-crate checklist all
green, toolchain hashed in the same term. Establishes what "good
standing" looks like so every later refusal reads instantly.

### Act II — sanctioned change: Scene 3, breaking variant (2.5 min)

The lifecycle heart of the talk. GUMBO contract edit → attribution by
slice → interactive ruling → **bless** (spec-first, props only) →
**promote** (tool-gated real codegen catch-up) → and the honest ending:
gold moves *without* a verification gate, so the next episode reports
Verus RED — a blessed spec the implementation doesn't yet meet,
reported truthfully. This scene alone carries the "attestation across
sanctioned lifecycle events" claim.

### Act III — unsanctioned change, repaired: Scene 2 (1.5 min)

Implementation tamper; contracts-intact rung exhausts (diagnosis), impl
rung restores crate-scoped, restarted episode re-attests. The ladder
repairs the *right* artifact.

### Act IV — attacks on trust itself: Scene 6 (1.5 min)

Three beats, one gate, three attributed refusals: flipped
signed-evidence byte (signature), hand-edited golden (anchor),
laundered re-provision (derivability/lineage). The punchline: the
readiness gate's failure chain is *empty by design* — no knowledge
source may repair a baseline; the only exit is out-of-band re-bless.

### Act V — "verification succeeded" is not enough: Scene 12 (2 min)

The most visceral for a mixed audience: the heat command inverted in
unverified FFI glue behind `external_body` — every proof passes, the
cheat scan is silent, only the gensrc byte anchor refuses; repair by
regeneration-from-model. Close the act with a 15-second nod to Scenes
9–11 as the fuller taxonomy (proof escapes, the hollow system proof,
the stale dep cache).

### Coverage beat (30 s)

The scene × artifact-class × repair-species matrix as a spoken line
over Act V's last frame (budget reclaimed for the AI-in-the-loop
capstone), with the 5 shown scenes highlighted and the other 7
one-lined — signals depth without spending runtime.

## 3. Same workflow, other ecosystems — slides (~4 min)

- **Rocq** (temp-control as the example;
  [demo_rocq.sh](../examples/demo_rocq.sh), 8 scenes): adds the repair
  species isolette honestly can't have — **proof synthesis** (tactic
  portfolio, opt-in LLM) and spec-guided implementation re-derivation.
- **Lean** (landing gear, temp-control, and the goal-directed
  encoding): a third prover ecosystem on the same blackboard workflow —
  culminating in blessed *statements* with workflow-owned proofs, where
  attestation enforces exactly one invariant while an automated
  synthesis workflow iterates freely underneath.
- **AADL-Slang**: the AADL frontend with HAMR codegen to Slang/JVM — a
  different modeling language and target runtime, same artifact classes
  and protocols.
- **Diverse repair strategies**: the knowledge-source abstraction
  admits any repair engine, all judged the same way — by fresh
  measurement, never by the repairer's claim. Examples: golden value
  restoration (wholesale and per-contract slice), AutoVerus, homegrown
  repair agents (the KU Dogtreat repairer), LLM engines via API keys,
  LLM desktop sessions, and pausing for manual out-of-band user
  intervention.
- The point of the section: per-ecosystem artifact mappings and
  pluggable knowledge sources slot into one unchanged pybb workflow —
  that's what makes it *lifecycle* attestation rather than a per-tool
  integrity check.

### Capstone: "AI in the loop" — two slides (~1.5 min)

**Slide A — AI inside the workflow.** The lifecycle pipeline annotated
with AI touchpoints per stage, and the AI-free zone marked: model/spec
(LLMs may draft; only the administrator blesses), implementation
(spec-guided synthesis with LLM engines), proofs (the ladder's engines:
tactic portfolio first, then LLM API engines, AutoVerus, desktop agent
sessions, the KU Dogtreat repairer), verification & appraisal (**no AI
by design** — the judges stay deterministic), evidence/trust state
(**no AI by design** — refusal properties). Callout: *AI proposes;
measurement disposes* — an LLM's output is just another untrusted
artifact, same episode, same appraisal; keyless by default.

**Slide B — AI built the loop.** Every layer was built in Claude
desktop and CLI sessions, git-attested (`Co-Authored-By: Claude`), and
judged by the discipline itself:

| Layer | AI-built | Judged by |
|---|---|---|
| pybb | blackboard/controller/KS framework, both demo arcs, install + CI | scene gates on expected output |
| ASP primitives (asp-libs, Rust) | **12 new** binaries + **7 upgraded** (cheat scan, batch hashing, Lean/Rocq/HAMR runners & appraisers, golden-slice extraction) | tool hashes measure-then-use; appraisal vs signed goldens |
| Copland protocols | **41 provisioned protocol dirs** across 5 ecosystems | readiness-gate config checks; blessed baselines |
| CVM core | `bpar` parallel execution in the *verified* VM | **the Rocq proofs had to re-prove** |

Kicker: the workflow never asked whether the author was human or AI —
trust never came from the author. *Standing comes from measurement.*
Speaker aside: cvm-mcp — an AI-built MCP interface so AI agents can
drive attestation, closing the loop. (Budget offset: the section-2
coverage slide becomes a spoken line over Act V's last frame.)

## 4. Close — slide (1 min)

Recap the thesis; roadmap as evidence of a principled scope:
episode-triggering monitors, the executable artifact class, attested
freshness guards, lineage anchoring across promote.

## Production notes

- Scene 3's promote beats add ~1–2 min of codegen wall-clock each, and
  Scene 12's regeneration also runs real codegen — pre-record and trim
  those runs (or use `--fast` where honest) rather than capturing live
  in one take.
- The demo's opt-in VSCode diffs are ideal camera material at each
  tamper beat — show them at least in Acts II and V.
- Tie-backs that make section 3 land as payoff rather than new ideas:
  in Acts III/V, a spoken line like "restore is one rung; the ladder
  accepts any engine"; the repair-strategies bullet can open with "the
  ones you saw" (crate-scoped restore, slice splice) before moving to
  the synthesis-based engines.
