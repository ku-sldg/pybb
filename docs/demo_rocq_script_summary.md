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

## Scene 4 — verification failure and repair

- A corrupted seed proof: the failure-time checklist names the failing
  contract with its diagnostic, and **isolation variants** judge every other
  proof individually (per-goal ✓/✗ from one proofs file, instead of unknowns).
- Tactic-portfolio repair, in-session re-attestation, and the archived
  **signed evidence** of the re-measurement (never a re-blessing).

## Throughout

- Every scene gates on expected output (including no-✗/no-? checks on clean
  checklists), so regressions — or a dirty starting tree — abort loudly.
- Self-cleaning: the original spec, proofs, and blessing are restored on exit.

Postponed by design: episode-triggering monitor, wall-clock repair timeouts,
the executable artifact class, LLM/pause repair-strategy variants, Rocq
`--check`/`--promote`, hashes-only tool blessing.
