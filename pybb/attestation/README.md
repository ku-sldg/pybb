# pybb.attestation

Remote-attestation knowledge sources for the pybb blackboard, integrating the
ku-sldg Copland stack (Rocq CVM + asp-libs ASPs) following the patterns of
HEAL-demo and cvm-mcp.

## Architecture

Attestation is expressed as blackboard dynamics, not a call chain. Knowledge
sources coordinate through key conventions:

| key | written by | value |
|---|---|---|
| `attestation.request/<id>` | any domain KS | `{"protocol": id, "path_map"?: {...}}` |
| `attestation.evidence/<id>` | `AttestationKS` | raw `ProtocolRunResponse` + success flag |
| `attestation.verdict/<id>` | `AppraisalKS` | binary verdict + per-component summary |
| `attestation.component/<id>/<cid>` | `AppraisalKS` | one entry per appraised target |
| `attestation.hypothesis` | `TrustDecisionKS` | final trust summary (also sets `blackboard.hypothesis`) |

Guards compare timestamps (evidence newer than request, verdict newer than
evidence), so re-posting a request re-runs the pipeline. All KSs are
stateless; `blackboard.history` is the audit trail.

`EscalationKS` demonstrates blackboard control: when a cheap whole-file
protocol (gumbo_l1) fails, it posts a request for the per-contract protocol
(gumbo_l2), whose component entries attribute the failure to a specific
GUMBO contract range.

## Three-tier ladder (Phase 2 Track A)

A second `EscalationKS` instance chains gumbo_l2 failures to
`gumbo_validation`, which runs the live Sireum tools (`proyek tipe`,
`proyek logika` over the GumboX predicates, randomized GumboX unit tests)
via the `run_command_hamr` ASP — appraised by exit code, no goldens
involved. The ladder is pure configuration; no KS class knows about tiers:

    tier 1  gumbo_l1          whole-file hashes          ~1s
    tier 2  gumbo_l2          per-contract ranges        ~1s   (on l1 fail)
    tier 3  gumbo_validation  Sireum tipe/logika/test    ~min  (on l2 fail)

`TrustDecisionKS(semantic=["gumbo_validation"])` is the only place tier
semantics exist in code: integrity failures plus passing semantic
verification yield "artifacts modified yet system still verifies", while a
semantic failure yields a categorically worse hypothesis.

Command ASPs resolve their tool (e.g. `sireum`) by name from PATH;
`CvmConfig.path_prepend` (default: `~/Claude_workspace/bin`) ensures CVM
child processes see workspace-safe wrappers rather than TCC-restricted
locations.

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
  without touching the knowledge sources.
- `appraisal.py` — walks post-APPR evidence into `ComponentResult`s;
  binary `overall_verdict`.
- `knowledge_sources.py` — `AttestationKS`, `AppraisalKS`, `EscalationKS`,
  `TrustDecisionKS`.

## Running

Environment (defaults target `~/Claude_workspace`; override via env vars):

- `CVM_BINARY` — Rocq CVM binary (`cvm/_build/default/theories/cvm`)
- `ASP_BIN` — asp-libs release binaries (`asp-libs/target/release`)

Demo against the provisioned temp-control-jvm GUMBO protocols:

```sh
python examples/gumbo_attestation.py            # clean: L1 passes, no escalation
python examples/gumbo_attestation.py --tamper   # corrupt a contract line in a
                                                # temp copy: L1 fails, L2 attributes
```

Tests:

```sh
pytest -m "not cvm"       # unit tests only (no external binaries)
pytest                    # includes end-to-end CVM runs (auto-skip if unavailable)
RUN_SIREUM=1 pytest       # also the multi-minute Sireum validation run
```
