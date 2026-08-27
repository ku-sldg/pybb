# Recording plan — isolette demo section (video presentation)

Step-by-step runbook for capturing the six demo scenes (five acts) of
the lifecycle-attestation video. Companion docs:
[video_presentation_outline.md](video_presentation_outline.md) (talk
plan, act timings), [video_slide_drafts.md](video_slide_drafts.md)
(act-transition slides, watch-for lines).

**Model**: no live app-switching. Capture with **QuickTime**, assemble
manually in **iMovie** (decided 2026-08-26): one terminal capture per
scene-set, act slides dropped in as exported PNG stills, voiceover
recorded last with iMovie's built-in VO tool against the assembled
timeline. Act slides appear full-screen 5–10 s with VO, then hard-cut
to terminal. (Scripted-ffmpeg assembly was considered and set aside —
reproducible edits, but new tooling; revisit only if many revision
rounds or re-records pile up.)

## Phase 0 — machine prep (once, day before)

1. Bring the stack current: `scripts/install.sh` state up to date;
   both demo arcs at a passing readiness gate.
2. `git status` clean in `targets/isolette-microkit` (scene 3's
   promote requires a git-clean tree and restores through git).
3. Warm the cargo-verus caches: one full gated-clean run
   (`./examples/demo_isolette.sh --scenes 1 --fast --auto`) so verus
   tiers run at warm speed (~0.7 s/crate) on camera.
4. Re-verify the intro-slide stats against live goldens (13 files, 67
   slices, 8 crates, 1,862 obligations, 30 tool/dep files) — they are
   provision-dependent.
5. Confirm the recovery hatches work: `--restore-tools`, and the
   drivers' self-cleaning on exit (run a scene, ctrl-C mid-way, rerun
   readiness).

## Phase 1 — capture environment (once, recording day)

6. Terminal: dark high-contrast theme; font 18–20 pt (the ✓/✗/?
   glyphs must read on a phone); window sized to clean 16:9; prompt
   stripped to `$ ` (no user/hostname); shell history/autosuggest
   noise off.
7. VSCode (for the diff beats): font bumped to match, same theme
   family, window pre-positioned so `[v]iew diff` opens on top of the
   terminal frame without resizing.
8. Recorder: QuickTime screen recording (⌘⇧5) — records at native
   Retina resolution, so terminal text stays tack-sharp. Record the
   full display, crop in edit. No microphone on the capture track
   (VO comes later in iMovie). QuickTime records variable frame rate;
   iMovie (same Apple ecosystem) conforms it cleanly, so no ramp-test
   needed.
9. Do-not-disturb on; notifications off; spotlight/dock hidden.

## Phase 2 — captures (one take per act; retakes are cheap)

General rules for every take:

- Start the recorder, then run the invocation. Leave ~3 s of quiet
  terminal before and after the scene for edit handles.
- Drive prompts **manually** (no `--auto`): the `[v]iew diff / Enter`
  and ruling prompts are the narration beats. Dwell 3–5 s on every
  checklist frame — the audience reads slower than the operator.
- On any unexpected output (a stray ✗, an abort): stop, let the
  driver's self-clean run, rerun readiness, retake. Never splice
  output across runs.
- Log each take in a scratch sheet: act, take #, wall-clock, keeper?

Per-act script:

10. **Act I — scene 1**: `./examples/demo_isolette.sh --scenes 1`.
    Beats: readiness gate green → one full episode → the per-crate
    checklist all green. Dwell on the final checklist (this is the
    frame every later refusal gets compared against).
11. **Act II — scene 3, benign range** (single take):
    `./examples/demo_isolette.sh --scenes 3 --drift range`.
    Beats: the Table A-12 ceiling widened 102 → 103 in the shared
    library constant → model appraisal fails anyway, attributed to the
    `gumbo_library` slice with everything else green (dwell — this is
    the "sanction, not semantics" frame) → ruling diff → rule
    **bless** → spec-first green episode → **promote** (real codegen;
    speed-ramp stretch — keep rolling) → the fresh episode re-proves
    **all green**; the offered diff shows the regenerated
    shared-library constant. End on the all-green checklist. (The
    breaking-spec take is retired from Act II — breaking now lives in
    Acts IV and V.)
12. **Act III — scene 13, benign impl drift**:
    `./examples/demo_isolette.sh --scenes 13`.
    Beats: the equivalent guard rewrite (take the `[v]`iew — the
    x>y → y<x diff) → l1a hash moves → the files entry passes via the
    l2 refinement (slices intact) → the `contracts` (l1b marker) entry
    stays clean → the confirmation chain **re-verifies** the rewrite
    green. No restore — the benign change survives. Short take, no
    codegen. The implementation-class mirror of Act II.
13. **Act IV — scene 14, contract-launder**:
    `./examples/demo_isolette.sh --scenes 14`.
    Beats: the laundering diff (take the `[v]`iew — weakened REQ_MHS_2
    ensures + inverted impl; "self-consistent, verus passes") →
    cargo-verus SUCCEEDS → the **l1b marker tier refuses** (the report
    slices miss `compute_cases`; only the marker byte anchor sees it)
    → the marker rung splices the golden contract block back → the
    restored true contract **refutes the inverted impl**: end on the
    exposed Verus refusal (`verus_targ` Appraisal was not successful).
    **Do not drive to green** — the exposure IS the beat (impl repair
    is Act V). Codegen-free.
14. **Act V — scene 2, breaking impl (the ladder)**:
    `./examples/demo_isolette.sh --scenes 2`.
    Beats: the dummy-bad-impl diff (take the `[v]`iew — VSCode diff
    D1) → contracts-intact rung exhausts → impl rung restores
    crate-scoped → restart → re-attested clean. The breaking
    counterpart to Act III.
15. **Act VI — scenes 6+7, trust-state + toolchain**:
    `./examples/demo_isolette.sh --scenes "6 7"`.
    Scene 6 beats: three tampers, three attributed refusals
    (signature → anchor → derivability); optionally one trust-state
    diff on camera (the flipped evidence byte, pretty-printed). Scene
    7 beats: the wrapper edit (take the `[v]`iew, diff D10) →
    readiness still passes → the tool hash refutes and **every proof
    cell poisons to `?`** — dwell; the act's money shot →
    `--restore-tools` recovery mentioned in VO, not shown.
16. **Act VII — scene 12, unverified foundation**:
    `./examples/demo_isolette.sh --scenes 12`.
    Beats: the inverted-FFI diff (take the `[v]`iew, diff D18 — "see
    how innocent it looks") → every proof passes, cheat scan silent →
    the gensrc byte anchor refuses, naming the file → diagnosis rung
    classifies the drift → repair by regeneration (real codegen —
    speed-ramp stretch) → re-attested clean. The final clean checklist
    doubles as the coverage beat's background frame.

## Phase 3 — keeper prep (QuickTime) + slide stills

17. Per keeper take, in QuickTime: trim the ~3 s handles (⌘T); a
    single fumble may be cut by splitting at the playhead (⌘Y) and
    deleting the segment — only if the join lands in a static stretch,
    otherwise retake. Save trimmed keepers to `recordings/keepers/`
    with the act naming (`actIV_keeper.mov`, …).
18. Optional pacing check before opening iMovie: Edit ▸ Add Clip to
    End to rough-concatenate the seven acts and eyeball total runtime
    against the ~13 min section budget.
19. Export the act-transition slides (and any other cutaways) from
    PowerPoint via File ▸ Export ▸ PNG into `recordings/slides/`.

## Phase 4 — assembly (iMovie)

20. New project; drop a full-resolution capture in FIRST so the
    project adopts native resolution (not 720p).
21. Build act by act: act-slide PNG (duration ~8 s) → keeper clip →
    next act slide → … Never cut between different runs' output; a
    visible take is one run.
22. Speed stretches (Act II promote, Act VII regeneration — the two
    real-codegen acts): blade the codegen range into its own clip
    (⌘B), then Speed ▸ Fast (8× preset or custom). Overlay a
    Lower-Third title as the honesty label ("HAMR codegen — Ns, shown
    at M×" — N computed from the keeper's real duration, not
    estimated).
23. Trim dwell to final pacing against the act budgets: I 1.25 ·
    II 1.75 · III 1.25 · IV 1.75 · V 1.5 · VI 2.25 · VII 1.75 (+15 s
    coverage beat over Act VII's last frame).
24. VO: record with iMovie's built-in voiceover tool against the
    assembled timeline, from the VO script (watch-for lines + the
    per-act beats above).
25. Export File ▸ Share ▸ File at project resolution; watch the
    export end-to-end once before calling it done; verify runtime
    against the act budgets.

## Division of labor

- **Operator (manual)**: captures, keeper selection and trims, iMovie
  assembly, VO recording, final watch-through.
- **Claude (support)**: pre-flight checklists and stat re-verification
  (Phases 0–1); honesty-label arithmetic from keeper-file durations
  (readable via Spotlight metadata — no extra tooling); the timed VO
  script drafted against keeper durations; the edit's paper trail
  (takes, trims, labels) kept in the repo; export verification
  (resolution / duration / size vs. budgets).

## Honesty conventions

- Sped-up segments are always labeled with real elapsed time.
- All output shown comes from the take being shown.
- The recovery hatches (`--restore-tools`, self-cleaning) may be
  described in VO without being shown, but nothing shown is staged
  beyond the drivers' own scripted tampers.

## Retake / abort criteria

- Dirty starting tree or readiness failure at take start → fix,
  don't record around it (the scene gates will abort loudly anyway).
- Wrong dwell or fumbled prompt → retake the scene (takes are 1–4 min;
  retakes are cheaper than rescue edits).
- Any output that surprises the operator → investigate before
  re-recording; a surprise on camera is either a regression or a
  missed rehearsal.
