# pybb.attestation

Remote attestation on the pybb blackboard, integrating the ku-sldg Copland
stack (Rocq CVM + asp-libs ASPs) following the patterns of HEAL-demo and
cvm-mcp.

## Architecture

Attestation maps onto the routed blackboard's own vocabulary — predicates,
measurements, routes, and the escalate segment — rather than bringing its
own coordination machinery:

| blackboard concept | attestation meaning |
|---|---|
| entry (one per attested system) | the trust question, e.g. `"gumbo"` |
| measurement | request descriptor `{"protocol", "path_map"?, "nonce"}` |
| predicate | runs the named protocol via the client and appraises the response into a `Verdict` |
| `entry.result` | the `Verdict`: overall pass plus per-component results |
| good standing | some tier rendered a conclusive passing verdict |
| route (`on_pass` / `on_fail` chains) | the decision tree over tiers |
| escalate segment | every responsible tier failed; `entry.result` is the failure report |

The predicate (built by `make_attestation_predicate(client, protocols)`)
IS the attestation: the controller's evaluation step runs the protocol
named in the measurement and stores the appraised `Verdict` (truthy iff
every component passed). Because the controller re-evaluates entries every
cycle, the predicate memoizes on the measurement; a future repair KS forces
re-attestation by bumping the request nonce.

Knowledge sources are tier rungs (`TierKS`): each one reacts to the entry
by re-pointing its measurement at its own protocol, and the controller's
next evaluation attests there. No KS runs protocols or parses evidence.

## The decision tree (temp-control / GUMBO)

```python
controller.route("gumbo",
    on_pass=[TierKS(protocol_id="gumbo_validation", carry_path_map=False)],
    on_fail=[TierKS(protocol_id="gumbo_l2")])
```

    eval gumbo_l1 (whole-file hashes, ~1s)
      pass -> gumbo_validation  sireum tipe/logika/test (~min)
                pass = done     fail = escalate (validation report)
      fail -> gumbo_l2          per-contract slices (~1s)
                pass = done     fail = escalate (per-contract report)

- A passing l1 with a configured `on_pass` chain is *provisional*: the
  controller clears its standing and dispatches to the confirmation tier.
  Without `--validate` there is no `on_pass` chain and an l1 pass is final.
- A failing l1 dispatches to `on_fail`, where gumbo_l2's per-contract
  ranges attribute the failure to specific GUMBO contracts. If the slices
  all match (tamper outside measured content), the entry ends in good
  standing at finer granularity.
- Escalation is the controller's own end-of-chain behavior: the entry
  moves to the escalate segment carrying the failing tier's `Verdict`
  (failing components and reasons) and the `ks_history` of attempts.

`trust_summary(blackboard, semantic=[...])` renders the final state as
prose after `run()` — including the audit distinctions good standing alone
doesn't show ("intact", "confirmed by validation", "clean at finer
granularity", "passed but confirmation failed").

`carry_path_map=False` on the confirmation rung reflects a real asymmetry:
integrity tiers re-measure the attested file copy (`path_map` re-roots
every filepath), while semantic validation runs the real, runnable project.

## Provisioning is out of scope (deliberately)

pybb consumes protocol directories that were already provisioned; it never
writes golden values. Provisioning (measurement-only run → provision_bundle →
extract_golden_slice → golden_b64 in asp_args.json) is owned by the cvm-mcp
dashboard, keeping a single writer for golden state. This is also a trust
boundary: declaring "the system is in a known-good state" is a human/policy
decision made out-of-band, and must never be reachable from the blackboard's
failure-handling logic — auto-provisioning after a failed appraisal would
launder tampered state into the new golden.

## Modules

- `copland.py` — typed Pydantic models of the CVM wire format (adapted from
  HEAL-demo's `cvm_headers.py`) plus dict-level term utilities
  (`inject_asp_args`, `normalize_term`, `rewrite_filepaths`).
- `client.py` — `ProtocolDir` (loads cvm-mcp-style protocol directories,
  assembles run requests) and `CvmSubprocessClient` (invokes the CVM binary).
  Transports implement `AttestationClient`; a socket/AM client can slot in
  without touching the rest.
- `appraisal.py` — walks post-APPR evidence into `ComponentResult`s;
  binary `overall_verdict`.
- `knowledge_sources.py` — the attestation predicate factory, `Verdict`,
  and `TierKS`.
- `summary.py` — `trust_summary`, the post-run trust narrative.

Deferred to follow-up PRs (they live on the `attestation-integration`
branch): the repair loop (`RepairKS`, `GoldenRestoreRepairer` — slots in by
lengthening the `on_fail` chain) and the isolette examples (CVM ladder and
rodeo transport).

## Running

Environment (defaults target `~/Claude_workspace`; override via env vars):

- `CVM_BINARY` — Rocq CVM binary (`cvm/_build/default/theories/cvm`)
- `ASP_BIN` — asp-libs release binaries (`asp-libs/target/release`)

Command ASPs resolve their tool (e.g. `sireum`) by name from PATH;
`CvmConfig.path_prepend` (default: `~/Claude_workspace/bin`) ensures CVM
child processes see workspace-safe wrappers rather than TCC-restricted
locations.

```sh
./examples/run_gumbo_workflow.sh             # clean run (~1s)
./examples/run_gumbo_workflow.sh --tamper    # l1 fail -> l2 report -> escalate
./examples/run_gumbo_workflow.sh --validate  # clean + sireum confirmation (~min)
```

Or the Python example directly:

```sh
python examples/gumbo_attestation.py --tamper [--validate]
```

Tests:

```sh
pytest -m "not cvm"       # unit tests only (no external binaries)
pytest                    # includes end-to-end CVM runs (auto-skip if unavailable)
RUN_SIREUM=1 pytest       # also the multi-minute Sireum validation runs
```
