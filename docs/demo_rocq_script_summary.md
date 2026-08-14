# `examples/demo_rocq.sh` — what it exercises

An interactive walkthrough of the attestation workflow on the Rocq example
(`temp-control-rocq`), driven end-to-end through `temp_control_rocq.py`.

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

## Scene 3 — immutable-model policy

- The same drift under `--immutable-model`: a failed model hash appraisal is
  the repair order — restore from golden and re-attest **in-session**, no
  interaction. The policy for automated pipelines where spec drift is never
  tolerated.

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

- The trust state itself is attacked; the live tree stays pristine. Two
  beats against the model baseline: a **flipped byte of signed bundle
  evidence** (the signature refutes) and a **hand-edited installed golden**
  (the anchor to the signed evidence refutes; the signature stays silent).
- Both stop attestation before it starts — and no knowledge source can
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

## Scene 7 — audit coverage tamper: regeneration from config

- One deleted `Print Assumptions` line: every proof still proves, but what
  *provability means* silently shrank — the appraiser's section count fails
  closed and every cell poisons.
- The repair is the third species — neither restore nor synthesis: the audit
  file is a **rendering of AM configuration**, so the rung re-renders its
  Print block from config and the restarted episode re-attests.

## Throughout

- Every scene gates on expected output (including no-✗/no-? checks on clean
  checklists), so regressions — or a dirty starting tree — abort loudly.
- Self-cleaning: the original spec, proofs, and blessing are restored on exit.

Postponed by design: episode-triggering monitor, wall-clock repair timeouts,
the executable artifact class, Rocq `--check`/`--promote`, hashes-only tool
blessing, the implementation-repair ladder scene.
