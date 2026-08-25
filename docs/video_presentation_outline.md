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
  and the evidence itself (a need sharpened by the **proliferation of
  AI-generated software artifacts** — the seed the AI-in-the-loop
  capstone pays off) — and to lifecycle **events**: drift, tamper,
  sanctioned change (bless/promote), repair.
- The recurring thesis, styled as a banner this slide installs and the
  later slides echo verbatim: **"Every trust decision is grounded in
  cryptographic attestation evidence."** Subline, smaller: *trust is
  NOT anchored in the following: developer claims, untrusted tools,
  LLM outputs, cached verdicts* (each item paid off by a later
  section: developer claims → scenes 5/7, untrusted tools → scene 7,
  LLM outputs → slides A/B, cached verdicts → scene 11).
- **Roadmap strip**: a thin position-indicator strip (preliminaries →
  five acts on the isolette → other ecosystems → AI in the loop →
  close), introduced here and reused as the act-transition template
  with the current section highlighted. Section header titles on the
  strip are provisional — expect tweaks as the sections firm up.
- Speaker note on first showing the banner: the administrator's
  *bless* survives "every" — authority enters the system only *as*
  signed evidence (the blessed baseline), never by assertion; scene
  6's laundering beat proves exactly that.

## 1. Preliminaries — slides (4.5 min)

### 1a. Core attestation stack (1.5 min)

One architecture slide: Copland (attestation protocols as terms with an
evidence semantics) → CVM (executes phrases; manifests, ASPs,
appraisal). asp-libs appears as a diagram label on the CVM layer (the
measurement/appraisal primitives: hash, readfile, signature, golden
comparison), not a talking point. Output: **signed evidence bundles**
appraised against **golden baselines**. Include one small Copland
snippet from a real isolette protocol as visual texture — a few lines
at most, not verbose — with the spoken line "you don't need to read
this; you need to know it's a formal object with an evidence
semantics."

### 1b. pybb architecture (2 min)

One workflow diagram: measurements land as blackboard entries; segments
(provision / certify / escalate); the controller cycle evaluates
predicates — which *are* attestation episodes; **knowledge sources**
are repair rungs on outcome-routed chains; failure handoff,
restart-episode, escalation. The one idea to land hard: the **repair
ladder** — a rung's exhaustion is the *diagnosis* that a different
artifact is at fault, and every repair is judged only by
re-measurement. Include a small checklist legend the whole demo reads
through: ✓ attested, ✗ refuted, ? poisoned fail-closed.

### 1c. Artifact classes (1 min)

A single table slide: **model** (blessed, signed), **contract** (named
slices), **implementation**, **proof/verification** — plus the two
cross-cutting classes: **toolchain** (hashed measure-then-use) and
**trust state** (bundles, goldens). Columns follow the class → measured
how → **judged by** → repair species shape (the same shape slide B
reuses, so the audience recognizes it): restore, slice splice,
re-derivation, regeneration-from-model, out-of-band pause, principled
refusal. This table becomes the map the scenes get pinned to. Speaker
note: *this table is deliberately incomplete — the demo will show why*
(the cheat/sysproof/gensrc tiers are slide C's punchline; do not
pre-introduce them here).

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
regeneration-from-model. Close the act with one sentence naming Scenes
9–11 (proof escapes, the hollow system proof, the stale dep cache) —
the AI-in-the-loop capstone's slide C carries that taxonomy in full.

### Coverage beat (30 s)

The scene × artifact-class × repair-species matrix as a spoken line
over Act V's last frame (budget reclaimed for the AI-in-the-loop
capstone), with the 5 shown scenes highlighted and the other 7
one-lined — signals depth without spending runtime.

## 3. Same workflow, other ecosystems — slides (~5 min)

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

### Capstone: "AI in the loop" — three slides (~2.5 min)

The section's payoff beat: the ecosystems bullets establish breadth,
the repair-strategies bullet names the LLM engines, and these slides
zoom out to where AI touches the whole workflow — and where it never
does. Same title across all three, "part 1 / 2 / 3": AI inside the
workflow, AI built the loop, AI attacked the loop. (Budget offsets:
the section-2 coverage slide becomes a spoken line over Act V's last
frame, and Act V's closing nod to scenes 9–11 shrinks to one sentence
since slide C now carries that taxonomy.)

**Slide A — "AI in the loop: untrusted help, measured trust."**
Layout: the lifecycle pipeline across the slide (model → contracts →
implementation → proofs → verification → evidence), each stage
annotated with its AI touchpoint — the last two stages visibly marked
as the AI-free zone.

| Workflow stage | Where AI participates | The rule |
|---|---|---|
| Model / spec | LLMs may draft or restate specs | only the administrator **blesses** — authority is human, AI never signs |
| Implementation | spec-guided synthesis / re-derivation with LLM engines (Rocq demo's `--llm`) | the seed proofs must prove again against the blessed statements |
| Proofs | the repair ladder's engines: deterministic tactic portfolio first, LLM behind it — API-key engines, AutoVerus, desktop agent sessions, the KU Dogtreat repairer | a repair claim is worthless; only fresh measurement re-establishes standing |
| Verification & appraisal | **none — by design** | the judges stay deterministic: the kernel, Verus, appraisal against signed goldens |
| Evidence / trust state | **none — by design** | signature, anchor, derivability; no knowledge source (human or AI) repairs a baseline |

Callout (the slide's one idea): **AI proposes; measurement disposes.**
An LLM's output is just another untrusted artifact — it enters the
same episode and faces the same appraisal as a human edit or a tamper.
The demos are keyless by default with LLM as an opt-in branch: the
workflow's guarantees never depend on the engine being good, honest,
or even present.

Speaker note: the arrow points the other way too — as more lifecycle
artifacts *are* AI-generated, lifecycle attestation is what makes them
trustworthy: provenance and evidence, not provider assurances. Sets up
the close.

**Slide B — "AI in the loop, part 2: AI built the loop."** Setup line:
every layer of this stack was built in Claude desktop and CLI
sessions — and the discipline you've just watched is what made that
safe. Four rows, layer → what AI built → what judged it:

| Layer | AI-built (Claude sessions, git-attested) | Judged by |
|---|---|---|
| pybb | the blackboard/controller/KS framework, both demo arcs, install + CI | scene gates on expected output; every scene aborts loudly on regression |
| ASP primitives (asp-libs, Rust) | **12 new** measurement/appraisal binaries + **7 upgraded** — the cheat scan, batch hashing, the Lean/Rocq/HAMR runners and appraisers, golden-slice extraction | tool hashes measure-then-use; appraisal against signed goldens |
| Copland protocols | **41 provisioned protocol directories** across 5 ecosystems | protocol-config checks at the readiness gate; blessed baselines |
| CVM core | `bpar` parallel execution — in the *verified* VM | **the Rocq proofs had to re-prove** |
| CVM & tooling frontends | usability fixes: explicit `--stdin` mode (+ eager-read fix) in the CVM frontend, `--req_file` request input in copland-evidence-tools, cvm-mcp's re-runnable single-line CVM commands | existing cram tests; the demos' readiness gate |
| Demo tampers (scenes 1–8) | the scripted spec / implementation / proof / golden edits, each crafted — counterexample-style — to exercise one specific blackboard capability (attribution, the ladder, restore grains, refusal) | every scene gates on the expected detection, attribution, and repair |
| Attacks (scenes 9–12) | 6 attack classes discovered in interactive red-team sessions — proof escapes, hollow proofs, stale caches, the unverified foundation | each was green across every existing tier when found; each forced a new measurement capability (→ next slide) |

Kicker (the meta-point, and the bridge back to the thesis): the
provenance is itself attested the ordinary way — `Co-Authored-By:
Claude` trailers in the git history; every count on this slide is
reproducible from `git log` alone. The workflow never asked whether
the author was human or AI, because the author was never an input to
the decision. Close on the banner, verbatim: *every trust decision is
grounded in cryptographic attestation evidence.*

Speaker aside (15 s): cvm-mcp — an AI-built MCP interface so AI agents
can drive attestation, closing the loop. See the
[appendix](#appendix-ai-built-infrastructure-git-attested) for the
full enumeration behind the counts.

**Slide C — "AI in the loop, part 3: AI attacked the loop."** Setup
line: the same interactive sessions red-teamed the stack they built —
and every one of these attacks was **green across every existing
measurement tier** when it was found. Six attack classes, scenes 9–12:

| Attack (scene) | How it succeeded — before | The capability it forced |
|---|---|---|
| **ADMIT** (9.1) — `assume(false)` planted in a bridge file no report target names | outside every measured file and slice; cargo-verus reports the **same success** over the hollow proof | the **cheat tier**: `cheat_scan_verus`, counting the proof-escape constructs Verus's own `--no-cheating` names |
| **SMUGGLE** (9.2) — `external_body` broadcast axiom `ensures false` in the shared foundation crate | body is trusted so it verifies clean; inert until a `broadcast use` — no proof outcome moves | the same construct scan at the staging point, before any proof consumes it |
| **SHRINK** (10.1) — a system-proof module commented out | the smaller crate **still verifies, 0 errors** — the shrink carries no verification signal | the **sysproof tier**: whole-file byte hashes of the system proof crate (`hashfile_many`) |
| **SWAP** (10.2) — a real VC dropped, a trivial `ensures true` added at constant count | outcome unchanged, count unchanged, no escape construct — every semantic detector silent | the same byte tier — **bytes anchor what a proof outcome cannot** |
| **STALE** (11) — a semantic flip in a cached dependency, mtime preserved nanosecond-exact | cargo's mtime-gated cache serves the stale artifact; Verus sits green over a proof **false of the live bytes** | the **gensrc byte anchor** (exposes it) + the content-keyed `--fresh-deps` guard (repairs the evidence) |
| **INVERT** (12) — the heat command flipped in unverified FFI glue behind `external_body` | Verus never reads the body: every proof passes, the escape surface is unchanged | the gensrc anchor over every generated source + repair by regeneration-from-model |

Kicker: **adversarial co-development** — defense-in-depth here wasn't
designed up front; it was *measured into existence*, one successful
attack at a time. Each attack became a new measurement tier, a new ASP,
and a regression-gated demo scene — the attack that succeeded yesterday
is re-run and refuted on every demo run today.

Speaker note: this is also the honest epistemics of the byte tiers —
the escalating lesson of scenes 9→12 is that "verification succeeded"
and "no cheats present" are both weaker claims than "these are the
blessed bytes."

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

## Appendix: AI-built infrastructure (git-attested)

The enumeration behind slide B's counts. Evidence standard: an
artifact is counted as AI-built only if the git commit introducing it
carries a `Co-Authored-By: Claude …` trailer — every figure is
reproducible from `git log` alone, with no reliance on memory. (Some
older ASPs — the Nov 2025 Verus/Rocq runners, `readfile_range_many`,
`run_command_autoverus`, `hamr_readfile_range_many` — may also have
had AI assistance but predate the trailer convention; they are
deliberately *not* counted as new, only as upgraded where a later
Claude commit touched them.)

### pybb (the framework)

Essentially every commit is Claude co-authored: the
blackboard/controller/knowledge-source core (design session preserved
as
[session_2026-07-24_pybb_blackboard_attestation.md](session_2026-07-24_pybb_blackboard_attestation.md)),
both demo arcs (8-scene Rocq, 12-scene isolette), all workflow
drivers, `scripts/install.sh` + CI. The arcs' scripted tampers
(scenes 1–8: spec, implementation, proof, and golden edits — e.g.
diffs D1–D12 in the isolette summary) were designed in the same
sessions, counterexample-style: each crafted to exercise one specific
blackboard capability and gated on its expected detection,
attribution, and repair.

### asp-libs: 12 new Rust ASP binaries (Apr–Aug 2026)

Introduced in Claude co-authored commits, spanning Sonnet 4.5/4.6 →
Fable 5: `cheat_scan_verus` (the scene 9 proof-escape scan),
`hashfile_many` + `hashfile_many_appr` (the sysproof/gensrc batch byte
tiers), `model_slices_appr`, `run_command_lean` +
`run_command_lean_appr`, `run_command_dune` (+ the Rocq
assumptions-audit appraiser), `run_command_hamr` +
`run_command_hamr_appr`, `readfile_marker_range`, `goldenbytes_appr`,
`extract_golden_slice`.

### asp-libs: 7 pre-existing ASPs upgraded

In Claude co-authored commits: `hashfile` (hardware-accelerated
sha256), `hashfile_appr`, `readfile_appr`, `run_command_cargo_verus`
(last-verification-results fix), `run_command_rocq` +
`run_command_rocq_appr` (runner upgrade), `run_command_verus_appr`
(cold-build robustness).

### Copland protocols: 41 provisioned protocol directories

Under `tests/fixtures/`: 8 isolette SysMLv2→Rust tiers (`props`,
`l1a`, `l2`, `verus`, `cheat`, `sysproof`, `gensrc`, `report`) + 4
isolette AADL→Rust + 15 Lean (temp-control, goals, landing-gear ×
`model`/`contracts`/`verification`/`build`/`executable`) + 3 Rocq
temp-control + 4 AADL-Slang temp-control + 3 AADL→Rust temp-control +
2 AutoVerus-related (`autoverus`, `find_max_verus_check`) + 2 tool
gates (`hamr_tools`, `sysml_libs`).

### CVM core (the verified VM)

The `bpar` phased work (Apr–May 2026, Claude co-authored): true
parallel execution via split spawn/collect FFI, PID-namespace
par-handle files, **with the Rocq proofs updated** — AI-assisted
changes to a verified codebase, re-judged by the kernel. Plus frontend
work (`--stdin` mode).

### cvm-mcp

Born in a Claude desktop session on 2026-03-25 ("implement an MCP-like
interface to an existing attestation tool… let AI agents configure and
invoke it"): the MCP server, appraisal dashboard, and the HAMR
report→protocol-dir generator. Doubly on-theme: AI built the interface
by which AI agents drive attestation.

### copland-evidence-tools

Frontend additions in Claude co-authored commits (`--req_file` mode +
test parity).
