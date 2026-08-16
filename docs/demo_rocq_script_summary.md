# `examples/demo_rocq.sh` — what it exercises

An interactive walkthrough of the attestation workflow on the Rocq example
(`temp-control-rocq`), driven end-to-end through `temp_control_rocq.py`.

**At a glance**: eight scenes; seven repair species (whole-file restore,
declaration splice, proof synthesis, implementation re-derivation,
human-out-of-band, regeneration-from-config, principled refusal); three
refusal properties at one gate (signature, anchor, derivability). Keyless by
default — the LLM is an opt-in branch where relevant.

**Running it**: `./examples/demo_rocq.sh` (interactive; `--help` for flags —
`--scenes`, `--drift`, `--repair-strategy`, `--fast --auto` for unattended,
`--restore-tools` recovery). Pinned checkouts: tag `rocq-demo-v2` (this
eight-scene demo), `rocq-demo-v1` (the earlier five-scene version).

## Setup

- Bootstrap provisioning if no blessed baseline exists (`bless_lint`-gated).
- The readiness gate: protocol configuration checks plus verification of
  every **signed golden baseline** before any attestation runs.

## Scene 1 — clean baseline

- One attestation episode over every artifact class: **model** (blessed,
  signed spec files), **contracts** (declaration-named slices),
  **verification** (`dune build` + the kernel's assumptions audit), with the
  rocq/dune toolchain hashed measure-then-use in the same term.
- The per-goal checklist, all green.

## Scene 2 — spec drift: escalate, examine, rule

- A model edit (operator's choice: **benign** bound change, or a **breaking**
  restatement that compiles but refutes a seed proof).
- Detection and escalation with attribution: failed attestation results in
  the terminal, each slice marked **modified** (✗) vs
  **moved, content unchanged** (✓).
- Interactive ruling over the diff (VSCode or terminal): **revert** to
  golden, or **bless** — spec-first sanctioning that re-signs the model only.
- Blessing the breaking change: model/contracts attest clean against the new
  baseline while verification refutes the not-yet-proved obligation; then
  automated **proof repair** (`--repair-proofs`, tactic portfolio) adapts the
  proof, judged by fresh measurement.

## Scene 3 — restore, at two grains

- **Whole-file** (`--immutable-model`): the ruling for automated pipelines —
  model files never drift; a failed hash appraisal is the repair order,
  restore + re-attest **in-session**, no interaction.
- **Slice** (`--repair-granularity slice`): the repair unit is the
  measurement unit — only the violated declaration is spliced back (located
  by **name**, insertion-robust), benign drift elsewhere survives, and the
  model entry ends attested clean *via the contracts refinement* — the
  terminal proof the note survived to re-measurement.

## Scene 4 — verification failure, repair by selectable strategy

- Strategy chosen at the prompt or `--repair-strategy`:
  **portfolio** (deterministic tactic search; no API keys),
  **llm** (LLM engine behind the portfolio — real calls with
  `ANTHROPIC_API_KEY`, keyless dry-run otherwise), or
  **pause** (out-of-band: the episode blocks on a work order, *you* repair
  in another terminal, and only fresh measurement — never your claim —
  re-establishes standing; declining falls through to escalation).
- For the engine strategies: the failure-time checklist names the failing
  contract, with **isolation variants** judging every other proof
  individually; then in-session re-attestation and the archived
  **signed evidence** of the re-measurement (never a re-blessing).

## Scene 5 — baseline tamper: the repair that must refuse

- Three beats, one gate, three attributed refusals: a **flipped byte of
  signed bundle evidence** (record integrity — the signature refutes), a
  **hand-edited installed golden** (installation consistency — the anchor
  refutes, signature silent), and **laundering** — the tampered spec
  re-provisioned into a fully self-consistent contracts bundle, refuted by
  semantic lineage: every slice golden must be *derivable from the blessed
  signed bytes*, and ordinary provisioning cannot refresh the blessing.
- Each stops attestation before it starts — and no knowledge source can
  repair a baseline: the readiness gate's failure chain is empty by design,
  so the only exit is the administrator's out-of-band re-bless.

## Scene 6 — toolchain tamper: measure-then-use catches the tool

- A **functionality-preserving** edit to the rocq wrapper: every build and
  audit still runs and looks fine, but the tool hash — taken in the same
  term, before use — refutes, and every proof cell poisons to `?`
  fail-closed. Readiness still passes: the stored record is coherent; the
  *live* tool drifted.
- Hash-only artifacts are unrepairable from goldens by design: the repair is
  the out-of-band pause rung — you restore the tool, fresh measurement
  re-establishes standing, and a claim without the repair just buys another
  failing measurement. (`--restore-tools` is the recovery hatch: reinstall
  the canonical wrapper, prove it against the blessed golden, confirm
  readiness.)

## Scene 7 — audit tamper: the rendering anchored to config

- The audit file's sections bind to goals only through the file's structure,
  so the **rendering itself is hashed** against its blessed canonical bytes,
  measure-then-use. Beat 1: a deleted `Print Assumptions` line. Beat 2: a
  query **substituted** for a different closed constant — count right, every
  section "Closed", the output check alone fooled; only the byte anchor
  refutes. (The section count stays as depth: it still catches
  config-vs-blessing drift.)
- The repair is the third species — neither restore nor synthesis: the audit
  file is a **rendering of AM configuration**, so the rung re-renders its
  Print block from config and the restarted episode re-attests.

## Scene 8 — implementation tamper: the ladder repairs the right artifact

- The implementation's hot response is inverted: it elaborates fine, but the
  blessed goals are genuinely **false** of it, so no proof can repair this.
  Proof repair exhausts — the exhaustion *is the diagnosis* — and the ladder
  hands off to the impl rung, which **re-derives the implementation from the
  blessed statements alone** (deterministic spec-guided engine, no API keys;
  `--llm` adds the LLM behind it). The seed proofs prove again, the restarted
  episode re-attests, and the proofs end byte-untouched.

## Throughout

- Every scene gates on expected output (including no-✗/no-? checks on clean
  checklists), so regressions — or a dirty starting tree — abort loudly.
- Self-cleaning: the original spec, proofs, and blessing are restored on exit.

Postponed by design: episode-triggering monitor, wall-clock repair timeouts,
the executable artifact class, Rocq `--check`/`--promote`, hashes-only tool
blessing.
