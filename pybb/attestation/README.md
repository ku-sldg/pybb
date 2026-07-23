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
| measurement | request descriptor `{"protocol", "nonce"}` |
| predicate | runs the named protocol via the client and appraises the response into a `Verdict` |
| `entry.result` | the `Verdict`: overall pass plus per-component results |
| good standing | some tier rendered a conclusive passing verdict |
| route (`on_pass` / `on_fail` chains) | the decision tree over tiers |
| provision partition | requests to (re-)provision golden evidence from the golden directory, written by external events |
| escalate segment | every responsible tier failed (or a provisioning request failed); `entry.result` is the failure report |

The predicate (built by `make_attestation_predicate(client, protocols)`)
IS the attestation: the controller's evaluation step runs the protocol
named in the measurement and stores the appraised `Verdict` (truthy iff
every component passed). Because the controller re-evaluates entries every
cycle, the predicate memoizes on the measurement; a future repair KS forces
re-attestation by bumping the request nonce.

Knowledge sources are tier rungs (`TierKS`): each one reacts to the entry
by re-pointing its measurement at its own protocol, and the controller's
next evaluation attests there. No KS runs protocols or parses evidence.

## Protocol readiness: the first verdict

Every episode opens with a configuration question, asked on the blackboard
itself: *do the protocols in this decision tree exist and can they run?*
A readiness entry checks the **whole protocol set** (ids resolve, protocol
config complete, goldens provisioned, CVM and manifest-listed ASP binaries
present — deeper checks via CVM tooling are the documented extension
point) and spends its dispatch on that verdict:

```python
controller.route("gumbo", on_pass=[...], on_fail=[...])   # pre-registered (entry not yet written)
controller.route("gumbo:ready",
    on_pass=[StartAttestationKS(key="gumbo", start="gumbo_l1")],
    on_fail=[])                                           # config failure -> escalate
blackboard.write_entry(key="gumbo:ready", predicate="protocol_check",
    measurement=readiness_request(["gumbo_l1", "gumbo_l2", "gumbo_validation"]))
```

A passing check's on_pass rung writes the attestation entry seeded at the
starting tier (idempotently — a live episode is never clobbered); a
failing check escalates with a `ReadinessReport` that is unmistakably a
*configuration* failure, and attestation never starts. The two-entry
pattern is deliberate: dispatch is once per key, so each entry owns
exactly one branch point — readiness owns "configured vs not", the
attestation entry owns "intact vs violated". Deeper decision trees chain
further entries the same way.

## The decision tree (temp-control / GUMBO)

```python
controller.route("gumbo",
    on_pass=[TierKS(protocol_id="gumbo_validation")],
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

## Live targets and the golden directory

Every tier measures the live target tree the protocols were provisioned
against. `golden/` (top of the repo) holds the clean copies of the watched
files (those named by the protocols' `asp_args`) — the same files the
protocols' golden values were provisioned from — mirrored by absolute
path. `examples/capture_golden.py` provisions it: the deliberate,
out-of-band act of declaring the live targets known-good, run only when
the tree is verified clean and in step with the protocol fixtures.

At run time `TargetSnapshot.load(protocols, GOLDEN_ROOT)` opens the golden
directory and `restore()` reverts changed live targets to it. Nothing in
the attestation flow calls `capture()` or `restore()` — declaring and
reverting are repair / new-run decisions made outside the measurement
path, so a failed appraisal can neither overwrite its own evidence nor
launder tampered files into gold. The `--tamper` demo and the tampered
integration test corrupt the live tree and rely on the golden copies to
put it back afterward.

## Provisioning on the blackboard (the provision partition)

Provisioning is a first-class blackboard activity, but one that sources
**exclusively from the golden directory** — never from the live tree.

An external event (a new verified release, a policy decision) adds or
updates files in `golden/` and writes a request into the blackboard's
**provision partition**:

```python
controller.register_predicate("provision",
    make_provision_predicate(client, protocols, GOLDEN_ROOT))
request_provision(blackboard, "gumbo_l1")          # key "provision:gumbo_l1"
```

The `"provision"` predicate IS the provisioning, mirroring the attestation
predicate: it runs the protocol's measurement-only term (APPR stripped, the
same flow as cvm-mcp's provision mode) against the golden copies, writes
the evidence bundle under `golden/_bundles/<protocol_id>/`, extracts each
target's golden slice with asp-libs' `extract_golden_slice`, and installs
the fresh `golden_b64` values into the protocol's `asp_args` — in memory
(the shared `ProtocolDir`, so attestation in the same run uses them) and on
disk (invalidating any prebuilt `cvm_request.json`, which bakes in old
goldens). Memoized on the request descriptor; re-provisioning after the
next event is the same request with a bumped nonce.

The partition's lifecycle is simpler than certify's: the controller
evaluates provision requests **before** certify entries each cycle (so
attestation never races ahead of pending provisioning), a failing request
escalates immediately (no KS chains), and a fulfilled one stays in the
partition as the durable record of provisioned state.

The trust boundary this preserves: golden values can only ever be derived
from `golden/`, and files land there only by deliberate out-of-band acts
(`capture_golden.py`, a release pipeline). Blackboard failure handling can
never launder tampered live state into golden values — the human control
point is who may write the golden directory.

## Modules

- `copland.py` — typed Pydantic models of the CVM wire format (adapted from
  HEAL-demo's `cvm_headers.py`) plus dict-level term utilities
  (`inject_asp_args`, `normalize_term`).
- `client.py` — `ProtocolDir` (loads cvm-mcp-style protocol directories,
  assembles run requests) and `CvmSubprocessClient` (invokes the CVM binary).
  Transports implement `AttestationClient`; a socket/AM client can slot in
  without touching the rest.
- `appraisal.py` — walks post-APPR evidence into `ComponentResult`s;
  binary `overall_verdict`.
- `knowledge_sources.py` — the attestation predicate factory, `Verdict`,
  `TierKS`, and `StartAttestationKS` (the readiness→attestation link).
- `readiness.py` — the protocol-readiness predicate factory and
  `ReadinessReport`.
- `snapshot.py` — `watched_files` and `TargetSnapshot`, the clean copies
  of the live targets: captured into / loaded from the golden directory,
  restored during repair or fresh runs.
- `provision.py` — the provisioning predicate factory, `ProvisionOutcome`,
  and `request_provision`, the external-event API for the provision
  partition.
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
