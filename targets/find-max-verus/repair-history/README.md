# AutoVerus repair history — find_max.rs

Preserved artifacts from running the attested AutoVerus example
(`examples/find_max_verus.py --tamper --autoverus`) on 2026-08-07.

The `--tamper` arc deletes the loop-invariant conjunct

    exists |k: int| 0 <= k < i && nums@[k] == max,

from the verified reference (2 verified / 0 errors), reproducing the
`tests/fixtures/autoverus/broken_proof.rs` repair task (1 verified /
1 error). AutoVerus (`--mode repair`, gpt-4o) then tries to repair it,
and the DEFINITIVE Verus verdict comes from a fresh attested CVM episode
(restart-episode primitive) — never from AutoVerus's own claim.

## Artifacts

- `find_max.repair-steps5-failed.rs` — result of `--repair-steps 5`.
  AutoVerus exhausted its 5 internal steps and emitted a best-effort
  candidate whose re-added invariant used `==>` (line 27) instead of
  `&&`. That form is vacuous (antecedent false for any `k >= i`), so it
  carries no information and cannot discharge the `exists` postcondition.
  Direct Verus: **0 verified / 1 error**. The attested episode 2 REFUTED
  it, the `reattest_budget=1` was exhausted, and the entry escalated:
  "repaired but re-attestation failed — restart budget exhausted."
  NOT a false success — AutoVerus's internal `veval` runs the same Verus
  and saw the same error; it simply never converged within budget.

- `find_max.repair-steps10-verified.rs` — result of `--repair-steps 10`.
  With more iterations gpt-4o landed the correct `&&` conjunct (line 28,
  identical to the deleted line). Direct Verus: **1 verified / 0 errors**
  (1, not 2, because AutoVerus inserted `#[verifier::loop_isolation(false)]`,
  which folds the loop into its enclosing function — no obligation lost;
  the predicate policy is `verified > 0 and errors == 0`). The attested
  episode 2 CONFIRMED it: "repaired and re-attested clean in-session
  (episode 2)." A harmless empty `proof {}` block was also inserted.

## Takeaway

The 5-step failure was a budget/capability miss, not a false success. The
same restart primitive that refused the bad `==>` repair blessed the good
`&&` one — in both cases the verdict came from the fresh attested
measurement, not from AutoVerus's say-so. The live target
(`../find_max.rs`) is restored to the pristine 2/0 reference.
