# Ledger records (schema v2)

The attestation ledger stores one JSON record per key. Records are pydantic
models in `pybb/attestation/ledger.py`, serialized in canonical form (sorted
keys, no whitespace, UTF-8, `null` members omitted); `content_sha256` in the
journal and the SQL mirror is the hash of exactly those bytes. Schema tag:
`pybb-ledger/v2`. Unknown fields are preserved on read, so additions within
v2 do not break older readers. There is no compatibility with earlier
schemas while the design iterates (plan P.9.8): the dev database is
recreated when the schema changes.

Five kinds, five key shapes:

| key | kind | one per |
|---|---|---|
| `bundle/<bid>` (legacy: `bundle/sha256:<blob hash>`) | `bundle` | CVM run output: a measurement, an appraisal, a provisioning bundle, a `stack` or `config` context bundle (plan O), a (planned) challenge |
| `judged_by/<bid>/<appraisal bid>` | `judged_by` | appraisal, pointing from the bundle it judged |
| `mirror/<store>/<state_tx>` | `mirror` | push to an evidence store |
| `restore/<created_at>` | `restore` | restore of the ledger from a mirror |
| `blessing/<stack bid>` | `blessing` | operator approval of one `stack` bundle (plan O.5) |

`bid` is the **bundle id**: the sha256 of the nonce the CVM's `generate_nonce`
ASP drew inside that run. A bundle and its nonce are one thing; a replayed
or duplicated package has a bid the ledger already holds and is refused
(pybb checks, and immudb enforces it with a `keyMustNotExist` precondition
on every `bundle/` key).

## Envelope (every record)

| field | type | description |
|---|---|---|
| `schema` | string | `"pybb-ledger/v2"` |
| `kind` | string | `bundle`, `judged_by`, `mirror`, `restore`, `blessing` |
| `bid` | hex | on bundles: the bundle id (absent on legacy nonce-less bundles); on `judged_by`: the judged bundle |
| `created_at` | RFC 3339 UTC | when pybb built the record (the ledger's own transaction order is authoritative) |
| `committer_fp` | `sha256:<hex>` | fingerprint of the verifying public key pybb trusts |
| `pybb_version` | string | package version that wrote the record |
| `appraiser_id` | string | opaque, stable id of the pybb installation; never a hostname or user name |

## `bundle/<bid>`

What every CVM run produces: a signed, nonce'd package that pybb archived,
hashed and laid out. What the bundle is evidence *of* is its `role` and its
`inputs`.

| field | type | description |
|---|---|---|
| `role` | `measurement`, `appraisal`, `provision`, `challenge`, `stack`, `config` | a measurement of the target system; an appraisal of another bundle; a provisioning bundle (signed golden baseline); a pre-registered challenge (section G, planned); the CVM/asp-libs installation measured by the CVM (`stack`, plan O.1); one protocol's exact inputs measured by the CVM (`config`, plan O.2) |
| `protocol_id` | string | the protocol configuration the run belongs to (for an appraisal: the protocol it appraises; for a `config` bundle: the protocol it describes; a `stack` bundle: `attestation_stack`) |
| `term_sha256`, `session_sha256`, `manifest_sha256` | hex | hashes of the **canonical term, session and manifest pybb placed in the request the CVM ran** (plan O.3; before O the term pin was of the raw `term.json`). A `config` bundle's `input:<constructor>:<term|session|manifest>` targets measure exactly those bytes, so a reader joins a run to its configuration by hash equality. For an appraisal they pin the **appraisal policy** (companion map, goldens) |
| `response_sha256` | hex | hash of the package's canonical JSON; the stable identity of the evidence |
| `blob` | BlobRef | the archived bytes: hash, size, encoding and every known location |
| `rawev_count` | int | number of RawEv slots |
| `rawev_sha256` | hex | sha256 over the flattened RawEv bytes, which is what the `hashevidence` ASP computes; an appraisal's binding compares to it |
| `nonce` | NonceInfo or absent | the run's nonce: the ASP that drew it and the bytes in clear (unpredictability before use is what matters, not secrecy after); absent only on legacy nonce-less provisioning bundles |
| `signature` | SignatureInfo | that the package is signed, by which ASP, and by whose key |
| `assurance` | `signed+nonce`, `signed`, `nonce`, `none` | computed from the package as produced |
| `freshness` | `post-hoc`, `pre-registered`, `none` | what the nonce proves: `post-hoc` today (binding, uniqueness, order; not a challenge) |
| `exception_reason` | string or absent | set only when the run committed below the configured minimum assurance through an explicit exception |
| `tooling` | ToolingRef or absent | legacy (plan B.8, retired by O): the tooling blessing in force; readable on old bundles, never written again. Runs now carry **no pointer** to their context — see "What a reader derives" below |
| `error` | string | non-empty on a measurement whose live appraisal never happened: why |
| `shape` | string or absent | the term constructor that produced the package (plan M, N.5): `measure` (a measurement run, from the split flow, a measurement-only run, or provisioning), `appraise` (any appraisal run), `combined` (the one-run shape); absent on legacy or foreign bundles. Readers use it to pick the session typing a package lays out under |
| `inputs` | list of InputRef, appraisal only (and a challenged measurement) | the bundles this run took as initial evidence: an appraisal names the one bundle it judged; a challenged measurement names its challenge |
| `verdict` | Verdict, appraisal only | the reading of this appraisal package |
| `claim` | ContextClaim or absent | on measurement and appraisal bundles pybb writes: the writer's claim of the stack and configuration the run was made under (plan P.3), measured into the run's claim lane (P.2). Absent on stack and config bundles and on bundles from other writers |
| `golden_provenance` | list of GoldenProvenance, appraisal only | where the goldens the CVM compared against came from (plan P.11); required and non-empty on every appraisal. There are no kinds of appraisal: live, first-later and audit are positions in the chain `judged_by/<bid>/…` (same transaction as the input; no earlier appraisal; a later one or an input that is itself an appraisal, stack or config), and a policy is its `session_sha256` |
| `provision` | ProvisionInfo, provision only | goldens timestamp and target count |
| `stack` | StackInfo, stack only | `plc` (the Copland place the CVM ran as), `executables` (CVM, summarizer and ASP executables measured), `fingerprint` (the package's `H_bin` slot: the CVM's `hashevidence` over the binaries' and key's digests in term order, base64) and `invocation` (the `stack:invocation` slot, the digest of `cvm_config.json`). Slot copies, never computed by pybb (plan P.1) |
| `config` | ConfigInfo, config only | `constructors` (the term constructors whose inputs were measured), `files` (`[{targ_id, blob}]`: each materialized input archived as a content-addressed `json` blob, so a reader can fetch the exact session a package laid out under) and `fingerprint` (the package's `H_cfg` slot) |
| `state`, `challenge` | challenge only | section G lifecycle (`issued`, `bound`, `consumed`, `expired`) and the challenge's metadata; the only key the appraiser ever writes twice |

**The claim lane** (plan P.2). Every run term pybb builds carries, as its
left-most branch (`bseq right_path`, so the lane gets empty evidence and
never retains a copy of an appraised package), `hashfile` over five files
the run wrote just before it ran: its canonical `term.json` (a fixed point:
the term names the file as a target), `session.json`, `manifest.json`,
`cvm_config.json` (the CVM invocation) and `claim.json` (the claim). RawEv
is `[sig, nonce, claim:term, claim:session, claim:manifest,
claim:invocation, claim:claim, …as before]`; readers step over the five-slot
prefix by its `claim:` target ids. The lane's `claim:term` digest and a
config bundle's `input:<constructor>:term` digest are `hashfile` outputs over
the same bytes, so a run is tied to its measured configuration by CVM
digests, not by a pointer. In a live appraisal the measurement's lane is
judged against the files pybb wrote (`golden_provenance` names the
measurement bundle, in the same batch); in a later appraisal the stored
package's lane is judged against the config bundle the claim names (term,
session, manifest) and the run's archived lane files (invocation, claim).

Validation: `bid == sha256(nonce bytes)`; an appraisal has `inputs` and a
`verdict` and a non-empty `golden_provenance`, no other role carries any of them; a challenged
measurement names exactly one input; a challenge has a `state`; only a
`stack` bundle carries `stack`, only a `config` bundle carries `config`. A `golden_provenance` ref must be a
key the ledger holds at commit, like an input.

### What a run writes

| event | batch |
|---|---|
| live run (two CVM invocations) | `bundle/<mid>` (measurement) + `bundle/<abid>` (appraisal, `inputs=[mid]`, provenance `protocol`) + `judged_by/<mid>/<abid>`, one transaction |
| later appraisal of a measurement (`appraise_bundle`), same or different policy | `bundle/<abid2>` (`inputs=[mid]`, `session_sha256` pinning the policy) + `judged_by/<mid>/<abid2>` |
| appraisal of an appraisal bundle (plan B.6: signature, appraiser nonce and binding judged inside the CVM) | `bundle/<abid3>` with `inputs=[abid]` + `judged_by/<abid>/<abid3>` |
| provisioning | `bundle/<bid>` (`provision`) |
| `examples/ledger_context.py measure stack` (operator command) | `bundle/<sbid>` (`stack`); with `--bless` also `blessing/<sbid>` |
| `examples/ledger_context.py measure config <pid>` (operator command) | `bundle/<cbid>` (`config`, `protocol_id = pid`) |
| audit of a stack / config bundle (`appraise_bundle`) | `bundle/<abid>` (`inputs=[sbid]`, provenance `blessing` for a stack, the bundle's own files for a config) + `judged_by/<sbid>/<abid>` |

### What a reader derives (plan O.7)

Runs store no pointer to the stack or configuration they ran under: pybb
runs the CVM in the state it is in, and the ledger says afterwards whether
that state had been measured. For a run bundle R by writer W
(`appraiser_id`, or `committer_fp`), `ledger_context.derive_context` finds:

- the **stack in force**: W's latest `stack` bundle at a lower transaction,
  and whether a `blessing/` record exists for it;
- the **configuration in force**: W's latest `config` bundle with
  `protocol_id == R.protocol_id` at a lower transaction;
- the **pins**: R's `term_sha256`/`session_sha256`/`manifest_sha256` against
  that config bundle's `input:<constructor>:*` file hashes, for some
  constructor (`measure`, `appraise`, `combined`, `audit`,
  `appraise_combined`, `audit_combined`).

Pins matching: R ran under a measured configuration. Pins differing: the
inputs changed after the last `measure config`; R belongs to no measured
configuration. No earlier `config` bundle from W: no configuration evidence
exists for R. `examples/appraise_from_ledger.py` prints this beside every
bundle; `examples/ledger_context.py show` prints it for one.

## `judged_by/<bid>/<appraisal bid>`

A pointer written in the same batch as every appraisal bundle, so "every
appraisal of bundle X" is one prefix scan (`immuclient scan --prefix
judged_by/<bid>/`) with no secondary index. Nothing is sequenced; ledger
transaction order is the order.

| field | type | description |
|---|---|---|
| `bid` | hex | the judged bundle |
| `appraisal_bid` | hex | the appraisal bundle |

## `mirror/<store>/<state_tx>`

One per push to an evidence store (`ledger_repo.push_archive`). Bundles
state at commit time where their bytes are and will be (`blob.locations`:
`local` plus the content-addressed path in each configured store); a
mirror record witnesses that a push happened and what it carried. The key's
`<store>` is the store id with `:` and `/` replaced by `-`
(`github:ku-sldg/pybb-ledger` → `github-ku-sldg-pybb-ledger`); `<state_tx>`
is the ledger head the push captured, zero-padded to 12 digits.

| field | type | description |
|---|---|---|
| `store` | string | store id: `github:owner/name`, or `git:<name>` for a non-hosted remote |
| `repo` | string | the remote's `owner/name` (or basename) |
| `commit` | hex | the git commit the push made |
| `state_tx`, `state_hash` | int, hex | the ledger head (`tx_id`, `tx_hash_hex`) written to `ledger/state/<tx>.json` |
| `journal_from_tx`, `journal_to_tx` | int | the journal lines this push appended |
| `blobs` | int | blobs carried |
| `blob_hashes_sha256` | hex | sha256 over the sorted, concatenated hashes of those blobs |
| `skipped` | list of `{blob_sha256, reason}` | stated blobs the push could not carry (`local bytes missing`, `local bytes mismatch`) |

A stated location is **durable** when the clone (or the remote) has the file
at that path and it hashes to its name; `reconcile` reports stated-but-absent
blobs as pending. Nothing is derived from mirror records alone.

## `blessing/<stack bid>`

The operator's approval of one `stack` bundle (plan O.5), written by
`examples/ledger_context.py bless` (or `measure stack --bless`). One per
stack bundle; attributable to the installation that made it through the
envelope. Configurations are not blessed.

| field | type | description |
|---|---|---|
| `stack_bid` | hex | the approved stack bundle |
| `targets` | list of string | its `stack:*` target ids |
| `goldens` | map target id → base64 | the measured values read off the stack bundle's signed package (identification, no judgment): the expectations a later stack audit injects for `goldenbytes_appr` — the digests beneath `H_bin` and the settings lane (`stack:term`, `stack:session`, `stack:manifest`, `stack:invocation`) |
| `fingerprint` | base64 | the blessed package's `H_bin` slot; a stack audit injects it as the golden of the inner `hashevidence` event, so the CVM returns one fingerprint verdict beside the per-target ones |
| `note` | string | operator note (`--note`) |

The blessing in force when a bundle was written is the latest `blessing`
from the same writer at a lower transaction — derived by order, never
asserted. A blessing made by one writer serves others through audits
(`--against blessing/<bid>`): equal binaries yield equal goldens.

## `restore/<created_at>`

One per restore of a ledger from the evidence repo.

| field | type | description |
|---|---|---|
| `mode` | `exact` or `replay` | hot-restore from backup segments, or journal replay |
| `source_repo` | string | evidence repository |
| `source_commit` | hex | commit restored from |
| `source_last_state_tx` | int | the last mirrored ledger transaction |
| `tx_count` | int | transactions restored |

## Nested models

**BlobRef** — archived bytes.

| field | type | description |
|---|---|---|
| `blob_sha256` | hex | hash of the archived bytes exactly as stored (gzip is not reproducible); what every fetch verifies and what names the blob in a store |
| `blob_bytes` | int | size |
| `encoding` | string | `gzip+json` (packages, component lists) or `json` (provision bundles) |
| `locations` | list of Location | every place the bytes are or will be |
| `derived_from` | hex or absent | set when pybb assembled the bytes from a span of another bundle's package — the signed measurement lifted out of a `combined` run names that run's appraisal bundle |

**Location**

| field | type | description |
|---|---|---|
| `store` | string | `local`, or a store id such as `github:owner/name` |
| `path` | string | file path (local) or path inside the store (`blobs/<sha256>.json.gz`) |

Records carry no RawEv positions (plan section L). Where the nonce, the
signature or a binding sits in a package is pybb's reading of that package,
re-derived from the archived bytes and the session whenever it is needed
(`describe_package`, `slot_layout`); the record describes the evidence,
not pybb's handling of it.

**NonceInfo** — the bundle's nonce.

| field | type | description |
|---|---|---|
| `asp` | string | the ASP that drew it: `generate_nonce` |
| `b64` | base64 | the nonce bytes |
| `bytes` | int | nonce length; validated against the bytes |

**SignatureInfo**

| field | type | description |
|---|---|---|
| `present` | bool | the package has a signature |
| `asp` | string or null | `sig` or `sig_tpm` |
| `signer_fp` | string or null | fingerprint of the verifying key |

**InputRef** — a bundle this run took as initial evidence.

| field | type | description |
|---|---|---|
| `bid` | hex | the input bundle (legacy: `sha256:<blob hash>`) |
| `binding_hash` | hex | the value of this appraisal package's `hashevidence` slot, computed by the CVM over the judged bundle's RawEv; equals that bundle's `rawev_sha256`. A record-level cross-check; the CVM's own check is `goldenbytes_appr` over the slot |

**Verdict** — an appraisal bundle's reading.

| field | type | description |
|---|---|---|
| `passed` | bool | overall verdict |
| `components_total`, `components_failed` | int | appraised components and failures |
| `failing` | list of FailingComponent | the failures with their reasons |
| `components_sha256` | hex | hash of the full component list |
| `components_blob` | BlobRef or absent | the archived component list |
| `interpreter` | Interpreter | how the components were read |

Agreement between appraisals of one bundle is a reader's comparison of
their verdicts under one `session_sha256`, not a recorded field.

**ContextClaim** — the writer's claim of its context (plan P.3). A
statement, not evidence: the CVM binds it to the run by hashing `claim.json`
in the lane; the bundles it names hold the evidence.

| field | type | description |
|---|---|---|
| `stack_bid`, `stack_fingerprint`, `stack_measured_at` | hex, base64, RFC 3339 | the stack bundle the writer says was in force, its `H_bin` (a slot copy from the writer's cache), when the CVM measured it; empty when the writer had measured nothing yet |
| `config_bid`, `config_fingerprint`, `config_measured_at` | hex, base64, RFC 3339 | likewise for this protocol's configuration (`H_cfg`) |
| `fresh` | `none`, `stack`, `config`, `both` | what the refresh policy or the run's own demand re-measured right before this run (plan P.4) |
| `policy` | string | the refresh policy in force: `manual`, `every_episode`, `every_run`, `max_age:<seconds>` |
| `files` | list of `{targ_id, blob}` | the five lane files archived as content-addressed `json` blobs (`claim:term` … `claim:claim`), the goldens a later appraisal injects for the lane |

`ledger_context.verify_claim` is a reader's report on a claim: the named
bundles exist, are of the right role, by the same writer, recorded before
the run, carry the claimed fingerprints; the run's pins are among the config
bundle's inputs; whether the claimed stack was the writer's latest. The
CVM's judgment is the appraisal that injects those bundles' values as
goldens.

**GoldenProvenance** — where an appraisal's goldens came from (plan P.11).

| field | type | description |
|---|---|---|
| `source` | `protocol`, `bundle`, `blessing`, `claim` | goldens provisioned into the measured term; values read off a ledger bundle's record or package; a `blessing/` record; the claim a run bundle carries (plan P) |
| `ref` | ledger key or absent | the record the values were read from; required for every source but `protocol` |
| `targets` | list of target ids | the targets the goldens were injected for (`*` patterns allowed) |
| `asp` | string or absent | a golden with no target id: the ASP whose event received it (`hashevidence` for a binding or a fingerprint) |

`inputs` is the evidence the run took; `golden_provenance` is the yardstick
it was compared against. A measurement appraised under the protocol's own
goldens has `{source: protocol}`; a B.6 audit of an appraisal has `{bundle,
ref: bundle/<judged bid>, asp: hashevidence}`; a stack audit `{blessing, ref,
targets: [stack:*]}`; a config audit `{bundle, ref: its own key, targets:
[input:*]}`.

**FailingComponent**: `targ_id`, `appr_asp`, `reason`.

**Interpreter**: `kind` (`verified-summary` or `legacy-walker`), `tool` (a
name, never a hash; tool identity is the `tooling` reference).

**StackInfo** (stack bundles): `plc`, `executables`, `fingerprint`,
`invocation`. A stack package's RawEv is `[sig, nonce, H_bin, h_1 … h_n,
h_term, h_session, h_manifest, h_invocation]`: the binaries and key under a
`hashevidence` typed EXTEND (its output `H_bin` is sha256 over the digests
in term order, which is the sorted target-id order of the generated chain),
and beside it a settings lane hashing the run's own term (a fixed point:
the term file names itself as a target), session, manifest and
`cvm_config.json`. Identical binaries anywhere give the same `H_bin`; the
settings digests carry paths and differ per installation.

**ConfigInfo** (config bundles): `constructors` (list), `files` (list of
`{targ_id, blob: BlobRef}`; `encoding: json`, the blob hash is the file's
sha256, which is also what the `hashfile` target measured), `fingerprint`
(`H_cfg`, the same construction over the eighteen input digests), `settings`
(the settings-lane slots `config:term`, `config:session`, `config:manifest`,
`config:invocation`, so a config audit can inject them as goldens).

**ProvisionInfo**: `golden_ts` (the goldens' timestamp), `targets` (number of
golden targets).

**ChallengeInfo** (section G, planned): `requested_protocol`, `requester`,
`issued_at`, `expires_at`.
