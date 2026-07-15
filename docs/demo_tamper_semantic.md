# Demo: semantic tamper detected across a three-tier attestation ladder

*Captured 2026-07-06 from `./examples/run_full_workflow.sh --tamper-semantic`
on the `attestation-integration` branch of pybb.*

This demo corrupts the **meaning** (not just the text) of a GUMBO contract
oracle in a HAMR-generated system, then lets the pybb blackboard drive a
three-tier attestation ladder over it. Each tier is a Copland protocol
executed by the CVM with asp-libs ASPs; no knowledge source calls another —
escalation emerges from blackboard state:

| tier | protocol | measures | cost |
|---|---|---|---|
| 1 | `gumbo_l1` | whole-file SHA-256 of 4 "do not edit" artifacts | ~1 s |
| 2 | `gumbo_l2` | 28 per-contract line ranges / marker blocks | ~1 s (on tier-1 fail) |
| 3 | `gumbo_validation` | live `sireum proyek tipe` / `logika` / `test` | ~77 s (on tier-2 fail) |

## The tamper

One enum flip inside the TempControl GumboX oracle
(`TempControlPeriodic_p_tcproc_tempControl_GumboX.scala`, line 119 — inside
the provisioned measurement range 113–120):

```scala
// guarantee: when current temp < set point, the fan must be off
api_currentTemp.degrees < api_setPoint.low.degrees __>:
  latestFanCmd == CoolingFan.FanCmd.Off &&      // ← flipped to FanCmd.On
    api_fanCmd == CoolingFan.FanCmd.Off
```

The mutation is type-correct Scala, so it survives type checking — and, more
interestingly, it survives formal verification (see "How to read the result"
below). The file is backed up before and restored after the run.

## Blackboard audit trail

Every attestation action is a timestamped entry on the blackboard
(`conf=0.0` marks a failed appraisal). This is the run's full history,
verbatim — note the two escalation entries: no code path connects the tiers,
each `EscalationKS` guard simply observed a failed verdict:

```
20:37:31  conf=1.0  main             attestation.request/gumbo_l1
20:37:32  conf=1.0  AttestationKS    attestation.evidence/gumbo_l1
20:37:32  conf=1.0  AppraisalKS      attestation.component/gumbo_l1/sig
20:37:32  conf=1.0  AppraisalKS      attestation.component/gumbo_l1/tempcontrolsystem_targ
20:37:32  conf=1.0  AppraisalKS      attestation.component/gumbo_l1/tempsensor_targ
20:37:32  conf=0.0  AppraisalKS      attestation.component/gumbo_l1/tempcontrolperiodic_p_tcproc_tempcontrol_gumbox_targ
20:37:32  conf=1.0  AppraisalKS      attestation.component/gumbo_l1/tempsensorperiodic_p_tcproc_tempsensor_gumbox_targ
20:37:32  conf=0.0  AppraisalKS      attestation.verdict/gumbo_l1
20:37:32  conf=1.0  EscalationKS_l1_l2 attestation.request/gumbo_l2
20:37:32  conf=1.0  AttestationKS    attestation.evidence/gumbo_l2
          ... 27 passing gumbo_l2 component entries elided ...
20:37:32  conf=0.0  AppraisalKS      attestation.component/gumbo_l2/tc_gumbox_113_120_targ
20:37:32  conf=0.0  AppraisalKS      attestation.verdict/gumbo_l2
20:37:32  conf=1.0  EscalationKS_l2_validation attestation.request/gumbo_validation
20:38:49  conf=1.0  AttestationKS    attestation.evidence/gumbo_validation
20:38:49  conf=1.0  AppraisalKS      attestation.component/gumbo_validation/proyek tipe slang
20:38:49  conf=1.0  AppraisalKS      attestation.component/gumbo_validation/proyek logika TempControlPeriodic_p_tcproc_tempControl_GumboX.scala
20:38:49  conf=1.0  AppraisalKS      attestation.component/gumbo_validation/proyek logika TempSensorPeriodic_p_tcproc_tempSensor_GumboX.scala
20:38:49  conf=0.0  AppraisalKS      attestation.component/gumbo_validation/proyek test TempControlPeriodic_p_tcproc_tempControl_GumboX_UnitTests
20:38:49  conf=1.0  AppraisalKS      attestation.component/gumbo_validation/proyek test TempSensorPeriodic_p_tcproc_tempSensor_GumboX_UnitTests
20:38:49  conf=0.0  AppraisalKS      attestation.verdict/gumbo_validation
20:38:49  conf=0.0  TrustDecisionKS  attestation.hypothesis
```

(10 controller cycles total; the 77-second gap before `20:38:49` is the five
Sireum tool invocations.)

## Verdicts

Tier 1 — one of four file hashes no longer matches its provisioned golden:

```json
"gumbo_l1": { "passed": false, "components": {
  "sig": true,
  "tempcontrolsystem_targ": true,
  "tempsensor_targ": true,
  "tempcontrolperiodic_p_tcproc_tempcontrol_gumbox_targ": false,
  "tempsensorperiodic_p_tcproc_tempsensor_gumbox_targ": true } }
```

Tier 2 — of 28 measured contract regions, exactly the mutated range fails:

```json
"gumbo_l2": { "passed": false, "components": {
  "tc_gumbox_113_120_targ": false,
  "... all 27 other targets ...": true } }
```

Tier 3 — the live Sireum toolchain, one tool per component:

```json
"gumbo_validation": { "passed": false, "components": {
  "proyek tipe slang": true,
  "proyek logika TempControlPeriodic_p_tcproc_tempControl_GumboX.scala": true,
  "proyek logika TempSensorPeriodic_p_tcproc_tempSensor_GumboX.scala": true,
  "proyek test TempControlPeriodic_p_tcproc_tempControl_GumboX_UnitTests": false,
  "proyek test TempSensorPeriodic_p_tcproc_tempSensor_GumboX_UnitTests": true } }
```

## Final hypothesis (written by TrustDecisionKS)

> Attestation integrity violation with failed semantic verification;
> failing components: gumbo_l1/tempcontrolperiodic_p_tcproc_tempcontrol_gumbox_targ,
> gumbo_l2/tc_gumbox_113_120_targ;
> failing verification: gumbo_validation/proyek test
> TempControlPeriodic_p_tcproc_tempControl_GumboX_UnitTests

## How to read the result

- **Attribution narrows at every tier.** Tier 1 says *which file* changed;
  tier 2 says *which contract* (the guarantee at lines 113–120); tier 3 says
  *which verified property no longer holds* (the TempControl oracle's unit
  tests).
- **Type checking passed** — the mutation is well-typed.
- **Formal verification (Logika) passed** — this is the subtle one. A flipped
  enum inside a pure oracle predicate yields a different but perfectly
  *provable* predicate; there is no specification above it to contradict.
  Verification checks provability, not whether the oracle says what its
  author meant.
- **Randomized GumboX unit tests failed** — they execute the real component
  against the oracle, and the component's correct behavior (fan off when the
  temperature is below the set point) refutes the inverted oracle.
  Testing and verification catch **disjoint classes of oracle corruption**,
  which is why the validation tier runs both.
- Compare with the text-only tamper demo (`--tamper`), where tiers 1–2 fail
  but tier 3 passes, yielding the hypothesis *"artifacts modified yet system
  still verifies"* — the ladder distinguishes edits that change bytes from
  edits that change meaning.

## Reproduce

```sh
cd ~/Claude_workspace/pybb
./examples/run_full_workflow.sh --tamper-semantic
```

Prerequisites and the full workflow (including provisioning) are documented
in [pybb/attestation/README.md](../pybb/attestation/README.md). The tampered
oracle is restored automatically (verified by the script) — the run leaves
no changes behind.
