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
| measurement | request descriptor `{"protocol"}` |
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
cycle, the predicate memoizes on the measurement: each protocol attests at
most once per predicate lifetime, and a fresh workflow run re-attests
everything. In-session re-attestation (e.g. verifying a repair) is a
future restart-episode primitive, deliberately not a measurement field.

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
controller.route("gumbo:files", on_pass=[...], on_fail=[...])   # pre-registered
controller.route("gumbo:contracts", on_fail=[...])              # (entries not yet written)
controller.route("gumbo:ready",
    on_pass=[StartAttestationKS(episodes={"gumbo:files": "gumbo_l1a",
                                          "gumbo:contracts": "gumbo_l1b"})],
    on_fail=[])                                           # config failure -> escalate
blackboard.write_entry(key="gumbo:ready", predicate="protocol_check",
    measurement=readiness_request(["gumbo_l1a", "gumbo_l1b", "gumbo_l2"]))
```

A passing check's on_pass starter writes every attestation entry seeded at
its starting tier (one rung starts them all — chains are failure ladders,
so two starter rungs in one chain would never both run; idempotent, a live
episode is never clobbered). A failing check escalates with a
`ReadinessReport` that is unmistakably a *configuration* failure, and
attestation never starts. The pattern is deliberate: dispatch is once per
key, so each entry owns exactly one branch point — readiness owns
"configured vs not", each attestation entry owns its own question. Deeper
decision trees chain further entries the same way.

## The layers and their roles (temp-control / GUMBO)

| tier | question | measures | granularity | runs | repair unit |
|---|---|---|---|---|---|
| `gumbo_l1a` | baseline drifted? | whole-file hashes: 2 AADL models + 2 GumboX oracles | file | always | whole file |
| `gumbo_l1b` | contract blocks intact? | 6 codegen-managed BEGIN/END blocks in the developer-owned component files | block | always | block splice |
| `gumbo_l2` | *where* in the l1a files — invariant content or benign? | 22 contract-range slices, all inside l1a files | contract clause | on l1a failure | (guides l1a repair) |
| `gumbo_validation` | does it still *verify*? | tool exit codes: tipe / logika / GumboX tests | semantic | on pass, `--validate` | none |

The split follows the HAMR paradigm: GumboX oracles are generated
("do not edit"), AADL models are baseline-immutable by policy, and
component files are "safe to edit" *except* their codegen-managed contract
blocks — which is why whole-file hashing cannot watch them and `gumbo_l1b`
exists as an always-run sentinel at terminal granularity.

```python
controller.route("gumbo:files",                        # the baseline question
    on_pass=[TierKS(protocol_id="gumbo_validation")],  # --validate
    on_fail=[TierKS(protocol_id="gumbo_l2"),
             WholeFileRestoreKS(golden_root=GOLDEN_ROOT)])
controller.route("gumbo:contracts",                    # the living-code question
    on_pass=[TierKS(protocol_id="gumbo_validation")],
    on_fail=[SliceRestoreKS(golden_root=GOLDEN_ROOT)])
```

    gumbo:files   eval gumbo_l1a (whole-file hashes, ~1s)
      pass -> gumbo_validation (~min): pass = confirmed, fail = escalate
      fail -> gumbo_l2 (contract slices, ~1s)
                pass = benign drift, tolerated (re-provision to bless it)
                fail -> WholeFileRestoreKS restores the files gumbo_l2
                        confirmed violated -> repaired, pending

    gumbo:contracts   eval gumbo_l1b (contract blocks, ~1s)
      pass -> done (or gumbo_validation with --validate)
      fail -> SliceRestoreKS splices the violated blocks from golden,
              touching nothing else -> repaired, pending

`trust_summary(blackboard, semantic=[...])` renders the final states as
prose — "intact", "confirmed by validation", "clean at finer granularity",
"passed but confirmation failed", and the repair terminal below.

## Repair: converge live to gold, never mint trust

Repair unit = measurement unit: whole-file restore is the only repair that
can return a whole-file hash to its golden value; block splice is the only
repair permitted inside a safe-to-edit file. Scope discipline: whole-file
repair restores only files the refinement tier confirmed violated — benign
drift is never repaired (legitimate edits are blessed by re-provisioning,
not laundered by repair). Repair reads gold and writes live, the one
permitted direction.

A repair rung acts, exhausts its single attempt, and the entry escalates
carrying the repair in `ks_history` — the escalate segment means "terminal
for this episode; external action required", and after a repair that
action is simply the next episode: fresh predicates re-measure everything,
converting "repaired" into "verified" (or not). `trust_summary` renders
this terminal as "repaired from golden — verification pending next
episode". The `--repair` demo runs both episodes.

## Promotion: sanctioned model changes become the new baseline

An out-of-band **attestation manager** (`examples/attestation_manager.py`)
is the sanctioned actor of model evolution: it re-measures the AADL models
on demand (polling or user prompt) and compares contract content against
the last-provisioned golden slices, position-independently — a moved
contract is not a changed one. When contracts changed, HAMR codegen is
needed and the manager writes a **promotion request** into the provision
partition, followed by the per-protocol provision requests
(`request_promotion`; the partition evaluates in write order):

```python
request_promotion(blackboard, "gumbo", ["gumbo_l1a", "gumbo_l1b", "gumbo_l2"])
```

The `"promotion"` predicate IS the pipeline: re-run HAMR codegen on the
sanctioned model (pluggable `codegen_fn`; configure the real
`sireum hamr phantom` + `codegen` invocation per deployment) → optional
semantic validation gate (opt-in: gold may not move unless the
regenerated project verifies) → **regenerate the target maps from the new
content** (`targetmap.py` syntax scan: GUMBO clause spans, `@strictpure`
spans, marker blocks — a model edit shifts line numbers, so target
*definitions*, not just golden values, must be re-derived; deriving from
the HAMR attestation report is the planned alternative backend) → capture
the watched files into `golden/` (gold moves). The provision requests
behind it extract fresh goldens against the new targets, and the next
attestation episode measures the live tree against the new baseline.

Trust note: promotion is reachable only from the attestation manager —
the authorization point for sanctioned AADL changes — never from the
blackboard's failure handling. Derived target maps are complete over
their syntax and may be supersets of a historically hand-curated map;
after promotion, the derived map is the baseline.

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
request_provision(blackboard, "gumbo_l1a")         # key "provision:gumbo_l1a"
```

The `"provision"` predicate IS the provisioning, mirroring the attestation
predicate: it runs the protocol's measurement-only term (APPR stripped, the
same flow as cvm-mcp's provision mode) against the golden copies, writes
the evidence bundle under `golden/_bundles/<protocol_id>/`, extracts each
target's golden slice with asp-libs' `extract_golden_slice`, and installs
the fresh `golden_b64` values into the protocol's `asp_args` — in memory
(the shared `ProtocolDir`, so attestation in the same run uses them) and on
disk (invalidating any prebuilt `cvm_request.json`, which bakes in old
goldens). Memoized on the request descriptor per predicate lifetime;
re-provisioning after a later event happens in a fresh workflow run.

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
- `repair.py` — `WholeFileRestoreKS` and `SliceRestoreKS`, the repair
  rungs (repair unit = measurement unit; gold -> live only).
- `targetmap.py` — target-map derivation by syntax scan (GUMBO clauses,
  GumboX predicates, marker blocks) and term construction.
- `promotion.py` — the promotion predicate factory, `PromotionOutcome`,
  and `request_promotion`, the attestation-manager API.
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
