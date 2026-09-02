# Recording plan — lifecycle-attestation video

Step-by-step runbook for capturing and assembling the video: the
narrated slide sections and the nine demo scenes (seven acts) of the
isolette section. Companion docs:
[video_presentation_outline.md](video_presentation_outline.md) (talk
plan, section/act timings), [video_slide_drafts.md](video_slide_drafts.md)
(slide content, act-transition slides, watch-for lines).

**Model**: no live app-switching. Capture with **QuickTime**, assemble
manually in **iMovie** (decided 2026-08-26; narrated-slides model added
2026-09-02). Two kinds of capture:

- **Slide sections** (framing, preliminaries, isolette intro,
  ecosystems, capstone, close): the presenter steps through the
  full-screen slideshow **narrating live**; QuickTime records screen +
  microphone in one take per section.
- **Demo acts** (the seven isolette acts): one **silent** terminal
  capture per act; act-transition slides dropped in as exported PNG
  stills; voiceover recorded last with iMovie's built-in VO tool
  against the assembled timeline. Act slides appear full-screen 5–10 s
  with VO, then hard-cut to terminal.

(Scripted-ffmpeg assembly was considered and set aside — reproducible
edits, but new tooling; revisit only if many revision rounds or
re-records pile up.)

Every capture is a self-contained **chunk** saved under a fixed name
(see *Recording assets*), so progress survives across days and the
edit can be assembled incrementally.

## Recording assets — layout, naming, progress log

All recording files live under `recordings/` at the repo root
(git-ignored: multi-GB `.mov` files never enter git; only this plan
and the takes log are versioned).

```
recordings/
  takes/      raw QuickTime output, exactly as recorded — never edited in place
  keepers/    one trimmed keeper per chunk (the file iMovie imports)
  slides/     PNG stills exported from PowerPoint (act transitions, cutaways)
  vo/         the timed VO script for the demo acts (iMovie stores the VO audio itself)
  takes.md    progress log — chunk, take #, date/time, keeper?, notes
```

**Chunk naming**: `NN_kind_name_takeK.mov` in `takes/`, where `NN` is
the two-digit timeline position, `kind` is `slides` or `demo`, `name`
is the section/act, `K` is the take number. The keeper copy in
`keepers/` drops the take suffix: `NN_kind_name.mov`. Sorting either
folder by name gives timeline order.

| NN | Chunk file (keeper) | Content | Capture |
|----|---------------------|---------|---------|
| 00 | `00_slides_framing.mov` | §0 framing (banner, roadmap strip) | narrated |
| 01 | `01_slides_prelims.mov` | §1a–1c core stack, pybb, artifact classes | narrated |
| 02 | `02_slides_isolette_intro.mov` | §2 isolette intro slide | narrated |
| 03 | `03_demo_actI.mov` | scene 1 | silent |
| 04 | `04_demo_actII.mov` | scene 3, benign range | silent |
| 05 | `05_demo_actIII.mov` | scene 13 | silent |
| 06 | `06_demo_actIV.mov` | scene 14 | silent |
| 07 | `07_demo_actV.mov` | scene 2 | silent |
| 08 | `08_demo_actVI.mov` | scenes 6+7 | silent |
| 09 | `09_demo_actVII.mov` | scenes 9+12 | silent |
| 10 | `10_slides_ecosystems.mov` | §3 other ecosystems | narrated |
| 11 | `11_slides_capstone.mov` | capstone A/B/C | narrated |
| 12 | `12_slides_close.mov` | §4 close | narrated |

Act-transition stills: `slides/actI.png` … `slides/actVII.png`
(the coverage-beat overlay, if used, is `slides/coverage.png`).

**Progress log** (`recordings/takes.md`): one line per take, appended
as it happens — `chunk | take | date time | keeper? | notes`. A chunk
is *done* when its keeper file exists and the log says so. Nothing
else needs to be remembered between sessions: the keepers folder plus
the log is the whole state.

**Partial-progress rules**

- Record chunks in any order; `NN` fixes the timeline order later.
- A retake replaces only that chunk's keeper; the raw takes stay in
  `takes/` until the final export is approved, then may be deleted.
- Keep the iMovie library on the same internal disk (default
  `~/Movies/iMovie Library.imovielibrary`); iMovie saves continuously,
  there is no Save command.
- Import keepers into iMovie in timeline order as they become
  available — the timeline can be built across several sessions, and
  a re-recorded keeper is swapped by deleting the old clip from the
  timeline and dragging in the new file.

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
6. Create the folders: `mkdir -p recordings/{takes,keepers,slides,vo}`
   and an empty `recordings/takes.md` with the header line.
7. **Dry run (once, before the first real take)** — three short tests
   that exercise every tool feature used below:
   - *Test A, narrated slides*: record 2–3 slides with the mic per
     Phase 2b, saying "mark" on the first and last slide. Play back
     in QuickTime: level, fan/room noise, text sharpness, no cursor.
   - *Test B, silent demo*: record one short scene per Phase 2 with
     Microphone → None.
   - *Test C, iMovie round trip*: new project, import A first, then
     B; confirm resolution (Phase 4 step 3); try Crop to Fill on
     whichever clip shows bars; record 20 s of voiceover over B;
     scrub to the end of A and confirm the final "mark" still lands
     on the last slide; export 1080p and watch it.
   Pass = clean audio, crisp text, sync holds, export plays. Fix the
   capture settings before recording anything real.

## Phase 1 — capture environment (once, recording day)

8. Terminal: dark high-contrast theme; font 18–20 pt (the ✓/✗/?
   glyphs must read on a phone); window sized to clean 16:9; prompt
   stripped to `$ ` (no user/hostname); shell history/autosuggest
   noise off.
9. VSCode (for the diff beats): font bumped to match, same theme
   family, window pre-positioned so `[v]iew diff` opens on top of the
   terminal frame without resizing.
10. **Microphone check** (narrated chunks only): System Settings ▸
    Sound ▸ Input tab ▸ select **MacBook Pro Microphone** (never the
    "Microsoft Teams Audio Device" virtual input, which also appears
    in every mic list). Speak normally; the Input level meter should
    bounce around the middle — adjust the Input volume slider if it
    barely moves or pegs right. Optional listen test: QuickTime
    Player ▸ File ▸ New Audio Recording ▸ pick the mic from the
    small ▾ next to the record button ▸ record 10 s ▸ play back;
    this is the fastest way to hear fan or room noise.
11. Recorder: QuickTime screen recording via ⌘⇧5 — records at native
    Retina resolution (3024×1964 on this machine), so terminal text
    stays tack-sharp. QuickTime records variable frame rate; iMovie
    (same Apple ecosystem) conforms it cleanly, so no ramp-test
    needed. **First-time permissions**: macOS prompts for Screen
    Recording and Microphone access on first use; approve under
    System Settings ▸ Privacy & Security ▸ Screen Recording /
    Microphone, then restart the recording. A silent take almost
    always means the Microphone permission or the wrong input.
12. Do-not-disturb on; notifications off; Spotlight/Dock hidden.

### QuickTime screen-recording — click sequence

Used by every capture below.

- **a.** Press **⌘⇧5**. A toolbar appears at the bottom of the screen
  with five mode icons and an *Options* menu. The first three icons
  are screenshot modes; the last two (small ● badge) are **Record
  Entire Screen** and **Record Selected Portion**.
- **b.** Click a **recording** mode first. *Options* only shows the
  Microphone section when a recording mode is selected.
- **c.** Click **Options** and set:
  - *Save to* → `recordings/takes` (choose *Other Location…* once;
    it is remembered).
  - *Timer* → None.
  - *Microphone* → **MacBook Pro Microphone** (narrated chunk) or
    **None** (demo chunk).
  - *Show Mouse Clicks* → off. *Show Floating Thumbnail* → off (the
    thumbnail can land in the next take).
  - *Remember Last Selection* → on (keeps the selected-portion frame
    between takes).
- **d.** For *Record Selected Portion*, drag the dashed frame's
  corner handles over the area to capture; for *Record Entire
  Screen*, no frame is needed.
- **e.** Click **Record** (selected portion) or click anywhere on the
  screen (entire screen). Recording is live immediately.
- **f.** To stop: click the **■** icon that appears in the menu bar
  at the top of the screen, or press **⌃⌘Esc**. The file lands in
  *Save to* as `Screen Recording <date> at <time>.mov`.
- **g.** Rename the file immediately to its chunk name with the take
  number (`04_demo_actII_take1.mov`) and append a line to
  `recordings/takes.md`.

## Phase 2 — demo captures (one take per act; retakes are cheap)

General rules for every demo take:

- Microphone → **None** (VO comes later in iMovie). Record the
  **entire screen**; crop in edit.
- Start the recorder, then run the invocation. Leave ~3 s of quiet
  terminal before and after the scene for edit handles.
- Drive prompts **manually** (no `--auto`): the `[v]iew diff / Enter`
  and ruling prompts are the narration beats. Dwell 3–5 s on every
  checklist frame — the audience reads slower than the operator.
- On any unexpected output (a stray ✗, an abort): stop, let the
  driver's self-clean run, rerun readiness, retake. Never splice
  output across runs.
- Log each take in `recordings/takes.md`: chunk, take #, wall-clock,
  keeper?, notes.

Per-act script:

13. **Act I — scene 1** (`03_demo_actI`):
    `./examples/demo_isolette.sh --scenes 1`.
    Beats: readiness gate green → one full episode → the per-crate
    checklist all green. Dwell on the final checklist (this is the
    frame every later refusal gets compared against).
14. **Act II — scene 3, benign range** (`04_demo_actII`, single take):
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
15. **Act III — scene 13, benign impl drift** (`05_demo_actIII`):
    `./examples/demo_isolette.sh --scenes 13`.
    Beats: the equivalent guard rewrite (take the `[v]`iew — the
    x>y → y<x diff) → l1a hash moves → the files entry passes via the
    l2 refinement (slices intact) → the `contracts` (l1b marker) entry
    stays clean → the confirmation chain **re-verifies** the rewrite
    green. No restore — the benign change survives. Short take, no
    codegen. The implementation-class mirror of Act II.
16. **Act IV — scene 14, contract-launder** (`06_demo_actIV`):
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
17. **Act V — scene 2, breaking impl (the ladder)** (`07_demo_actV`):
    `./examples/demo_isolette.sh --scenes 2`.
    Beats: the dummy-bad-impl diff (take the `[v]`iew — VSCode diff
    D1) → contracts-intact rung exhausts → impl rung restores
    crate-scoped → restart → re-attested clean. The breaking
    counterpart to Act III.
18. **Act VI — scenes 6+7, trust-state + toolchain** (`08_demo_actVI`):
    `./examples/demo_isolette.sh --scenes "6 7"`.
    Scene 6 beats: three tampers, three attributed refusals
    (signature → anchor → derivability); optionally one trust-state
    diff on camera (the flipped evidence byte, pretty-printed). Scene
    7 beats: the wrapper edit (take the `[v]`iew, diff D10) →
    readiness still passes → the tool hash refutes and **every proof
    cell poisons to `?`** — dwell; the act's money shot →
    `--restore-tools` recovery mentioned in VO, not shown.
19. **Act VII — scenes 9 + 12, the detector escalation**
    (`09_demo_actVII`): `./examples/demo_isolette.sh --scenes "9 12"`.
    - Beat 1 (scene 9, axioms): for each of ADMIT and SMUGGLE — take
      the `[v]`iew of the innocent-looking diff, then the two-grid
      view (verus grid all ✓ beside the proof-escape grid refusing the
      exact crate: `assume 0 → 1`; `broadcast 0 → 1, external_body
      0 → 1`) — dwell here, the construct annotation is the point —
      then the full episode where the byte anchor also refuses and the
      diagnosis rung correlates them. The **cheat scan** catches what
      the outcome cannot.
    - Beat 2 (scene 12, FFI): the inverted-FFI diff (diff D18 — "see
      how innocent it looks") → every proof passes *and the cheat scan
      is silent* → only the **gensrc byte anchor** refuses, naming the
      file → diagnosis → repair by regeneration (real codegen —
      speed-ramp stretch) → re-attested clean.
    VO through-line: three detectors, three blind spots — outcome
    (blind to both), construct scan (beat 1), byte anchor (beat 2).
    The final clean checklist doubles as the coverage beat's
    background frame.

## Phase 2b — narrated slide captures (one take per section)

Chunks 00–02 and 10–12. The presenter narrates live while stepping
through the slideshow; audio and video land in the same `.mov`.

20. **Slideshow setup**: open the deck in PowerPoint. Slide Show ▸
    *Play from Start* once to confirm the display shows plain slides,
    not Presenter View (single-display Macs may default either way;
    if Presenter View appears, Slide Show ▸ *Presenter View* toggles
    it off, or use the *Use Slide Show* button inside Presenter View).
    Press Esc. Navigate to the section's first slide so *Play from
    Current Slide* (⌘⇧↩) starts there.
21. **Frame the capture**: ⌘⇧5 ▸ **Record Selected Portion** ▸ drag
    the dashed frame to cover exactly the slide area (the display is
    16:10, so a full-screen 16:9 slideshow has black bars top and
    bottom; framing to the slide removes them at the source). With
    *Remember Last Selection* on, the frame persists across sections.
    Fallback if the frame is fiddly: *Record Entire Screen* and use
    iMovie's Crop to Fill (Phase 4 step 5).
22. **Options**: Microphone → **MacBook Pro Microphone**; Show Mouse
    Clicks off; Save to `recordings/takes`.
23. **Take**: click Record ▸ start the slideshow from the current
    slide ▸ say **"mark"** before the first line of narration ▸
    narrate, advancing with **→ / space only** (no mouse — PowerPoint
    hides the pointer after a few seconds, a mouse move brings it
    back) ▸ on the section's last slide say **"mark"** again ▸ pause
    2 s ▸ stop from the menu bar ■. The two marks are the sync check
    in the edit and the trim points.
24. **Rules**: one take per section; on a fumble, stop and retake the
    whole section (2–5 min each — cheaper than an audio splice).
    Rename and log the take (click-sequence step g). Play the take
    back once in QuickTime before moving on: level, noise, no
    notification, no cursor.
25. **Fallback for a single bad slide**: PowerPoint's Slide Show ▸
    *Record Slide Show* records narration per slide and File ▸ Export
    ▸ MP4 produces a video with the recorded timings; use it only if
    a section refuses to come out clean in one QuickTime pass, and
    treat its output as that section's keeper.

## Phase 3 — keeper prep (QuickTime) + slide stills

26. Per keeper take, in QuickTime Player (double-click the `.mov`):
    - **Trim** the handles: Edit ▸ *Trim* (⌘T) shows the yellow
      trim bar; drag the left and right handles to the in/out points
      (for narrated chunks: just before the first "mark" is spoken
      and just after the second; for demo chunks: the ~3 s quiet
      handles); the frame thumbnails and the audio waveform under
      them show where speech starts. Click **Trim**.
    - **Single fumble** (demo chunks only): move the playhead to the
      start of the fumble, Edit ▸ *Split Clip* (⌘Y), move to the end,
      ⌘Y again, click the middle segment, press Delete. Only if the
      join lands in a static stretch of terminal; otherwise retake.
      Never do this on a narrated chunk — the audio cut is audible.
    - **Save**: File ▸ *Export As* ▸ *4K* (keeps native resolution —
      *Save* would overwrite the raw take) into `recordings/keepers/`
      under the keeper name (`04_demo_actII.mov`). Mark the take as
      keeper in `recordings/takes.md`.
27. Optional pacing check before opening iMovie: open the first
    keeper, Edit ▸ *Add Clip to End* for each following keeper, and
    eyeball total runtime against the budgets (~13 min demo section,
    ~20 min total). Do not save this concatenation.
28. Export the act-transition slides (and any other cutaways) from
    PowerPoint: File ▸ Export ▸ File Format *PNG* ▸ *Save Every
    Slide* into a scratch folder, then copy the seven act slides into
    `recordings/slides/` as `actI.png` … `actVII.png`.

## Phase 4 — assembly (iMovie)

Build incrementally: the timeline can be extended in any session as
new keepers appear, and iMovie saves automatically.

29. **Project**: open iMovie ▸ *Projects* ▸ **Create New** ▸ *Movie*.
    File ▸ *Rename* the project `pybb-lifecycle-video`.
30. **First import**: click **Import Media** (↓ arrow on the toolbar)
    ▸ navigate to `recordings/keepers/` ▸ select the keeper(s) ▸
    **Import Selected**. Drag the first keeper from the *My Media*
    browser into the empty timeline. iMovie takes the project
    resolution from the **first clip added**, so this must be a
    full-resolution screen capture, never a PNG still or a 720p test.
31. **Confirm resolution**: File ▸ *Share* ▸ *File*. The *Resolution*
    dropdown's largest entry is the project resolution — it should
    offer **4K**; the summary at the top of the dialog shows the
    dimensions. If the top choice is 720p or 1080p, the first clip
    was wrong: File ▸ *Delete Project*, create a new one, and start
    with a keeper. Click *Cancel*.
32. **Build in timeline order**, chunk by chunk:
    narrated slides keeper → act-slide PNG (select it in *My Media*,
    drag to the timeline, then *Clip ▸ Adjust Clip Duration* or drag
    its right edge to ~8 s) → demo keeper → next act slide → … .
    A PNG dropped in the timeline gets an automatic Ken Burns pan:
    select the still, click the **Crop** button (⌘K or the crop icon
    above the viewer), choose **Fit**, and click ✓ so it stays static.
    Never cut between different runs' output; a visible take is one
    run.
33. **Bars/aspect**: if a full-screen capture shows black bars in the
    viewer, select the clip ▸ Crop button ▸ **Crop to Fill** ▸ drag
    the frame over the slide/terminal area ▸ ✓. For narrated chunks
    recorded as selected portions this step is unnecessary.
34. **Speed stretches** (Act II promote, Act VII regeneration — the
    two real-codegen acts): move the playhead to the codegen start,
    Modify ▸ *Split Clip* (⌘B); move to its end, ⌘B again; select the
    middle clip ▸ click the **Speed** button (speedometer icon above
    the viewer) ▸ *Fast* ▸ pick 8× or choose *Custom* and type a
    factor. Then overlay the honesty label: **Titles** tab ▸ drag
    *Lower Third* onto the sped-up clip so it sits above it in the
    timeline ▸ double-click the title text in the viewer and type
    "HAMR codegen — Ns, shown at M×" (N from the keeper's real
    duration: Finder ⌘I on the keeper file, or the clip's duration in
    iMovie before speeding).
35. **Trim dwell** to final pacing: drag clip edges in the timeline,
    or move the playhead and ⌘B to split and delete a stretch. Act
    budgets (min): I 1.25 · II 1.75 · III 1.25 · IV 1.75 · V 1.5 ·
    VI 2.25 · VII 1.75 (+15 s coverage beat over Act VII's last frame).
36. **Sync check on every narrated clip**: place the playhead at the
    clip's end, press Space, and confirm the second spoken "mark"
    lands while the section's last slide is on screen. If it drifts,
    the raw take is at fault (VFR edge case): re-export the keeper
    from QuickTime and re-import; do not stretch audio in iMovie.
37. **Voiceover** (demo acts): place the playhead where the narration
    starts, press **V** (or click the microphone icon under the
    viewer). Click the ▾/options control next to the record button
    and set the input to **MacBook Pro Microphone**, mute project
    audio on. Press the red button; a 3-2-1 countdown runs; speak
    from the VO script in `recordings/vo/`; press Space to stop. The
    take appears as a detached green audio clip under the video —
    drag to nudge, or select and Delete to redo that span. Record
    one act at a time; there is no punch-in.
38. **Swapping a re-recorded keeper**: import the new keeper, select
    the old clip in the timeline, Delete, drag the new one into the
    gap; re-check step 36 for narrated chunks and re-place any
    voiceover that was under a demo clip.
39. **Export**: File ▸ *Share* ▸ *File*. *Format* Video and Audio;
    *Resolution* **1080p** for review passes and direct sharing
    (fast export, a few hundred MB for 20 min); *Quality* High;
    *Compress* Better Quality. **4K** once, for the final platform
    upload only (YouTube gives 4K uploads a higher bitrate, which
    keeps monospace glyphs crisp; the file is several GB and exports
    several times slower). Click *Next…*, save into
    `recordings/exports/` as `pybb-lifecycle-video_<date>_<res>.mp4`.
    Watch the export end-to-end once before calling it done; verify
    runtime against the section budgets.

## Division of labor

- **Operator (manual)**: captures, keeper selection and trims, iMovie
  assembly, VO recording, final watch-through.
- **Claude (support)**: pre-flight checklists and stat re-verification
  (Phases 0–1); maintaining `recordings/takes.md` and checking the
  keepers folder against the chunk table (names, gaps, durations —
  readable via Spotlight metadata, no extra tooling); honesty-label
  arithmetic from keeper-file durations; the timed VO script drafted
  against keeper durations; the edit's paper trail (takes, trims,
  labels) kept in the repo; export verification (resolution /
  duration / size vs. budgets).

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
- Fumbled narration on a slide section → retake the section; never
  splice audio.
- Any output that surprises the operator → investigate before
  re-recording; a surprise on camera is either a regression or a
  missed rehearsal.
