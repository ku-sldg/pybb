# Recording plan — isolette demo section (video presentation)

Step-by-step runbook for capturing the six demo scenes (five acts) of
the lifecycle-attestation video. Companion docs:
[video_presentation_outline.md](video_presentation_outline.md) (talk
plan, act timings), [video_slide_drafts.md](video_slide_drafts.md)
(act-transition slides, watch-for lines).

**Model**: no live app-switching. Three material tracks recorded
separately — (1) the slide track, (2) one terminal capture per
scene-set, (3) voiceover recorded last against the edit. Act slides
appear full-screen 5–10 s with VO, then hard-cut to terminal.

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
8. Recorder: QuickTime screen recording at 1080p minimum (4K
   preferred — terminal text survives compression better). Record the
   full display, crop in edit. No microphone on the capture track
   (VO comes later).
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
    frame Act IV/V refusals get compared against).
11. **Act II — scene 3 (breaking)**:
    `./examples/demo_isolette.sh --scenes 3 --drift breaking`.
    Beats: the drifted episode escalates with slice attribution → the
    ruling diff (golden vs. proposed — always shown; linger) → bless
    (`--bless-props` path) → **promote** (real codegen; this is the
    1–2 min stretch to speed-ramp in edit — keep the take rolling) →
    gold moves → the episode against the new baseline reports the
    Verus tier RED (mhs + sys_nominal_proof). End on the honest-RED
    checklist.
12. **Act III — scene 2**: `./examples/demo_isolette.sh --scenes 2`.
    Beats: the dummy-bad-impl diff (take the `[v]`iew — VSCode diff
    D1 on camera) → contracts-intact rung exhausts → impl rung
    restores crate-scoped → restart → re-attested clean.
13. **Act IV — scenes 6+7**:
    `./examples/demo_isolette.sh --scenes "6 7"`.
    Scene 6 beats: three tampers, three attributed refusals
    (signature → anchor → derivability); optionally one trust-state
    diff on camera (the flipped evidence byte, pretty-printed). Scene
    7 beats: the wrapper edit (take the `[v]`iew, diff D10) →
    readiness still passes → the tool hash refutes and **every proof
    cell poisons to `?`** — dwell on that frame; it is the act's
    money shot → `--restore-tools` recovery mentioned in VO, not
    shown.
14. **Act V — scene 12**: `./examples/demo_isolette.sh --scenes 12`.
    Beats: the inverted-FFI diff (take the `[v]`iew, diff D18 — "see
    how innocent it looks") → every proof passes, cheat scan silent →
    the gensrc byte anchor refuses, naming the file → diagnosis rung
    classifies the drift → repair by regeneration (real codegen —
    second speed-ramp stretch) → re-attested clean. The final clean
    checklist doubles as the coverage beat's background frame.

## Phase 3 — slide track

15. Export the deck (act-transition slides + all others) as images,
    or screen-record the deck full-screen paging at a steady pace.
    The act slides need only ~10 s each of static hold.

## Phase 4 — edit assembly

16. Assemble per act: act slide (5–10 s) → terminal capture →
    (repeat). Speed-ramp the two codegen stretches (Act II promote,
    Act V regeneration) with an on-screen honesty label
    ("HAMR codegen — Ns, shown at M×"). Never cut between different
    runs' output; a visible take is one run.
17. Trim dwell to final pacing against the act budgets: I 1.25 ·
    II 2.25 · III 1.5 · IV 2.5 · V 1.75 (+15 s coverage beat over
    Act V's last frame).
18. Write the VO script from the act slides' watch-for lines plus the
    scene beats above; record VO against the locked edit; mix.

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
