# AutoVerus on the blackboard: standalone repair and attested re-verification

Two workflows around the same knowledge source
(`pybb/autoverus/AutoVerusRepairKS`, merged from the `apk` branch), with
one division of labor throughout: **repair repetition happens inside the
knowledge source** (AutoVerus's own `--mode repair` loop, `repair_steps`
rounds of LLM-driven candidate generation checked against Verus
internally), and **the verdict comes from outside it** — its claim of
success is never trusted.

## LLM-call safety (read first)

AutoVerus calls the OpenAI API. The rules, enforced in code:

- **Nothing calls an LLM by default.** The rung's `allow_llm` latch
  defaults to False and refuses the real bridge (the entry escalates
  with the refusal on record). Only the examples' explicit `--autoverus`
  flag arms it, after printing what will run. Every CI-runnable test
  drives the rung through the `repair_fn` seam — no LLM anywhere; the
  one live test is triple-gated (`RUN_AUTOVERUS=1` + preflight + key).
- **The key lives in the environment ONLY.** `OPENAI_API_KEY` is read at
  call time by the bridge; the config JSON handed to AutoVerus carries
  an empty key field (pinned by test); the key crosses the subprocess
  boundary via env (`extra_env`/WSLENV), never argv or files. Never
  commit, log, or echo it — `.gitignore` covers `.env`/`secrets*`.

## The standalone workflow (apk's, as merged)

`examples/autoverus_example.py --autoverus`: one entry asks "does this
Rust file's Verus proof check?" (`make_verus_predicate` — direct verus
subprocess, memoized on the file's CONTENT HASH read at call time);
failure routes to the rung; the repaired file's new hash makes the same
predicate re-verify in the same run. Detect → repair → confirm, no
attestation stack involved. Vacuous proofs (`assume(`/`admit()`) are
rejected before Verus runs; `examples/autoverus_failure_example.py`
shows the unfixable-spec escalation. Setup: edit the paths at the top of
`pybb/autoverus/config.py` (AutoVerus is Linux/WSL-only) and set
`OPENAI_API_KEY`.

## The attested workflow (`examples/find_max_verus.py`)

The same rung on an ATTESTATION entry, with the **definitive Verus run
performed by the CVM** in a fresh episode:

    find_max_verus:ready   readiness + signed-baseline verification
    find_max_verus:proof   eval find_max_verus_check: the CVM runs
                           `verus targets/find-max-verus/find_max.rs
                           --output-json`, verus toolchain (wrapper,
                           binary, rust_verify, z3) hashed in the same
                           term measure-then-use, SIG; appraised by
                           run_command_verus_appr (errors == 0)
      fail -> AutoVerusRepairKS(target=..., reattest=True):
              AutoVerus iterates internally, writes the repair,
              cheat-gates it, then request_restart(key)
      episode 2: the fresh CVM measurement judges the repaired file
        pass -> "repaired and re-attested clean in-session (episode 2)"
        fail -> reattest_budget exhausted -> escalation with the verdict

The committed target (`targets/find-max-verus/find_max.rs`, Verus-Bench
find_max, MIT) is the VERIFIED reference — the provisioning bundle signs
a passing measurement, which readiness re-appraises at every episode.
`--tamper` deletes the `exists` loop-invariant conjunct, reproducing the
`broken_proof.rs` repair task (1 verified, 1 error).

Attested-mode specifics of the rung:

- **`reattest=True`** replaces the standalone re-measure with
  `request_restart`: the fresh episode's attested run — toolchain
  measured in-term, evidence signed and gzip-archived — is the only
  thing that flips standing. The repair's word is worthless by
  construction.
- **The cheat gate moves in front of the restart**: a vacuous repair
  would PASS attested Verus (the appraiser sees verus output, not
  source), so `find_cheat` refuses the re-attestation instead — no
  restart is spent and the entry escalates. An appraiser-side cheat ASP
  (source measured into the term) is the noted hardening follow-up.
- **`reattest_budget`** (default 1) bounds definitive re-verifications
  per key, checked BEFORE any repair runs: a restart resets the entry's
  KS budget (fresh episode semantics), so without this the rung would be
  re-invoked — and live AutoVerus re-billed — every episode until the
  controller's restart cap.

Known limitation, recorded: `run_command_verus_appr` passes on
`errors == 0` alone (no `verified > 0` floor — that guard currently
lives only in the standalone predicate); an asp-libs follow-up.

## Demo arcs

```sh
python examples/find_max_verus.py --provision   # tool goldens + blessing
python examples/find_max_verus.py               # clean attested episode
python examples/find_max_verus.py --tamper      # drift -> escalation (no LLM)
python examples/find_max_verus.py --tamper --autoverus   # the full arc
```

`tests/test_autoverus_attested.py` pins the arcs with the `repair_fn`
seam (CVM + RUN_VERUS=1, no AutoVerus install needed): clean episode;
repair → definitive attested pass (restarts == 1, first-fail/last-pass
history); cheated repair refused before any restart; unrepairable →
budgeted escalation; the latch and key-hygiene invariants.
