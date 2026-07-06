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
pytest -m "not cvm"   # unit tests only (no external binaries)
pytest                # includes end-to-end CVM runs (auto-skip if unavailable)
```
