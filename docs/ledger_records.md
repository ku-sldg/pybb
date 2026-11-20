# Ledger records (schema v2)

The attestation ledger stores one JSON record per key. Records are pydantic
models in `pybb/attestation/ledger.py`, serialized in canonical form (sorted
keys, no whitespace, UTF-8, `null` members omitted); `content_sha256` in the
journal and the SQL mirror is the hash of exactly those bytes. Schema tag:
`pybb-ledger/v2`. Unknown fields are preserved on read, so additions within
v2 do not break older readers. v1 records (`pybb-ledger/v1`, the seven-kind
schema) remain readable through `pybb/attestation/ledger_v1.py`; nothing
writes them.

Four kinds, four key shapes:

| key | kind | one per |
|---|---|---|
| `bundle/<bid>` (legacy: `bundle/sha256:<blob hash>`) | `bundle` | CVM run output: a measurement, an appraisal, a provisioning bundle, a (planned) challenge |
| `judged_by/<bid>/<appraisal bid>` | `judged_by` | appraisal, pointing from the bundle it judged |
| `mirror/<store>/<state_tx>` | `mirror` | push to an evidence store |
| `restore/<created_at>` | `restore` | restore of the ledger from a mirror |

`bid` is the **bundle id**: the sha256 of the nonce the CVM's `generate_nonce`
ASP drew inside that run. A bundle and its nonce are one thing; a replayed
or duplicated package has a bid the ledger already holds and is refused
(pybb checks, and immudb enforces it with a `keyMustNotExist` precondition
on every `bundle/` key).

## Envelope (every record)

| field | type | description |
|---|---|---|
| `schema` | string | `"pybb-ledger/v2"` |
| `kind` | string | `bundle`, `judged_by`, `mirror`, `restore` |
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
| `role` | `measurement`, `appraisal`, `provision`, `challenge` | a measurement of the target system; an appraisal of another bundle; a provisioning bundle (signed golden baseline, including the tooling blessing); a pre-registered challenge (section G, planned) |
| `protocol_id` | string | the protocol configuration the run belongs to (for an appraisal: the protocol it appraises) |
| `term_sha256`, `session_sha256`, `manifest_sha256` | hex | hashes of the exact term/session/manifest the CVM ran; for an appraisal these pin the **appraisal policy** (companion map, goldens) |
| `response_sha256` | hex | hash of the package's canonical JSON; the stable identity of the evidence |
| `blob` | BlobRef | the archived bytes: hash, size, encoding and every known location |
| `rawev_count` | int | number of RawEv slots |
| `rawev_sha256` | hex | sha256 over the flattened RawEv bytes, which is what the `hashevidence` ASP computes; an appraisal's binding compares to it |
| `nonce` | NonceInfo or absent | the run's nonce: the ASP that drew it and the bytes in clear (unpredictability before use is what matters, not secrecy after); absent only on legacy nonce-less provisioning bundles |
| `signature` | SignatureInfo | that the package is signed, by which ASP, and by whose key |
| `assurance` | `signed+nonce`, `signed`, `nonce`, `none` | computed from the package as produced |
| `freshness` | `post-hoc`, `pre-registered`, `none` | what the nonce proves: `post-hoc` today (binding, uniqueness, order; not a challenge) |
| `exception_reason` | string or absent | set only when the run committed below the configured minimum assurance through an explicit exception |
| `tooling` | ToolingRef or absent | the Copland evidence identifying the binaries in force (the tooling blessing) |
| `error` | string | non-empty on a measurement whose live appraisal never happened: why |
| `shape` | string or absent | the term shape that produced the package (plan M): `split`, `combined`, `appraise` (a later appraisal), `measure` (provisioning); absent on legacy or foreign bundles. Readers use it to pick the session typing a package lays out under |
| `inputs` | list of InputRef, appraisal only (and a challenged measurement) | the bundles this run took as initial evidence: an appraisal names the one bundle it judged; a challenged measurement names its challenge |
| `verdict` | Verdict, appraisal only | the reading of this appraisal package |
| `appraisal_kind` | string, appraisal only | caller-chosen label: `live` (the appraisal run right after the measurement), `audit`, or a policy name such as `slices-only` |
| `provision` | ProvisionInfo, provision only | goldens timestamp and target count |
| `state`, `challenge` | challenge only | section G lifecycle (`issued`, `bound`, `consumed`, `expired`) and the challenge's metadata; the only key the appraiser ever writes twice |

Validation: `bid == sha256(nonce bytes)`; an appraisal has `inputs` and a
`verdict`, no other role carries a verdict or `appraisal_kind`; a challenged
measurement names exactly one input; a challenge has a `state`.

### What a run writes

| event | batch |
|---|---|
| live run (two CVM invocations) | `bundle/<mid>` (measurement) + `bundle/<abid>` (appraisal, `inputs=[mid]`, `appraisal_kind: live`) + `judged_by/<mid>/<abid>` |
| later appraisal of a measurement (`appraise_bundle`), same or different policy | `bundle/<abid2>` (`inputs=[mid]`, `appraisal_kind` set, `session_sha256` pinning the policy) + `judged_by/<mid>/<abid2>` |
| appraisal of an appraisal bundle (plan B.6: signature, appraiser nonce and binding judged inside the CVM) | `bundle/<abid3>` with `inputs=[abid]` + `judged_by/<abid>/<abid3>` |
| provisioning / tooling blessing | `bundle/<bid>` (`provision`) |

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
| `checks` | map of bool | appraisals of a stored bundle: `ledger_verified`, `bytes_match`, `bid_ok` |
| `agrees_with_live` | bool or absent | a later appraisal under the same session: agreement with the measurement's live appraisal; absent otherwise |

**FailingComponent**: `targ_id`, `appr_asp`, `reason`.

**Interpreter**: `kind` (`verified-summary` or `legacy-walker`), `tool` (a
name, never a hash; tool identity is the `tooling` reference).

**ToolingRef**

| field | type | description |
|---|---|---|
| `kind` | `bundle` or `run` | the tooling blessing bundle, or a tooling run under a re-measurement cadence |
| `ref` | string | the bundle's sha256, or the run's bundle id |

**ProvisionInfo**: `golden_ts` (the goldens' timestamp), `targets` (number of
golden targets).

**ChallengeInfo** (section G, planned): `requested_protocol`, `requester`,
`issued_at`, `expires_at`.
