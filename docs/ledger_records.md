# Ledger records

The attestation ledger stores one JSON record per key. Records are pydantic
models in `pybb/attestation/ledger.py`, serialized in canonical form (sorted
keys, no whitespace, UTF-8); `content_sha256` in the journal and the SQL
mirror is the hash of exactly those bytes. Schema tag: `pybb-ledger/v1`.
Unknown fields are preserved on read, so additions within v1 do not break
older readers.

Keys: `nonce/<nid>`, `evidence/<nid>`, `verdict/<nid>`, `appraisal/<nid>/<seq>`,
`locator/<nid>/<seq>`, `bundle/<nid>` (legacy: `bundle/sha256:<hash>`),
`restore/<created_at>`. `nid` is the sha256 of the run's nonce bytes.

## Envelope (every record)

| field | type | description |
|---|---|---|
| `schema` | string | `"pybb-ledger/v1"` |
| `kind` | string | `nonce`, `evidence`, `verdict`, `appraisal`, `locator`, `bundle`, `restore` |
| `nid` | hex or null | nonce id the record belongs to; null on legacy bundles, absent on restores |
| `created_at` | RFC 3339 UTC | when pybb built the record (the ledger's own transaction order is authoritative) |
| `committer_fp` | `sha256:<hex>` | fingerprint of the verifying public key pybb trusts |
| `pybb_version` | string | package version that wrote the record |
| `appraiser_id` | string | opaque, stable id of the pybb installation; never a hostname or user name |

## `nonce/<nid>`

One per nonce. A nonce is generated inside the CVM by the `generate_nonce`
ASP and recorded after the run; it gives a package identity, binds it under
the signature, and lets the ledger refuse a replayed package.

| field | type | description |
|---|---|---|
| `nonce_b64` | base64 | the nonce bytes (stored in clear; unpredictability before use is what matters) |
| `nonce_bytes` | int | nonce length; validated against the bytes |
| `role` | `measurement` or `appraisal` | the run's own nonce, or an appraiser nonce from an appraisal run |
| `for_nid` | hex or null | for an appraiser nonce, the run it judged |
| `state` | string | `committed` today; `issued`, `bound`, `consumed`, `expired` under the planned pre-registration |
| `freshness` | `post-hoc`, `pre-registered`, `none` | what the nonce proves: today always `post-hoc` |
| `protocol_id` | string | the Copland protocol configuration the run used |

Validation: `nid == sha256(nonce)`; an appraiser nonce must carry `for_nid`.

## `evidence/<nid>`

One per run: describes the raw signed package from the measurement run
(nonce, measurements, signature) and where its bytes are. Never holds the
bytes.

| field | type | description |
|---|---|---|
| `protocol_id` | string | protocol run |
| `term_sha256`, `session_sha256`, `manifest_sha256` | hex | hashes of the protocol files used, so "same configuration" is a comparison |
| `response_sha256` | hex | hash of the package's canonical JSON; the stable identity of the evidence |
| `blob_sha256` | hex | hash of the archived bytes exactly as stored (gzip is not reproducible); what every fetch verifies and what names the blob in the evidence repo |
| `blob_bytes` | int | size of the archived blob |
| `encoding` | string | `gzip+json` |
| `rawev_count` | int | number of RawEv slots |
| `rawev_sha256` | hex | sha256 over the flattened RawEv bytes, which is what the `hashevidence` ASP computes; appraisal bindings compare to it |
| `signature` | SignatureInfo | where the signature slot is and who signed |
| `nonce` | SlotRef | where the nonce slot is and which event produced it |
| `assurance` | `signed+nonce`, `signed`, `nonce`, `none` | computed from the package as produced |
| `freshness` | enum | as on the nonce record |
| `exception_reason` | string or null | set only when the run committed below the configured minimum assurance through an explicit exception |
| `tooling` | ToolingRef or null | the Copland evidence identifying the binaries in force (the tooling blessing) |
| `locators` | list of Locator | where the bytes were at commit time (the local path); later places are `locator` records |

Durability (two locator kinds resolving) is derived at read time, never
stored.

## `verdict/<nid>`

One per run: the queryable summary of the live appraisal.

| field | type | description |
|---|---|---|
| `protocol_id` | string | protocol run |
| `passed` | bool | overall verdict |
| `components_total` | int | appraised components |
| `components_failed` | int | failing components |
| `failing` | list of FailingComponent | the failures with their reasons |
| `components_sha256` | hex | hash of the full component list, archived as a blob |
| `appraisal_seq` | int | which appraisal record the components came from (1, the live one) |
| `evidence_assurance` | enum | assurance of the raw package |
| `appraisal_assurance` | enum | assurance of the live appraisal package |
| `interpreter` | Interpreter | how the components were read |
| `error` | string | non-empty when the run itself failed; then `passed` is false and the lists are empty |

## `appraisal/<nid>/<seq>`

One per appraisal run over a run's package. Seq 1 is the live appraisal;
later seqs are audits. An appraisal run is itself a signed, nonce-bound
Copland package bound to the judged package by a `hashevidence` slot.

| field | type | description |
|---|---|---|
| `seq` | int | order within the run |
| `mode` | `live` or `audit` | live appraisal, or a later audit |
| `anid` | hex | the appraiser nonce's id |
| `response_sha256`, `blob_sha256`, `blob_bytes`, `encoding`, `rawev_sha256` | as on evidence | the appraisal package's own hashes |
| `binding` | Binding | the `hashevidence` slot that ties this appraisal to the exact package it judged |
| `signature` | SignatureInfo | the appraiser's signature slot |
| `nonce` | SlotRef | the appraiser nonce slot |
| `assurance` | enum | of the appraisal package |
| `freshness` | enum | copied from the run's nonce |
| `passed` | bool | the appraisal's verdict |
| `components_sha256` | hex | hash of this appraisal's component list |
| `interpreter` | Interpreter | `verified-summary` for live and raw-package audits; `legacy-walker` for audits of appraisal packages |
| `tooling` | ToolingRef or null | binaries in force for this appraisal |
| `checks` | map of bool | audit only: `ledger_verified`, `bytes_match`, `nid_ok` |
| `locator_used` | Locator or null | audit only: which copy of the package was judged |
| `agrees_with_recorded_verdict` | bool or null | audits of the raw package: agreement with `verdict/<nid>`; null otherwise |
| `audits_seq` | int or null | set when this record audits an appraisal package: the seq of the appraisal judged |

## `locator/<nid>/<seq>`

One per place a blob can be found, appended by pushes to the evidence repo
and by audits. Never rewritten.

| field | type | description |
|---|---|---|
| `seq` | int | order within the run |
| `target` | `evidence`, `appraisal`, `components`, `bundle` | which blob |
| `blob_sha256` | hex | the exact bytes it locates |
| `locator` | Locator | where |
| `verified` | bool | the writer re-read the bytes at that location and matched the hash |

## `bundle/<nid>`

One per provisioning bundle (a signed golden baseline). Shaped like an
evidence record without a verdict. Legacy bundles, provisioned before
nonces, key by content hash with `nid` and `nonce` null and
`assurance: signed`.

| field | type | description |
|---|---|---|
| `protocol_id` | string | provisioned protocol |
| `response_sha256`, `blob_sha256`, `blob_bytes`, `encoding`, `rawev_count`, `rawev_sha256` | as on evidence | the bundle's hashes (`encoding` is `json`) |
| `golden_ts` | string | the goldens' timestamp |
| `targets` | int | number of golden targets |
| `signature` | SignatureInfo | signature slot |
| `nonce` | SlotRef or null | nonce slot; null on legacy bundles |
| `assurance`, `freshness` | enum | as on evidence |
| `tooling` | ToolingRef or null | blessing in force; null for the tooling bundle itself |
| `locators` | list of Locator | where the bundle file is |

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

**SlotRef** — where an event's output sits in the flat RawEv list.

| field | type | description |
|---|---|---|
| `slot` | int | RawEv index |
| `asp` | string | ASP that produced it |
| `asp_targid` | string or null | pybb's target id for the event |

**SignatureInfo**

| field | type | description |
|---|---|---|
| `present` | bool | the package has a signature |
| `slot` | int or null | its RawEv index |
| `asp` | string or null | `sig` or `sig_tpm` |
| `signer_fp` | string or null | fingerprint of the verifying key |
| `verified` | bool or null | set only by a CVM-native audit (`sig_appr` verdict); never by pybb |

**ToolingRef**

| field | type | description |
|---|---|---|
| `kind` | `bundle` or `run` | the tooling blessing bundle, or a tooling run under a re-measurement cadence |
| `ref` | string | the bundle's sha256, or the run's nonce id |

**Locator**

| field | type | description |
|---|---|---|
| `kind` | `local` or `github` | where |
| `path` | string | file path, or path inside the repository |
| `appraiser_id` | string or null | local: whose filesystem |
| `repo`, `commit`, `git_blob_sha` | string or null | github: `owner/name`, commit, git blob id |

**Binding**

| field | type | description |
|---|---|---|
| `slot` | int | RawEv index of the `hashevidence` output |
| `asp` | string | `hashevidence` |
| `evidence_hash` | hex | the hash it computed over the judged package |
| `matches_evidence` | bool or null | the `goldenbytes_appr` verdict from a CVM-native audit of this appraisal package; null until one has run |

**FailingComponent**

| field | type | description |
|---|---|---|
| `targ_id` | string or null | the failing target |
| `appr_asp` | string | the appraiser that failed it |
| `reason` | string | its reason text |

**Interpreter**

| field | type | description |
|---|---|---|
| `kind` | `verified-summary` or `legacy-walker` | the verified summarizer, or pybb's slot-layout reader |
| `tool` | string | tool name (never a hash; tool identity is the `tooling` reference) |
