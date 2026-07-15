# Demo: self-healing attestation — the repair loop

*Captured 2026-07-06 from `./examples/run_full_workflow.sh --tamper --repair`
on the `attestation-integration` branch of pybb.*

This is HEAL-demo's attest→repair→re-attest loop as blackboard control: a
GUMBO contract line is tampered (in a temp copy of temp-control-jvm), the
attestation ladder attributes the failure to the exact contract range, a
`GoldenRestoreRepairer` restores that range from the provisioned golden, and
the pipeline re-attests everything — including one Sireum semantic pass over
the repaired state.

## Audit trail (verbatim, elided to the decision points)

```
21:13:18  conf=1.0  main               attestation.request/gumbo_l1
21:13:18  conf=0.0  AppraisalKS        attestation.verdict/gumbo_l1        FAIL (file hash)
21:13:18  conf=1.0  EscalationKS_l1_l2 attestation.request/gumbo_l2
21:13:19  conf=0.0  AppraisalKS        attestation.verdict/gumbo_l2        FAIL (tc_sys_aadl_305_308_targ)
21:13:19  conf=1.0  RepairKS           repair.action/gumbo_l2/1/tc_sys_aadl_305_308_targ
21:13:19  conf=1.0  RepairKS           repair.attempts/gumbo_l2
21:13:19  conf=1.0  RepairKS           attestation.request/gumbo_l1
21:13:19  conf=1.0  RepairKS           attestation.request/gumbo_l2
21:13:19  conf=1.0  RepairKS           attestation.request/gumbo_validation
21:13:19  conf=1.0  AppraisalKS        attestation.verdict/gumbo_l1        PASS
21:13:19  conf=1.0  AppraisalKS        attestation.verdict/gumbo_l2        PASS
21:14:37  conf=1.0  AppraisalKS        attestation.verdict/gumbo_validation PASS (sireum, ~78s)
21:14:37  conf=1.0  TrustDecisionKS    attestation.hypothesis
```

## Final hypothesis

> Integrity violation detected and repaired (1 attempt); system re-attested
> clean (gumbo_l1, gumbo_l2, gumbo_validation passed)

## What to notice

- **Repair preempted the semantic tier.** After the tier-2 failure at
  21:13:19, both `RepairKS` (priority 12) and the escalation to
  `gumbo_validation` (priority 10) were eligible; repair won. There is no
  `gumbo_validation` verdict before the repair — the expensive Sireum run
  never executed against tampered state. Had repair failed `max_attempts`
  times, its guard would go false and the starved escalation would run the
  semantic tier as a diagnosis instead.
- **Repair acted on tier-2's attribution, not tier-1's.** A file hash can't
  tell you what to restore (and can't be inverted); the per-contract range
  measurement both pinpoints the tamper and — because `readfile_range`
  goldens are content, not hashes — supplies the original bytes to restore.
- **The repaired state was fully re-verified.** `RepairKS` re-posted all
  three protocols; the repaired file re-attested byte-identical at tier 1,
  content-identical at tier 2, and semantically sound at tier 3. Trust is
  granted to the *re-attestation*, never to the repair itself.
- **Everything is auditable.** The same verdict key fails and then passes in
  history; the `repair.action` entry records what was restored and from
  where; the hypothesis states both the violation and the recovery.
- Repair modifies only the measured (tamper-target) tree. Golden values are
  never written by the repair path — re-declaring known-good state remains
  an out-of-band provisioning decision.

## Reproduce

```sh
cd ~/Claude_workspace/pybb
./examples/run_full_workflow.sh --tamper --repair
```

See [pybb/attestation/README.md](../pybb/attestation/README.md) for the
HEAL-demo `orchestrate()` ↔ blackboard mapping and prerequisites.
