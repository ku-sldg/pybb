# Plan: immudb-backed attestation ledger (nonce ↔ evidence binding)

**STATUS: approved 2026-11-17. Step 1 (section A) implemented in
`pybb/attestation/ledger.py` + `tests/test_ledger.py`. Step 2 done: the
`generate_nonce` / `nonce_appr` ASPs exist in asp-libs (built, uncommitted)
and the spike ran against the real CVM — findings folded into B.1, B.2,
B.6 and C. Step 3 done: `pybb/attestation/ledger_runs.py` implements the
two-run flow, interpretation over the extracted APPR branch, assurance
policy and the one-batch commit; `make_attestation_predicate(...,
ledger=, ledger_config=)` selects it (legacy single-run flow unchanged
without a ledger); `Verdict` gained `appraisal_ref`, `components_ref`,
`nonce_id`, `ledger_ref`; archive directories carry a random suffix.
Tooling references (B.8) are wired in step 6 with bundle records.
Step 4 done: `pybb/attestation/ledger_immudb.py` (`ImmudbLedger`:
`execAll` batches, `verifiedGet` with a persistent client state, SQL
mirror, `bootstrap`), ephemeral-server fixture `immudb_server` and the
`ledger` marker, `scripts/immudb_dev.sh`, extra `pybb[ledger]`.
Step 5 done: `fetch_run`, `appraise_record` (B.5: fresh signed appraisal
of the raw package, appended as `appraisal/<nid>/<seq>`),
`audit_appraisal_package` (B.6: CVM-native audit of an appraisal package
with the same signed term, `audits_seq` set, verdicts read by slot
layout), `ledger_request(nid)` routing the predicate to an audit,
`examples/appraise_from_ledger.py`; real-CVM integration tests cover both
audit paths and a tampered appraisal blob.
Step 6 done: `pybb/attestation/ledger_repo.py` — `EvidenceRepo` (any git
clone named by `LedgerConfig.evidence_repo` / `PYBB_EVIDENCE_REPO`; the
locator `repo` slug is read from its remote), `push_archive` (blobs,
records, journal, state, manifest, one commit, push, verified `github`
locators), `resolve_github_locator` (clone at the recorded commit, else
`gh api`), `reconcile`, `verify_mirror`, `replay`, `record_restore`,
`exact_restore_command`, `commit_bundles` (legacy bundle backfill);
CLIs `examples/ledger_push.py`, `ledger_reconcile.py`,
`ledger_restore.py`; tests run the whole H.4 drill against a local bare
git remote. Hot-backup segments are operator-produced (`--backup-segment`),
not automated — `immuadmin` needs an interactive login.
Tooling identity (B.8) done: `pybb/attestation/ledger_tooling.py` registers
the attestation stack (CVM, summarizer, ASPs in use, verifying key) as a
`tools.py` tool, builds the `attestation_tools` protocol dir
(`examples/provision_tools.py`), `bless_tools` provisions it and records
the bundle, `tooling_ref_for` resolves `{kind: bundle, ref}` for every run
(default `at_provisioning`), and `ToolingResolver` implements the opt-in
`every_episode` / `every_run` cadences as ordinary ledger runs
(`{kind: run, ref: nid}`). Real-CVM test: blessing, idempotent re-bless,
runs referencing it, `verify_bundle` over the blessing.
Provisioning nonces (point 4) done: `provision._provision` wraps the
stripped term as `lseq (bseq left_path generate_nonce M) SIG` with the
ledger session/manifest (`PYBB_PROVISION_NONCE=0` restores legacy
bundles); bundles key as `bundle/<nid>` with `assurance: signed+nonce`;
`verify_bundle` appraises nonce'd bundles (`nonce_ok`) and, given a
ledger, reports `ledger_ok`/`ledger_key`. Real-CVM test: re-provisioning
l1a extracts identical goldens through the nonce'd layout, verifies, keys
by nonce, and a forced re-blessing is a distinct event.
Readiness reporting (B.7/B.8) done: `make_readiness_predicate(...,
ledger_config=)` reports missing ledger ASPs, each protocol's reachable
assurance (`signed+nonce` with a SIG step and companion, else `nonce`)
against `min_assurance` with exceptions honoured, and a missing
`attestation_tools` protocol or blessing bundle — all as configuration
failures before attestation starts. Docs (step 7) done: `docs/ledger.md`,
the ledger section of `docs/INSTALL.md`, README pointer. Steps 1–7 of
the order of work are complete; G (step 8) is the follow-up.
**Rocq scenario on immudb (2026-11-17):** service started and bootstrapped
(`~/.pybb/immudb_password`, admin rotated), stack blessed, Rocq driver
gained `--ledger immudb|PATH` (five predicate sites), `--ready --status`,
`--tamper-admitted` and `--repair` ran with every run recorded; contract
slices and verification output are recoverable from the ledger; fresh
re-appraisal and the CVM-native audit of the appraisal package both
recorded. Two defects found and fixed: (1) `slot_layout` double-counted
under EXTEND companions (`run_command_rocq_appr` keeps the judged event's
bytes; its sub-evidence is appraised as a sibling) — fixed, with the real
verification packages as fixtures; (2) rust-am-lib's
`handle_appraisal_body` returned negative-appraisal reasons as plain text
in RawEv, so any ASP after `APPR` (the B.6 `generate_nonce`/`SIG`) failed
to decode when a verdict failed — fixed on rust-am-lib branch
`ledger-verdict-b64` (reasons base64 like every RawEv value); asp-libs
`ledger-asps` carries a temporary `[patch]` to the local checkout until
the fix is upstream. Note: an audit of an appraisal package re-judges the
retained measurement outputs with their real companions, so its `passed`
follows the recorded verdict while `signature_ok`/`nonce_wellformed`/
`binding_ok` carry the authenticity result.
**Evidence repository created 2026-11-18:** private `ku-sldg/pybb-ledger`,
cloned to `~/Claude_workspace/pybb-ledger` (path in `~/.pybb/evidence_repo`,
read by `LedgerConfig.evidence_repo`). First push: 31 blobs, all records,
journal txs 1–97, state tx 99, 31 verified `github` locators; reconcile
clean. Findings: (1) branch protection is unavailable on a private repo in
a GitHub Free organization (403 "upgrade to Pro or make public"); on
2026-11-18 the repository was made **public** (pybb itself is public, so
the model bytes are not new exposure; the records do embed local archive
paths) and `main` is now protected against force-pushes and deletion,
enforced for admins — the mirror's integrity still rests on the ledger's
hashes and the mirrored state files first; (2) the first blessing's bundle bytes are gone —
provisioning overwrites `golden/_bundles/<pid>/provision_bundle.json`, and
the re-blessing happened before any push, so one `bundle` record stays
pending forever (follow-up: archive each bundle content-addressed at
blessing time, or push after every blessing); (3) journal tx ids are not
contiguous on immudb (SQL mirror/DDL transactions carry no records) —
`verify_mirror` now requires strictly increasing ids, not contiguity.**

Goal: bind a fresh nonce to a Copland evidence structure, push the
structure (or a pointer to it) to an append-only, cryptographically
verifiable ledger, and later retrieve it from the ledger and re-appraise
it under the CVM's own appraisal semantics. The ledger is immudb; pybb
talks to it through `immudb-py`. External tools (`immuclient`, immudb's
SQL, any gRPC/REST client) can read the same records without pybb.

## Where this attaches to pybb today

| existing seam | role in the ledger design |
|---|---|
| `ProtocolDir.build_request()` ([client.py](../pybb/attestation/client.py)) | the one place initial `EVIDENCE` is built — today always `empty_evidence()`; unchanged now, the seam for section G's two-run challenge |
| `make_attestation_predicate._archive` / `_attest` ([knowledge_sources.py](../pybb/attestation/knowledge_sources.py)) | responses are already archived gzipped under `evidence/<episode>/`; `_attest` becomes measure-then-appraise (B.0), the ledger push follows the archive, and `Verdict.evidence_ref` gains a ledger sibling |
| `provision.py` strip-APPR-keep-SIG transform | the term shape for the measurement run (B.0) already exists here |
| `baseline.verify_bundle` ([baseline.py](../pybb/attestation/baseline.py)) | the proven pattern for **appraisal-only re-runs of stored evidence** (`TERM = APPR`, `EVIDENCE = stored package`); ledger appraisal reuses it |
| `summarizer.summarize_response` | verified interpretation of the re-appraisal response; unchanged |
| `golden/_bundles/<pid>/provision_bundle.json` | provision bundles are evidence too and get ledger records the same way |

Nonce facts established from the sources (not from pybb, which has no
nonce code yet):

- Copland's own nonce is `nonce_evt(N_ID)`, created **outside** the
  protocol by the requester and appraised by a spec-fixed `check_nonce`
  ASP with empty args (`CoplandSpec/Built_In_Params.v`; the
  `nonce_creation` comment in `CoplandSpec/Appraisal.v`). This plan does
  **not** use it: a requester-supplied nonce needs an out-of-band channel
  (environment, file, or an inline ledger write) to reach the appraiser,
  and none is wanted here. Consequence, recorded deliberately: the nonce
  below is a *measurement of randomness* (an ordinary `asp_evt`), and
  copland-spec's formal results about `nonce_evt` do not apply to it.
- An ordinary EXTEND measurement ASP is fully supported end to end: `sig`
  (`EvInSig: ALL`) signs its slot, `ASP_Comps` names its companion, the
  CVM passes the event's `ASP_ARGS` to that companion (`Monad.v`
  `invoke_APPR'`), the verified summarizer attributes it by `asp_targid`,
  and no pybb special-casing is needed.
- Guarantee level of this design: **binding** (nonce and measurements
  under one signature), **uniqueness** (the ledger refuses a nonce it
  already holds), **ordering** (the ledger tx timestamps the record).
  **Not** challenge freshness: the appraiser first learns the nonce from
  the package itself, so a replayed or precomputed package cannot be
  distinguished by the nonce alone. In pybb's single-host model the
  package arrives on the CVM subprocess's stdout, so replay requires a
  compromised CVM/ASP, which defeats the measurements anyway. Every
  record is labelled `freshness: post-hoc`; section G is the upgrade.

## A. Ledger core — `pybb/attestation/ledger.py` (pybb only)

- Records (pydantic): `NonceRecord`, `EvidenceRecord`, `VerdictRecord`,
  `LocatorRecord`, `AppraisalRecord`, `BundleRecord`, `RestoreRecord` —
  bodies and the common envelope in section I. Every record carries the
  `nid` it belongs to (legacy bundles without a nonce key by content
  hash instead; `restore` has none).
- Canonicalization: `json.dumps(sort_keys=True, separators=(",", ":"))`
  is the stored value; `content_sha256` of that string is recorded in
  the SQL mirror so external readers can verify a KV value against a row.
- `Ledger` ABC: `commit_run(nonce, appraiser_nonce, evidence, appraisal,
  verdict) -> Receipt` (one batch, B.3), `get(nid) -> RunRecords`,
  `exists(nid)`, `append_appraisal` (audits), `append_locator`,
  `commit_bundle`, `commit_restore`, `history(filters)`. `Receipt` carries immudb's tx id
  and a client-verified flag.
- `ImmudbLedger`: `immudb-py`; keys `nonce/<nid>`, `evidence/<nid>`,
  `verdict/<nid>`, `appraisal/<nid>/<seq>`, `bundle/<nid>`, written with
  `execAll` and read with `verifiedGet` (client-side inclusion proof;
  client state under `~/.pybb/immudb_state`). SQL mirror table
  `attestation_records(nid, kind, protocol_id, evidence_sha256,
  content_sha256, created_at, passed, ...)` in the same batch, for
  `immuclient`/SQL queries by protocol, date, or verdict. Evidence bytes
  are **never stored in immudb** (decision 2, section H): records carry
  the sha256 and a list of locators.
- `FileLedger`: JSONL with a `prev_hash` chain, same interface. Used by
  unit tests and as the no-server fallback; never the default in demos.
- Config: `LedgerConfig(host="127.0.0.1", port=3322, db="pybb",
  user/password from env `PYBB_IMMUDB_USER/PASSWORD`, state_dir,
  evidence_repo, fail_open=False)`. New optional dependency group
  `ledger = ["immudb-py>=1.5"]` in `pyproject.toml`; core pybb stays
  pydantic-only.

## B. Nonce strategy: in-protocol generation, post-run commit

Decision 1 (resolved): a `generate_nonce` ASP runs first in every
protocol, its output is signed with the measurements, and pybb commits
the whole package — nonce embedded — to the ledger **after** the run.
Nothing touches the ledger, the environment, or the filesystem during
the run.

### B.0 Two CVM runs per protocol: measure+sign, then appraise (confirmed 2026-11-17)

Finding (2026-11-17, `evidence/20260922-141358/isolette_sysmlv2_rust_l1a`):
every fixture term ends with an in-run `APPR`, and the archived response
is the **post-appraisal** evidence — all 14 `RawEv` slots are appraiser
verdicts (`""` = pass). REPLACE appraisers (`goldenbytes_appr`,
`sig_appr`, and `nonce_appr` as planned) replace measurement, signature,
and nonce bytes with verdicts. Such a package carries no signature, no
measurements, and no nonce, so it cannot anchor a `nid`, cannot be
re-verified, and cannot be re-appraised (B.5/E).

Change: `_attest` performs two CVM invocations, the shape provisioning
and `verify_bundle` already use:

1. **Measurement run** — the protocol term with `APPR` stripped and `SIG`
   kept (`lseq (asp generate_nonce) (lseq <measurements> SIG)`). Its
   response is the **raw signed package**: nonce, measurements, signature
   all present. This is what `_archive` stores, what the ledger's
   evidence record describes, and what any later audit re-appraises.
2. **Appraisal run** — the signed, nonce-bound appraisal term of B.6
   over the raw package (`verify_bundle`'s request shape, extended). Its
   response is interpreted by the summarizer into the `Verdict`, archived
   alongside as `<pid>.appraisal.json.gz` (and the interpreted list as
   `<pid>.components.json.gz`), and described by an `appraisal` record
   (I.6).

Cost: one extra subprocess per protocol; the appraisal run reruns no
tools (REPLACE appraisers compare bytes). Benefit: the archived artifact
is re-verifiable and re-appraisable by construction, and provision
bundles and attestation packages now have the same shape.

### B.1 Protocol shape

- Term: `lseq (bseq left_path (asp generate_nonce) M) SIG`, where `M` is
  the existing measurement term with `APPR` stripped and `SIG` detached
  (`provision.py`'s strip-APPR-keep-SIG transform yields `lseq M SIG`).
  **Spike finding:** the first draft, `lseq (asp generate_nonce) (...)`,
  placed the nonce as initial evidence of the measurement splits, and
  `bseq both_paths` copies initial evidence into every branch — the l1a
  fixture produced **four** nonce events (one value) and four
  `nonce_appr` verdicts. `left_path` (`Impl.v`: left branch gets the
  evidence, right branch gets `mt_evc`) keeps exactly one nonce event;
  `M` receives empty initial evidence; `SIG` still covers the nonce
  slot. Ordering inside one run adds nothing (B.6 rationale), and under
  section G the challenge package `P1` sits beneath `generate_nonce` in
  the left branch, which is where `nonce_appr` reads `expected_b64`.
- `asp_args.json` gains `generate_nonce: {nonce_targ: {asp_targid:
  "nonce_targ", bytes: 32}}` — the args ride in the evidence type and
  reach the companion appraiser.
- Session: `ASP_Types.generate_nonce = {FWD: EXTEND, _BODY: 1, EvInSig:
  NONE}`, `ASP_Types.nonce_appr = {FWD: REPLACE, _BODY: 1}`,
  `ASP_Comps.generate_nonce = nonce_appr`.
- Appraisal run (B.0): `nonce_appr` checks **well-formedness only** —
  length equals `bytes`, not all-zero — because without a pre-registered
  expectation there is nothing else to check. When an `expected_b64`
  arg is present (section G) it additionally requires equality. Its
  verdict appears as a normal `ComponentResult` with `targ_id =
  "nonce_targ"`.
- Spike item: protocols using `bpar`/`bseq` splits — confirm the nonce
  evidence reaches the `sig` branch under the split spec the terms use
  (`ALL`/`NONE`), so the signature covers it in every protocol shape
  pybb generates.

### B.2 Identity derived from the signed slot

- `N` = the `generate_nonce` output, located by laying the evidence type
  out against `RawEv` (`ledger.slot_layout`: EXTEND prepends, REPLACE
  consumes, splits left then right). With the B.1 term it is **slot 1**,
  right after the signature (spike: `[sig, nonce, hash×4]`). pybb
  requires exactly one `generate_nonce/nonce_targ` event and that the
  layout accounts for every slot before trusting it.
- `nid` = hex(sha256(N)): the suffix of every ledger key for the run and
  the `nonce_id` carried by the `Verdict`. Anyone holding the package
  recomputes it.

### B.3 Ledger keys (immudb KV, `verifiedSet`/`verifiedGet`)

| key | body |
|---|---|
| `nonce/<nid>` | the measurement nonce record (I.2): bytes, `role: measurement`, state, freshness, protocol |
| `evidence/<nid>` | the raw package record (I.3): hashes, slots, assurance, tooling ref, initial `local` locator — `github` locators are appended as `locator/<nid>/<seq>` records by the push (H.2); durability is derived at read time, never stored |
| `appraisal/<nid>/1` | the live appraisal package (B.6, I.6) |
| `nonce/<anid>` | the appraiser's nonce, `role: appraisal`, `for_nid` |
| `verdict/<nid>` | `{passed, failing_targ_ids, components_sha256, appraisal_seq: 1, assurance levels}` |

All five are written in **one batch** (`execAll`) — together with the
`local` locator records for the appraisal and components blobs — so a
run is either fully in the ledger or absent. Later audits (B.5) append
`appraisal/<nid>/<seq>` records rather than rewriting. The SQL mirror
`attestation_records` (section A) is written in the same batch for
external queries. `nid` indexes the whole chain, and `immuclient get
nonce/<nid>` is the entry point for anyone outside pybb.

### B.4 Push after the run

In `_attest`, after the measurement run is archived (B.0) and the
appraisal run has produced the components: structural check (B.2),
derive `nid`, `verifiedGet nonce/<nid>` — **present means a replayed or
duplicated package**: the Verdict fails with `error = "duplicate nonce
<nid>"` and nothing is written. Otherwise write the batch. `Verdict`
gains `nonce_id` and `ledger_ref`. A ledger outage is a Verdict error
(fail closed) with a warn-only switch for demos.

Filesystem touchpoints: the archived raw package under `evidence/`,
which contains `N` as a signed slot and **is** the evidence artifact, and
the archived appraisal response beside it. The measurement request
carries no nonce (it is generated inside the run); the appraisal request
carries the raw package as `EVIDENCE`, as `verify_bundle`'s does today.

### B.5 Later verification: re-appraise from the ledger

`appraise_record(client, protocol, ledger, nid)` (or `--latest pid`)
is an **appraisal run in audit mode** (B.6) over a package fetched from
the ledger:

1. `verifiedGet` the run's keys; require they exist and agree on `nid`.
2. Fetch the raw package via the evidence record's locators in order
   (local path, then GitHub blob); require `sha256 == blob_sha256`.
3. Structural: innermost event is `generate_nonce/nonce_targ` and
   `sha256(b64decode(RawEv[nonce.slot])) == nid`.
4. Run the appraisal term of B.6 over the package (the same term the
   live appraisal used), interpret via the summarizer, archive the
   signed appraisal package.
5. Commit an `appraisal` record with `mode: audit` (I.6): the checks
   above as booleans, the appraiser nonce, the binding hash, whether the
   verdict agrees with `verdict/<nid>`, and the tooling reference (B.8).
   Disagreement with the recorded verdict is surfaced, never re-decided.

### B.6 Appraisal runs are themselves signed and nonce-bound

Every appraisal — the live one in B.0 and every later audit — produces
its own Copland package, so "who judged what, when" is evidence too, not
just a pybb log line. Term for the appraisal run (`EVIDENCE` = the raw
package):

```
lseq (bseq (ALL, ALL) (asp hashevidence) APPR)
     (lseq (asp generate_nonce) SIG)
```

- `bseq both_paths` hands the raw package to both branches. Left:
  `hashevidence` emits sha256 over the flattened package bytes — the
  **binding** of this appraisal to exactly that package. Right: `APPR`
  produces the verdict slots. **Spike-confirmed:** with `hashevidence`
  typed `REPLACE` in the appraisal session the left branch is one slot,
  and that slot equals the raw package's `rawev_sha256` exactly. The
  appraisal package of the l1a fixture lays out as `[sig, appraiser
  nonce, binding, sig_appr, nonce_appr, goldenbytes_appr×4]`.
- **Interpreting the appraisal package:** the verified summarizer
  type-checks only a pure appraisal structure and refuses the B.6
  package as a whole. pybb therefore hands it the `APPR` branch alone —
  the right child of the inner split with its RawEv slots, located by
  `slot_layout` (structural reading, B.9) — and the summary is identical
  to an APPR-only run's (spike-verified). Helper: `appraisal_branch()`
  in `ledger.py` (step 3).
- `generate_nonce` then adds the **appraiser's nonce** (`anid`, same
  derivation as `nid`), and `SIG` signs everything: `[sig | anid-nonce |
  hash | verdicts…]`. Signature binds appraiser nonce, binding hash, and
  verdicts together. (Today the appraiser and attester sign with the same
  demo RSA key; a distinct appraiser key is part of the key-custody
  follow-up and changes nothing structural here.)
- Why the appraiser nonce comes **after** `APPR`, unlike the measurement
  run: `APPR` replaces what it appraises, so a nonce generated first
  would be turned into a `nonce_appr` verdict (right branch) and folded
  into the `hashevidence` digest (left branch) — its bytes would survive
  nowhere, no `anid` could be derived, and the binding hash would become
  a salted digest no auditor can recompute. Generated after `APPR` it
  stays in clear under the signature. Its purpose is uniqueness: RSA
  PKCS#1 v1.5 signatures are deterministic, so without it two appraisals
  of the same package would be byte-identical. Ordering inside one run
  adds nothing — `lseq` fixes order and `SIG` binds atomically. A
  relying-party challenge *as initial evidence* of an appraisal run is
  the section G pattern, not this term.
- The appraisal package is archived beside the raw package as
  `<pid>.appraisal.json.gz`, pushed to the evidence repo like any blob
  (locator `target: appraisal`), and described by an `appraisal` record
  (I.6). The appraiser nonce gets a `nonce` record with `role:
  appraisal` and `for_nid`, so every nonce the appraiser ever produced is
  in the ledger and subject to the duplicate check.

Verifying an appraisal package later (an audit of the audit) is
**CVM-native only**: `TERM = APPR` over the appraisal package with an
audit session mapping `hashevidence → goldenbytes_appr` (golden = the
evidence record's `rawev_sha256`, injected into the event's args exactly
as `_inject_goldens` injects `golden_b64`), `generate_nonce →
nonce_appr`, `sig → sig_appr`, and each appraiser ASP → a pass-through
companion (`magic_appr`: an unconditional pass, spike-confirmed). pybb
then reads the per-event verdicts and compares them with the recorded
components (a structural comparison, not a judgment). pybb performs no
signature verification and no nonce comparison itself — see B.9.
**Spike-confirmed** on the l1a fixture: the audit passes untampered; a
flipped byte in the binding slot fails `sig_appr` and `goldenbytes_appr`;
a zeroed appraiser nonce fails `sig_appr` and `nonce_appr` — all judged
inside the CVM. **Caveat:** the verified summarizer refuses the audit
evidence shape (appraisal of appraisal nodes), so audit-of-audit verdicts
are read by `slot_layout` (one REPLACE slot per appraiser event) and the
`appraisal` record carries `interpreter: legacy-walker`; summarizer
support for that shape is a copland-evidence-tools follow-up.

### B.7 Assurance levels: label every package, refuse silently weak ones

pybb computes an `assurance` level from the **package as produced**,
never from configuration, and records it on every evidence and appraisal
record:

| level | meaning | typical source |
|---|---|---|
| `signed+nonce` | `sig` slot present and verified at appraisal; `generate_nonce` event present | default for live measurement and appraisal runs |
| `signed` | `sig` present, no nonce | legacy provision bundles; protocols run before `generate_nonce` was added |
| `nonce` | nonce present, no `sig` | protocols whose session has no `sig` companion |
| `none` | neither | readiness probes, tool-only validation runs |

`freshness` is orthogonal (`post-hoc` now, `pre-registered` under G,
`none` when there is no nonce). The verdict record carries both the
evidence package's and the live appraisal package's levels.

Policy, in `LedgerConfig`:

- `min_assurance` (default `signed+nonce`): a run below it is **refused
  at commit** — the Verdict fails with `error = "assurance <level> below
  minimum"` — unless the protocol is listed in `assurance_exceptions`
  with a reason. Excepted runs commit normally and carry
  `exception_reason` on the evidence record, so the lower assurance is
  explicit in the ledger rather than inferred.
- Readiness (the episode's first verdict) reports every protocol whose
  configuration cannot reach `min_assurance` (missing `sig` companion,
  missing `generate_nonce`) before any attestation runs, so a
  misconfiguration is a configuration failure, not a quietly weaker
  record.
- SQL mirror gains `assurance` and `freshness` columns; `immuclient` /
  SQL can list every record below a level.

### B.8 Tooling identity: measured only by the CVM, on a configurable cadence

The binaries that produce a verdict — the CVM, the summarizer, the ASPs
(which embed the verifying public key) — are themselves measured only by
Copland, never by pybb. pybb never hashes or inspects a tool binary.

- **Blessing.** The protocol `attestation_tools` measures with `hashfile`
  the CVM binary, the summarizer binary, every ASP binary listed by any
  configured protocol's manifest, and the public key file. Provisioning
  it (APPR stripped, SIG kept, bundle stored, goldens extracted) is the
  deliberate act of trusting a build of the stack; it is repeated when
  asp-libs or the CVM is rebuilt. The bundle gets a `bundle` record.
- **Cadence.** `LedgerConfig.tooling.measure`:

  | value | behaviour |
  |---|---|
  | `at_provisioning` (default) | tools are measured only by the provisioning run; nothing measures them again until re-provisioning |
  | `every_episode` | at episode start the protocol runs through the normal two-run pipeline (B.0, B.6) as a `tooling` blackboard entry; its verdict is CVM-appraised against the blessing; routes on that entry decide what a failure means; measurement and appraisal entries proceed independently |
  | `every_run` | the same before each protocol run; available, expensive, not recommended |

  `LedgerConfig.tooling.protocol_id` names the protocol (`attestation_tools`;
  null disables tooling tracking). There are no other tooling fields.
- **What runs record.** Evidence and appraisal records carry
  `tooling: {kind: bundle, ref: <bundle sha256>}` under the default, or
  `{kind: run, ref: <nid of the episode's/run's tooling run>}` under the
  cadences. There is no pybb-side check field. The binaries' hashes are
  one hop away in signed Copland evidence.
- **Implementation note.** `ledger_tooling.py` reuses the tool registry
  and `build_tools_protocol_dir` of `tools.py` (the 2026-07-30 note there
  that kept the attestation stack out of scope is superseded by this
  decision). The blessing bundle is a nonce'd signed package keyed
  `bundle/<nid>` (point 4); the `tooling.ref` is the bundle file's
  sha256.
- **Meaning, stated plainly.** Under `at_provisioning` a record says
  "this blessing was in force when the run happened"; it does not say
  the binaries were unchanged at run time, since nothing measured them
  then. `every_episode` buys that statement for one extra pair of CVM
  runs per episode. The tools measuring the tools remain circular
  (drift detection and provenance, not a root of trust); a hardware
  root of trust (`sig_tpm`) is a separate follow-up.

### B.9 Division of labour: what pybb may and may not do with evidence

Two rules, stated once and applied everywhere in this plan:

1. **pybb identifies and describes; the CVM judges.** pybb may hash
   evidence bytes to identify and index them (`nid`, `anid`,
   `blob_sha256`, `response_sha256`, `rawev_sha256`, `content_sha256`)
   and may read evidence structure to describe it (slot indices, event
   names, the `assurance` label, agreement between two verdict lists).
   pybb makes **no cryptographic or appraisal judgment** about any
   package: no signature verification, no nonce comparison, no golden
   comparison, no hashing of tool binaries. Those happen only inside
   the CVM, through `sig_appr`, `nonce_appr`, `goldenbytes_appr` and
   their peers, and are read back through the verified summarizer.
2. **pybb supplies expectations; the CVM compares.** Every value the
   CVM checks against — a golden, an `expected_b64` nonce (section G),
   a binding hash for an audit (B.6) — is placed by pybb into the
   event's args in the (unsigned) evidence type, the `_inject_goldens`
   pattern, and the comparison is the companion ASP's verdict. pybb
   never short-circuits a comparison it could have asked the CVM to
   make.

Consequences already reflected above: nonces are generated only by
`generate_nonce` (never by pybb); tool identity comes only from
`attestation_tools` evidence (B.8); audits of appraisal packages are
CVM-native (B.6); the ledger's duplicate-nonce refusal (B.4) is ledger
policy over history, which the CVM cannot see, and is the one check
pybb owns outright.

## C. Cross-repo prerequisites and the spike

- **asp-libs** (done, uncommitted on the `hamr-asps` checkout): two small executables on existing patterns.
  `generate_nonce` (EXTEND): read `bytes` from args (default 32), draw
  from the OS CSPRNG (`openssl::rand` is already a dependency), emit the
  raw bytes as its single output slot. `nonce_appr` (REPLACE, on the
  `hashfile_appr` pattern): pass iff slot length equals `bytes` and the
  slot is not all-zero; if `expected_b64` is in args, also require byte
  equality. Both added to the manifests' `ASPS` lists pybb generates.
  No file, environment, or network access in either.
- **rust-am-lib**: no change (the nonce is an ordinary `asp_evt`; the
  `et_size` discrepancy for `nonce_evt` is irrelevant to this design).
- **Spike — done 2026-11-17** on `temp_control_aadl_slang_l1a` with the
  real CVM (`asp_bin` = asp-libs `target/release`). Results:
  1. `lseq generate_nonce (bseq both_paths …)` → 4 nonce copies; the
     B.1 term (`bseq left_path`) → exactly one, at slot 1. Layout
     (`slot_layout`) accounts for every slot in all packages seen.
  2. `sig` covers the nonce slot; `nonce_appr` and the four
     `goldenbytes_appr` verdicts attribute by `asp_targid` through the
     verified summarizer.
  3. B.6 appraisal term runs; `hashevidence` REPLACE → one slot equal to
     the raw package's `rawev_sha256`.
  4. The summarizer accepts the extracted `APPR` branch and its summary
     equals an APPR-only run's over the same package (verdict
     reproducibility).
  5. CVM-native audit of the appraisal package works with `magic_appr`
     pass-through; tampered binding and zeroed appraiser nonce are
     caught by the right appraisers. The summarizer refuses this shape;
     verdicts are read by slot layout.
  Scripts: scratchpad `spike_nonce{,2,3}.py` (not part of the repo).
  Manifests must list `generate_nonce`, `nonce_appr`, `hashevidence`
  (and `magic_appr` for audit sessions) — wired in step 3.

## D. Push: evidence and bundles to the ledger (pybb only)

- In `make_attestation_predicate`, after `_archive` returns a path and
  interpretation is done: the one-batch write of B.3/B.4 (measurement
  nonce, appraiser nonce, evidence, appraisal, verdict — all keyed by
  `nid`), preceded by the duplicate check. `Verdict` gains `nonce_id` and `ledger_ref`. Failure to reach
  the ledger is a Verdict `error` (fail closed), configurable to
  warn-only for demos.
- Provision bundles: `provision.py`'s bundle write gets a `kind=bundle`
  record; `verify_bundle` reports whether the bundle on disk matches its
  ledger record (`BaselineReport.ledger_ok`).
- GitHub locators: produced by the per-archive-directory push into the
  evidence repo (section H.2) — `{repo, commit, path, git_blob_sha}` from
  `git rev-parse HEAD` and `git hash-object` on the committed blob.
  `/evidence/` stays gitignored in pybb; the evidence repo is separate.
- `examples/ledger_push.py <archive_dir | bundle>`: the push (H.2).
  Backfill is limited to **legacy bundles** (signed, no nonce →
  `bundle/sha256:…` records): today's `evidence/2026*` archives are
  post-appraisal packages (B.0 finding) with no signed bytes and no
  nonce, so they cannot become evidence records and are left as they are.

## E. Retrieve and appraise from the ledger (pybb only)

- `ledger.fetch(nid) -> (records, evidence_package)`: `verifiedGet`
  the run's keys plus locator records, then resolve bytes via the
  locators in order: local path, GitHub blob (`gh api
  repos/{repo}/git/blobs/{sha}` or raw URL). Refuse if
  `sha256(bytes) != blob_sha256`.
- `appraise_record(client, protocol, ledger, nid) -> LedgerAppraisal`:
  the B.5 procedure — generalizes `verify_bundle`'s APPR-only run
  (`TERM = APPR`, `EVIDENCE = fetched package`, session carrying the two
  nonce ASPs); response interpreted by the summarizer. Report fields as
  in B.5; truthy iff all hold.
- `examples/appraise_from_ledger.py <nid | --latest pid>` prints
  the chain: nonce → evidence → live appraisal → verdict → fresh audit
  appraisal (signed, nonce-bound), with immudb tx ids so a reader can cross-check in
  `immuclient`.
- Blackboard: `ledger_request(nid)` = `{"ledger_nonce": nid}` routes the
  predicate to `appraise_record` instead of a live run, so a tier can be
  "re-appraise what the ledger holds" (audit rung). The Verdict is truthy
  iff the verified reads, byte and nonce-id checks, and the fresh signed
  appraisal all hold; an audit that disagrees with the recorded verdict
  is a failing Verdict whose `error` says so.

## F. Tests, docs, ops

- Unit (no server): record canonicalization and `nid` derivation from a
  package; structural check of the innermost `generate_nonce` event;
  `FileLedger` chain and tamper detection; duplicate-`nid` refusal;
  pointer parsing.
- Integration, marker `ledger` (skipped unless `PYBB_IMMUDB=1` and the
  server answers): one-batch commit and `verifiedGet` round trip,
  tampered-value detection via client state, SQL mirror query. Marker
  `cvm` + `ledger`: full run with `generate_nonce` → commit → fetch →
  `appraise_record` passes; re-pushing the same archive → duplicate
  nonce error; mutated archived bytes → `bytes_match` false; mutated
  nonce slot → `signature_ok` false.
- Ops: `scripts/immudb_dev.sh` installs/starts the Homebrew service
  (`brew install immudb && brew services start immudb`), rotates the
  default admin password, creates db `pybb` and a non-admin user, and
  (optionally) a server signing key. `tests/conftest.py` gains an
  `immudb_server` session fixture that launches an ephemeral binary
  (temp dir, free port) when `immudb` is on PATH and skips the `ledger`
  marker otherwise. Evidence repo: private, `main`
  protected against force-push. INSTALL.md gains a "ledger (optional)"
  section; `docs/ledger.md` documents the record schema, keys,
  `immuclient` recipes, the push cadence, and the restore procedure
  (H.4). A restore drill (H.4 steps 1–6 into a scratch instance) is part
  of the integration suite under the `ledger` marker.

## G. Two-run pre-registration: challenge freshness (planning, 2026-11-18)

**STATUS: plan only; nothing implemented.** Opt-in upgrade of a run's
guarantee from `freshness: post-hoc` (B) to `freshness: pre-registered`.
Valid whether the attester is remote or a separate process on the same
host. Sections A–F, H and I need no schema change; what changes is listed
in G.6.

### G.0 What it adds, and what it does not

Under B the appraiser first learns a run's nonce from the package itself,
so a replayed or precomputed package is indistinguishable by the nonce
(binding, uniqueness and ordering hold; freshness does not). Under G the
appraiser **generates and records the nonce before the attester runs**,
hands it over as initial evidence, and the CVM's `nonce_appr` judges that
the package carries exactly that nonce. The appraiser's knowledge of `N`
is now independent of the package, which is what freshness needs. Still
out of scope: a distinct appraiser signing key (today appraiser and
attester use the same demo RSA key, so the challenge signature proves
origin only by process separation) and multi-place terms (`@P1`), which
this design accommodates but does not exercise.

### G.1 Run 1 — the challenge

Executed by the appraiser (pybb) through the CVM, no measurements:

```
lseq (asp generate_nonce {asp_targid: nonce_targ, bytes: 32,
                          requested_protocol: <pid>, requester: <appraiser_id>,
                          issued_at: <RFC 3339>}) SIG
```

- `generate_nonce` draws `N`; its args carry the **request metadata**, which
  rides in the (unsigned) evidence type and is also recorded in the nonce
  record. `SIG` at the appraiser's place signs `N`: the challenge package
  `P1 = [sig_a, N]` is the appraiser's signed statement "I am challenging
  protocol `<pid>` with this nonce, now".
- `nid = sha256(N)` as everywhere. `P1` is archived as
  `<pid>.challenge.json.gz` and is a blob like any other (locator target
  `challenge`).
- Spike item: the CVM's `generate_nonce` ignores unknown args today; the
  CVM must accept the extra arg keys in the term (they are opaque JSON) —
  expected to pass, since `hashfile` args already carry arbitrary keys.

### G.2 Issue — the ledger write that makes it a challenge

Before run 2 pybb commits, in one batch:

| key | body |
|---|---|
| `nonce/<nid>` v1 | `{state: issued, freshness: pre-registered, role: measurement, nonce_b64, nonce_bytes, protocol_id: <pid>, requested_protocol: <pid>, requester: <appraiser_id>, issued_at, expires_at, challenge_sha256: sha256(canonical P1)}` |
| `locator/<nid>/1` | the challenge blob, `target: challenge`, local path |

The immudb transaction id and timestamp of this batch are the witness that
the nonce and the request existed before any measurement; the evidence
record written later carries `issued_tx` so an auditor can check the order
without the journal. `verifiedGet` after the write proves inclusion as for
every batch.

### G.3 Run 2 — the attestation, challenged

```
EVIDENCE = P1 (with expected_b64 injected, see below)
TERM     = lseq (bseq left_path (asp NULL) M) SIG
```

- `P1` is the request's initial evidence (the `build_request` seam). The
  measurement term no longer generates a nonce: `M` is the protocol's
  measurement term with APPR stripped and SIG detached, as in B.1.
- `bseq left_path (asp NULL) M`: the left branch keeps `P1` unchanged
  (`NULL` is Copland's identity ASP, already used by provisioning as
  `_NULL_ASP`), the right branch measures with empty initial evidence —
  the same device B.1 uses to avoid the spike's "nonce copied into every
  branch" finding. `SIG` at the attester then covers `P1` (its appraiser
  signature and `N`) together with every measurement.
- Before dispatch pybb injects `expected_b64 = base64(N)` into the
  `generate_nonce` event's args **in `P1`'s evidence type**. This is the
  `_inject_goldens` pattern (B.9 rule 2): pybb supplies the expectation,
  the CVM compares. `nonce_appr` already implements the check (section C).
- Spike items: `NULL` accepted as a `bseq` branch with evidence flowing
  through unchanged; the summarizer type-checks a package whose innermost
  events are `sig` (appraiser) over `generate_nonce`; `sig_appr` over the
  appraiser's signature passes with today's shared demo key.

### G.4 Appraise, commit, consume

The appraisal run is B.6 unchanged (`EVIDENCE` = the raw package of run 2,
whose `P1` subtree already carries `expected_b64`). The verified summary
then contains `nonce_appr` = equality with the registered nonce,
`sig_appr` for the **appraiser's** signature over the challenge and
`sig_appr` for the attester's signature over the run.

Commit (one batch, as B.3/B.4) with two differences:

- `nonce/<nid>` **v2** `{state: bound, evidence_tx}` replaces the B.3
  "committed" state; `commit_run` accepts a pre-registered nonce **only if
  its latest version is `issued`, unexpired, for this protocol, with
  `expected_b64` equal to the package's nonce slot**, and refuses otherwise
  (`bound`/`consumed` = replay; `expired` = stale challenge; mismatch =
  wrong challenge). The B duplicate rule (refuse any existing nonce) applies
  when the nonce record is absent or not `issued`.
- after the live appraisal pybb writes `nonce/<nid>` **v3** `{state:
  consumed}`; pybb never dispatches a consumed or bound nonce again.
  Versions are new values of the same key (immudb keeps history;
  `immuclient history nonce/<nid>` shows issued → bound → consumed; the
  FileLedger appends a line and `_latest` moves).

Expiry is pybb policy, like duplicate refusal: `expires_at = issued_at +
LedgerConfig.challenge_ttl` (default 1 h). A challenge found expired at
commit is marked `nonce/<nid>` `{state: expired}` and the run is refused
(fail closed). Audits (B.5) re-inject `expected_b64` from the nonce
record before their appraisal run; the audit's `nonce_wellformed` then
reads as nonce **equality**, not just well-formedness.

### G.5 Records (additions to section I, all additive within v1)

- `nonce`: `state` gains `issued | bound | consumed | expired` (B's
  `committed` stays for post-hoc runs); new optional fields
  `requested_protocol`, `requester`, `issued_at`, `expires_at`,
  `challenge_sha256`, `evidence_tx`.
- `evidence`: new optional `issued_tx` (the tx of nonce v1) and
  `challenge_sha256`; `freshness: pre-registered`.
- `locator.target` gains `challenge`.
- `appraisal`: unchanged; its `nonce_appr` component now means equality.
- Assurance is unchanged (`signed+nonce`); freshness is the orthogonal
  label that moves. SQL mirror: `freshness` column already exists.

### G.6 Code changes

| module | change |
|---|---|
| `ledger.py` | `NonceRecord` fields/states above; `commit_run` state-aware acceptance (G.4); `Ledger.set_nonce_state(nid, state, **fields)` writing a new version; `EvidenceRecord.issued_tx/challenge_sha256`; `Locator.target` `challenge` |
| `ledger_immudb.py` | nothing structural; `get_record` already returns the latest version; add `versions(key)` via `history()` for audits/CLI |
| `ledger_runs.py` | `challenge_term(pid, requester, issued_at)`, `issue_challenge(client, lp, ledger, config) -> Challenge(P1, nid, tx)`, `challenged_measurement_request(lp, P1_with_expected)`, `inject_expected_nonce(et, nonce_b64)` (mirrors `inject_binding_golden`); `attest_with_ledger` branches on `config.freshness`; audits re-inject from the record |
| `client.py` | `ProtocolDir.build_request(initial_evidence=None)` (the seam G has pointed at since the first draft) |
| `knowledge_sources.py` | none beyond passing `config` (already done) |
| `readiness.py` | report `freshness` per protocol: `pre-registered` requires the `NULL` ASP acceptance spike to have passed and `sig` present |
| `ledger_repo.py` | `challenge` blobs push like any blob; `verify_mirror` already hashes every blob a record names |
| `examples/appraise_from_ledger.py` | print the nonce lifecycle (versions) in the chain |
| asp-libs / rust-am-lib / CVM | **no changes**: `generate_nonce` and `nonce_appr` (with `expected_b64`) already exist; `NULL` and `SIG` are built in |

Configuration: `LedgerConfig.freshness: Literal["post-hoc", "pre-registered"]
= "post-hoc"` (per-protocol override via `freshness_overrides: {pid: level}`
for a gradual rollout) and `challenge_ttl: str = "1h"`.

### G.7 Cost

Three CVM invocations per protocol run instead of two; the challenge run
is milliseconds (one ASP and a signature). One extra ledger batch per run
(the issuance) plus one version write (consume). Archive gains one small
blob per run.

### G.8 Tests and spike

- Spike (half a day, before coding): G.1 extra args accepted; G.3 `NULL`
  branch with `P1` flowing through; summarizer accepts the challenged
  package shape; `nonce_appr` equality pass/fail with injected
  `expected_b64`; APPR-only re-run with re-injected expectation.
- Unit (canned packages from the spike): challenge term and record;
  `commit_run` acceptance matrix (issued/bound/consumed/expired/
  mismatch/absent); versions in FileLedger; audit re-injection.
- Integration (real CVM, l1a and the Rocq verification protocol):
  challenged run passes; re-dispatching the same challenge is refused as
  replay; a package from an old challenge presented against a new one
  fails `nonce_appr` (judged in the CVM); expired challenge refused;
  `immuclient history nonce/<nid>` shows the lifecycle.

### G.9 Decisions to make before coding

1. **Default freshness**: keep `post-hoc` as the default and make
   `pre-registered` opt-in per protocol (recommended for a gradual
   rollout), or flip the default once the spike passes?
2. **Challenge TTL**: 1 h default? Long tool runs (Rocq verification) need
   minutes, not hours; a tight TTL narrows the window a stolen challenge
   is usable.
3. **Appraiser signature on the challenge**: include `SIG` in run 1
   (recommended: the challenge is then provably the appraiser's), knowing
   it is the same demo key as the attester's until the key-custody
   follow-up lands.
4. **Appraiser nonce of the appraisal run**: leave it post-hoc (its job is
   uniqueness), or pre-register it too for symmetry?
5. **Request metadata in args**: `requested_protocol`, `requester`,
   `issued_at` as proposed; anything else the relying party should
   state up front (e.g. a `purpose` or episode label)? Note the args are
   unsigned type data, mirrored into the signed nonce record.
6. **Attester receipts (speculative; not for the first G change set).**
   Should the attester place be allowed to write to the ledger at all?
   - *Case for:* two-way non-repudiation. Today the ledger is the
     appraiser's account of what the attester produced; if the attester
     commits a receipt for its signed package *before* handing it over,
     the appraiser cannot later deny receipt, suppress a run, or alter
     what was judged, because the attester's statement exists
     independently and first. Relevant only once appraiser and attester
     are parties who do not fully trust each other.
   - *Case against:* every ledger guarantee assumes one writer applying
     one policy (duplicate refusal, assurance minimum, the G lifecycle).
     An attester with write access could write run-shaped records that
     were never appraised, flood nonces to force collisions, or race the
     appraiser's commit. Its genuine testimony — the signature over the
     measurements — is already in the package and cannot be forged or
     altered by the appraiser, so receipts add a witness and a timestamp,
     not evidence.
   - *If wanted, the shape:* keep run records single-writer and let the
     attester write exactly one kind, `receipt/<appraiser_id>/<nid>`:
     `{package_sha256 (= rawev_sha256 or blob hash), nid, attester_id,
     signature over those fields, created_at}`, written with immudb's
     key-must-not-exist precondition so it can never overwrite. The
     appraiser's `commit_run` treats receipts as untrusted input: it
     cites the receipt's tx id on the evidence record (`receipt_tx`) and
     `verify_mirror`/`reconcile` check that the receipt's hash matches the
     package the appraiser recorded. Order in the ledger then shows both
     parties' statements.
   - *immudb feasibility:* straightforward — one database user per place
     (permissions are per database, so the key-prefix discipline is
     pybb's), the shared TLS instance of decision 3 reachable from the
     attester, each client keeping its own verified state. Moderate work
     on the pybb side (receipt record kind, precondition writes,
     commit-time cross-check, reconcile rule).
   - *Recommendation:* defer. Not needed for a single organization; revisit
     when a second party's word should not depend on the appraiser's
     ledger alone.

## H. Evidence repo: durable blobs, ledger mirror, and restore

Decisions 2 and 5 (resolved): the ledger is **pointer-primary** — no
evidence bytes inside immudb — and a separate GitHub repository (private
by the original decision; made public on 2026-11-18, see the status note)
— **any repository the operator chooses**: `LedgerConfig.
evidence_repo` (env `PYBB_EVIDENCE_REPO`) names a local clone and the
locators' `repo` slug is read from its `origin` remote; nothing in the
code assumes a name — is the durable store
for the blobs *and* the offsite mirror of the ledger itself. immudb
holds the verifiable index; the repo holds everything needed to rebuild
it. Records are ~1–2 KB, so immudb needs no retention/truncation; the
repo grows by the gzipped evidence (~80 KB per archive directory today, 87.5 MB
for the whole history so far).

### H.1 Repository layout (content-addressed, append-only by convention)

```
blobs/<sha256>.json.gz              evidence packages and provision bundles
ledger/journal.jsonl                one line per immudb tx, in tx order:
                                    {tx, ts, keys:[...], content_sha256:{key: sha}}
ledger/records/<nid>/{nonce,evidence,verdict}.json
ledger/records/<nid>/locator-<n>.json, appraisal-<seq>.json
ledger/bundles/<nid>.json
ledger/state/<tx>.json              immudb state at each push:
                                    {db, tx_id, tx_hash, signature?, signing_pub_fp?}
ledger/backups/<from_tx>-<to_tx>.bkp   immuadmin hot-backup segments (H.3)
runs/<archive_dir>/manifest.json    human index: protocol → nid → blobs (push-time grouping, not a ledger concept)
```

Blob and record files are written with the exact canonical bytes the
ledger holds, so `content_sha256` in the journal verifies a file against
the ledger and vice versa. Nothing under `blobs/` or `ledger/records/` is
ever modified; a correction is a new record. Branch protection on `main`
(no force-push) is part of the ops setup.

### H.2 Push cadence (extends D)

1. Per run: ledger batch commit (B.4) with the `local` locator only.
2. Per archive directory, after its last run: `ledger_push.py <archive_dir>` copies
   new blobs and records into the clone, appends the journal lines for
   every tx since the last push, writes `ledger/state/<tx>.json` (the
   server's current state, signed if the server runs with
   `--signingKey`), appends a hot-backup segment (H.3), updates the
   `runs/<archive_dir>/manifest.json`, and makes **one git commit** — a consistent snapshot
   — then pushes. On success it appends a `github` locator record per run
   (commit SHA, path, git blob SHA), making those runs `durable`.
3. `ledger_reconcile.py`: lists runs without a `github` locator, retries
   the push, verifies remote blobs by hash on request, and compares the
   live server state against the latest mirrored state (a rolled-back or
   rewritten server is caught here).

### H.3 Two complementary backups of the ledger, both in the repo

| | JSON mirror (`ledger/records` + `journal.jsonl`) | hot-backup segments (`ledger/backups/`) |
|---|---|---|
| produced by | pybb, from its own records | the operator: `immuadmin hot-backup pybb -o seg.bkp` (after `immuadmin login`), handed to `ledger_push.py --backup-segment seg.bkp`; not automated because `immuadmin` holds an interactive login token |
| readable without immudb | yes | no |
| restore result | a **new** ledger with identical content; new tx ids and roots | the **same** ledger: identical tx ids, hashes, proofs |
| old client state still verifies | no (reseeded) | yes |
| guards against | loss of immudb, format or version change, "what was attested" questions with no server at all | loss of immudb, with exact proof continuity |

Each `state/<tx>.json` is an external witness: a GitHub commit pins the
server's root at that tx, so any later instance can be checked against
history by anyone with the repo.

### H.4 Restore procedure (from a chosen commit of the evidence repo)

Preconditions: a clone checked out at the commit to restore from
(normally `main`; any older commit is also a consistent snapshot since
each push is one commit), a fresh immudb server, pybb with the `ledger`
extra.

1. **Verify the mirror before trusting it** —
   `ledger_restore.py verify <clone>`: every `ledger/records` file
   re-hashes to its `content_sha256` in the journal; every blob a record
   points to exists and matches `blob_sha256`; the journal's tx
   numbers are contiguous; each `state/<tx>.json` signature checks
   against the archived signing public key when present; the git history
   is linear from the first push (and commit signatures verify when the
   pushing account signs).
2. **Exact restore (preferred when the backup segments are present)** —
   `immuadmin database create pybb` is *not* run; instead
   `immuadmin hot-restore pybb -i <segments concatenated in order>`
   creates the database with the original tx ids and hashes. Then
   `ledger_restore.py check <clone>`: `verifiedGet` every key in the
   journal using the **old client state** from the latest
   `state/<tx>.json` — every inclusion and consistency proof must pass.
   This is the proof that the restored instance *is* the mirrored one.
3. **Content restore (when no segments exist, or they fail)** —
   `immuadmin database create pybb`, then `ledger_restore.py replay
   <clone>`: one `execAll` batch per journal line, in order, writing the
   same keys with the same canonical values (so `content_sha256`
   matches) and the same SQL mirror rows; the original tx id is kept in
   a side key `restore/txmap/<new_tx>` → `orig_tx`, never inside a
   record value. The client state file is reset and reseeded from the
   new instance.
4. **Record the restore** — append `restore/<ts>` to the ledger:
   `{source_commit, source_last_state_tx, mode: exact|replay, tx_count}`,
   and push it to the repo on the next push. A restore is itself
   an event the ledger should remember.
5. **Reconcile locators** — `ledger_reconcile.py --verify-all`: for every
   evidence record, resolve at least one locator. On a machine without
   the original `evidence/` directory the `local` locators fail and the
   `github` locators serve; `ledger.fetch` already falls through.
   Optionally re-materialize `evidence/` from `blobs/` for local speed.
6. **Smoke test** — `appraise_from_ledger.py --latest <pid>` on one
   protocol per target family: fetch from the repo, hash-check,
   appraisal-only CVM run, agreement with the recorded verdict.

What restore cannot do: reproduce the *old* root hashes under a content
replay (step 3) — those remain witnessed only by the mirrored states and
git history; and recover anything that was never pushed (runs whose
only locator was `local` on a lost disk) — the reconciler's backlog
count exists so that window is visible, not silent.

## I. Record schema v1

Plain pybb JSON (decision 4: no in-toto envelope for now). Every record
is a JSON object; the stored immudb value is its **canonical form**:
`json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` encoded UTF-8. `content_sha256` (in the journal and
the SQL mirror) is the sha256 of exactly those bytes. Conventions:
hashes are lowercase hex; nonce and evidence bytes are standard base64
with padding; timestamps are RFC 3339 UTC with `Z`; sizes are bytes.

### I.1 Common envelope (every record)

| field | type | meaning |
|---|---|---|
| `schema` | string | `"pybb-ledger/v1"`; additive changes stay v1, breaking changes bump it and readers accept both |
| `kind` | enum | `nonce` `evidence` `verdict` `locator` `appraisal` `bundle` `restore` |
| `nid` | hex | the run's nonce id (null on legacy bundles, absent on `restore`) |
| `created_at` | timestamp | when pybb built the record (immudb's tx time is the authoritative order) |
| `committer_fp` | string | `sha256:<hex>` of the verifying public key pybb trusts (as `verify_baseline.key_identity`) |
| `pybb_version` | string | package version that wrote the record |
| `appraiser_id` | string | opaque, stable id of the pybb installation that wrote the record (random, kept in config; to become the appraiser signing-key fingerprint under the key-custody follow-up). Never a hostname or username; the id→machine mapping lives outside the ledger |

Pydantic models carry the envelope as a base class; `kind` is the
discriminator. Unknown fields are preserved on read (forward
compatibility), never dropped.

### I.2 `nonce/<nid>`

```json
{"schema":"pybb-ledger/v1","kind":"nonce","nid":"3f9a…",
 "nonce_b64":"q4Yd…==","nonce_bytes":32,
 "role":"measurement","for_nid":null,
 "state":"committed","freshness":"post-hoc",
 "protocol_id":"temp_control_aadl_slang_l1a",
 "created_at":"2026-11-17T15:02:11Z","committer_fp":"sha256:9c1e…","pybb_version":"0.1.0","appraiser_id":"ap-4f1c"}
```

`nid == sha256(base64decode(nonce_b64))` is checked on write and read.
`role` is `measurement` (the run's nonce) or `appraisal` (an appraiser
nonce, B.6; then `nid` is the `anid` and `for_nid` names the run it
judged). The nonce record describes the nonce, not its place in the evidence:
the event's `asp_targid` and RawEv slot live on the evidence record's
`nonce` object (I.3). `protocol_id` stays here because under section G
the record is written before any evidence exists.
`state` is `committed` in this plan; section G adds `issued`, `bound`,
`consumed` (as new versions of the same key) and `requested_protocol`,
`issued_at`.

### I.3 `evidence/<nid>`

```json
{"schema":"pybb-ledger/v1","kind":"evidence","nid":"3f9a…",
 "protocol_id":"temp_control_aadl_slang_l1a",
 "term_sha256":"…","session_sha256":"…","manifest_sha256":"…",
 "response_sha256":"…","blob_sha256":"…","blob_bytes":2058,"encoding":"gzip+json",
 "rawev_count":5,"rawev_sha256":"…",
 "signature":{"present":true,"slot":0,"asp":"sig","signer_fp":"sha256:9c1e…"},
 "nonce":{"slot":4,"asp":"generate_nonce","asp_targid":"nonce_targ"},
 "assurance":"signed+nonce","freshness":"post-hoc","exception_reason":null,
 "tooling":{"kind":"bundle","ref":"<sha256 of the attestation_tools bundle>"},
 "locators":[{"kind":"local","path":"evidence/20260731-123205/temp_control_aadl_slang_l1a.response.json.gz","appraiser_id":"ap-4f1c"}],
 "created_at":"…","committer_fp":"…","pybb_version":"0.1.0","appraiser_id":"ap-4f1c"}
```

- The record describes the **raw signed package** from the measurement
  run (B.0), never the appraisal response. It carries no episode, run,
  or sequence fields (open point 5): orchestration lives on the
  blackboard, which links to the ledger via `Verdict.nonce_id`.
- Two content hashes on purpose: `response_sha256` is over the canonical
  JSON of that package — the stable identity of the evidence,
  independent of compression — and `blob_sha256` is over the archived
  bytes exactly as stored (gzip is not reproducible), which is what every
  fetch verifies and what names the blob in the evidence repo.
- `rawev_sha256` is sha256 over the flattened `RawEv` bytes — exactly
  what the `hashevidence` ASP computes — so an appraisal package's
  binding slot (B.6, I.6) is compared to it directly.
- `term_sha256`/`session_sha256`/`manifest_sha256` are over the canonical
  JSON of the ProtocolDir files used for the run, so "same protocol
  configuration" is a hash comparison.
- `signature.slot` / `nonce.slot` are `RawEv` indices recorded at
  commit time so readers need not re-derive evidence layout.
- `assurance` is computed from the package (B.7); `exception_reason` is
  non-null only when the run committed below `min_assurance` via an
  explicit exception.
- `tooling` references the Copland evidence that identifies the
  binaries in force (B.8): the blessing bundle by default, or that
  episode's tooling run under a cadence. Never a pybb-computed hash.
- `locators` holds only what is known at commit time (the local path);
  everything later is a `locator` record. There is **no `durable`
  field**: durability is derived at read time (≥2 locator kinds
  resolve), never stored in an append-only record.

### I.4 `verdict/<nid>`

```json
{"schema":"pybb-ledger/v1","kind":"verdict","nid":"3f9a…",
 "protocol_id":"temp_control_aadl_slang_l1a",
 "passed":false,"components_total":14,"components_failed":1,
 "failing":[{"targ_id":"tempsensor_targ","appr_asp":"goldenbytes_appr","reason":"File contents do not match"}],
 "components_sha256":"…","appraisal_seq":1,
 "evidence_assurance":"signed+nonce","appraisal_assurance":"signed+nonce",
 "interpreter":{"kind":"verified-summary","tool":"copland-evidence-tools"},
 "error":"",
 "created_at":"…","committer_fp":"…","pybb_version":"0.1.0","appraiser_id":"ap-4f1c"}
```

The full `ComponentResult` list is **not** in the ledger (it can reach
tens of KB); it is a third run artifact — `<pid>.components.json.gz`
beside the packages, with locators like any blob — and hashed here. It is
re-derivable from the blob via the appraisal run plus the summarizer.
`appraisal_seq` names the `appraisal` record (I.6) the components came
from — always `1`, the live appraisal. `interpreter` names the tool
only; its identity is covered by the `tooling` reference (B.8), never a
pybb-computed hash. `interpreter.kind` is
`verified-summary` or `legacy-walker`; a failed run has `passed:false`,
empty `failing`, and a non-empty `error`.

### I.5 `locator/<nid>/<seq>`

```json
{"schema":"pybb-ledger/v1","kind":"locator","nid":"3f9a…","seq":1,
 "target":"evidence","blob_sha256":"…",
 "locator":{"kind":"github","repo":"ku-sldg/pybb-evidence","commit":"a1b2…","path":"blobs/<blob_sha256>.json.gz","git_blob_sha":"e5f6…"},
 "verified":true,
 "created_at":"…","committer_fp":"…","pybb_version":"0.1.0","appraiser_id":"ap-4f1c"}
```

A `local` locator carries the writer's `appraiser_id` so a reader knows
whose filesystem the path refers to; the reconciler resolves only
local locators bearing its own id. `target` is `evidence`, `appraisal`, `components`, or `bundle`. `locator.kind` is `local` or
`github` now; future kinds (`oci`, a second git remote) add no schema
change. `verified` records that the pusher re-read the remote bytes and
matched `blob_sha256`.

### I.6 `appraisal/<nid>/<seq>` (replaces the earlier `audit` kind)

One per appraisal run over the run's raw package: `seq 1` is the live
appraisal (B.0), later `seq`s are audits (B.5). Keyed by the evidence
run's `nid`; the appraiser's own nonce is `anid`.

```json
{"schema":"pybb-ledger/v1","kind":"appraisal","nid":"3f9a…","seq":1,
 "mode":"live","anid":"7b2c…",
 "response_sha256":"…","blob_sha256":"…","blob_bytes":1180,"encoding":"gzip+json","rawev_sha256":"…",
 "binding":{"slot":2,"asp":"hashevidence","evidence_hash":"…","matches_evidence":true},
 "signature":{"present":true,"slot":0,"asp":"sig","signer_fp":"sha256:9c1e…","verified":true},
 "nonce":{"slot":1,"asp":"generate_nonce"},
 "assurance":"signed+nonce","freshness":"post-hoc",
 "passed":false,"components_sha256":"…",
 "interpreter":{"kind":"verified-summary","tool":"copland-evidence-tools"},
 "tooling":{"kind":"bundle","ref":"<sha256 of the attestation_tools bundle>"},
 "checks":{"ledger_verified":true,"bytes_match":true,"nid_ok":true},
 "locator_used":{"kind":"local"},
 "agrees_with_recorded_verdict":null,
 "created_at":"…","committer_fp":"…","pybb_version":"0.1.0","appraiser_id":"ap-4f1c"}
```

- `response_sha256`/`blob_sha256`/`rawev_sha256` describe the appraisal
  package itself, with the same meanings as on the evidence record.
- `binding.evidence_hash` is the `hashevidence` slot (sha256 over the
  raw package's flattened `RawEv` bytes). On the live appraisal pybb
  only records it; `matches_evidence` is the `goldenbytes_appr` verdict
  from a CVM-native audit of the appraisal package (B.6) and is `null`
  until one has run. This is what ties an
  appraisal to the exact bytes it judged, independent of the ledger.
- `checks` and `locator_used` are meaningful for `mode: audit`;
  `agrees_with_recorded_verdict` is `null` on the live appraisal and a
  boolean on audits of the raw package.
- `audits_seq` (step 5): `null` when the raw package was judged; the
  audited appraisal's `seq` when this record is a CVM-native audit of an
  appraisal package (B.6). Such a record's `binding` hashes the
  *appraisal* package it judged, its `binding.matches_evidence` is the
  `goldenbytes_appr` verdict over that package's own binding slot, and
  its `interpreter` is `legacy-walker` (the summarizer refuses the
  shape). The live record's `matches_evidence` stays `null`: records are
  immutable, so the judgment lives on the audit record.
- `tooling` references the Copland evidence (B.8) identifying the
  binaries in force for this appraisal; a disagreement between
  appraisals is interpretable only with it.

### I.7 `bundle/<nid>` (legacy: `bundle/sha256:<bundle_sha256>`)

```json
{"schema":"pybb-ledger/v1","kind":"bundle","nid":"5d0e…",
 "protocol_id":"isolette_sysmlv2_rust_props",
 "response_sha256":"…","blob_sha256":"…","blob_bytes":106886,"encoding":"json",
 "golden_ts":"2026-08-19T10:07:00Z","targets":5,"rawev_count":7,
 "signature":{"present":true,"slot":0,"asp":"sig","signer_fp":"…"},
 "nonce":{"slot":6,"asp":"generate_nonce","asp_targid":"nonce_targ"},
 "assurance":"signed+nonce","freshness":"post-hoc",
 "tooling":{"kind":"bundle","ref":"<sha256 of the attestation_tools bundle>"},
 "locators":[{"kind":"local","path":"golden/_bundles/isolette_sysmlv2_rust_props/provision_bundle.json","appraiser_id":"ap-4f1c"}],
 "created_at":"…","committer_fp":"…","pybb_version":"0.1.0","appraiser_id":"ap-4f1c"}
```

Provisioning runs carry `generate_nonce` (open point 4), so a bundle is
a signed package like any other and keys by `nid`; it keeps its own
`kind` because it has no verdict at creation. Legacy bundles (no nonce)
key by content hash with `nid: null`, `nonce: null`, `assurance:
signed`. A `verify_bundle` audit is recorded as an `appraisal` record
under the bundle's key. The `attestation_tools` bundle (B.8) is one of
these; its `tooling` field is null.

### I.8 `restore/<created_at>`

```json
{"schema":"pybb-ledger/v1","kind":"restore",
 "mode":"exact","source_repo":"ku-sldg/pybb-evidence","source_commit":"c3d4…",
 "source_last_state_tx":48211,"tx_count":48211,
 "created_at":"…","committer_fp":"…","pybb_version":"0.1.0","appraiser_id":"ap-4f1c"}
```

`mode` is `exact` (hot-restore) or `replay` (journal replay; then
`txmap` lives under `restore/txmap/<new_tx>`).

### I.9 Repo-side companions (not immudb values)

- `ledger/journal.jsonl` line (one per tx; a run's batch lists all five
  keys):
  `{"tx":48211,"ts":"…","db":"pybb","keys":{"nonce/3f9a…":"<content_sha256>","evidence/3f9a…":"…","appraisal/3f9a…/1":"…","nonce/7b2c…":"…","verdict/3f9a…":"…"}}`
- `ledger/state/<tx>.json`:
  `{"db":"pybb","tx_id":48211,"tx_hash_b64":"…","signature_b64":"…","signing_pub_fp":"sha256:…","captured_at":"…"}`
- `ledger/records/<nid>/` holds the records and a pointer (by hash) to
  the run's three blobs — raw package, appraisal package, components
  list — which live content-addressed under `blobs/` (open point 2).

### I.10 SQL mirror (`attestation_records`)

`key VARCHAR[128] PRIMARY KEY, kind VARCHAR[16], nid VARCHAR[64],
protocol_id VARCHAR[96], passed BOOLEAN (NULL except on verdict/appraisal
rows), assurance VARCHAR[16], freshness VARCHAR[16], blob_sha256
VARCHAR[64], created_at VARCHAR[32] (RFC 3339, sorts lexically),
content_sha256 VARCHAR[64]` — one row per record; `content_sha256` lets a
SQL reader verify a row against the KV value. Indexes on `(nid)` and
`(protocol_id, created_at)`.

Implementation notes (step 4): the KV batch is the ledger (`execAll`,
atomic); mirror rows are written **after** it and are a derived view — a
mirror failure is logged and never undoes the KV tx, and
`ImmudbLedger.rebuild_mirror()` regenerates every row from the KV history.
immudb-py 1.5 quirks met: it cannot bind a NULL parameter (hence two
UPSERT variants), indexed SQL keys are size-capped (hence VARCHAR[128]),
and `txById` returns the tx's keys as a list rather than the tx object.

### I.11 Schema open points (all resolved)

1. *Resolved*: opaque `appraiser_id` on the envelope and on `local`
   locators; no hostname or username anywhere in the ledger.
2. *Resolved*: repo-only, as a third run artifact with the same
   lifecycle as the two packages — written at run time to the archive
   directory as `<pid>.components.json.gz` (canonical JSON, gzipped),
   hashed into `verdict.components_sha256`, given a `local` locator on
   the evidence record (`target: components`), copied to
   `blobs/<sha256>.json.gz` by the push with a `github` locator
   appended, and counted in durability. The ledger never holds the
   list; it stays re-derivable from the raw package.
3. *Resolved*: tooling identity comes only from Copland evidence (B.8):
   an `attestation_tools` protocol measured by the CVM at provisioning
   (default) or on a configurable cadence; evidence and appraisal
   records carry a `tooling` reference to that bundle or run. pybb
   never hashes tool binaries.
4. *Resolved*: provisioning terms get `generate_nonce` first, so a
   bundle has the same shape as a measurement package (nonce,
   measurements, signature), keys as `bundle/<nid>`, carries
   `assurance: signed+nonce` and the `nonce` slot, and every re-blessing
   is a distinct event (deterministic RSA would otherwise make unchanged
   re-provisionings byte-identical — the problem `force_timestamp`
   works around today). Bundle verification ignores non-golden events
   and `extract_golden_slice` slices ordinary EXTEND nodes, so no
   extraction change is expected (spike confirms). The 40 existing
   bundles stay valid as legacy: keyed `bundle/sha256:<hash>`,
   `nid: null`, `assurance: signed`, until re-provisioned.
5. *Resolved*: the ledger carries **no blackboard or orchestration
   concepts** — no episode, run, or sequence fields on any record. It is
   a ledger of Copland runs, keyed and linked by nonce ids and content
   hashes, verifiable by a reader who knows nothing of pybb. The link
   runs the other way: `Verdict.nonce_id` on the blackboard history maps
   every key and episode to its ledger run. Grouping for the evidence
   repo is a push-time detail: the archive directory name (now
   timestamp plus a random suffix, generated when the predicate is
   built, fixing same-second collisions) becomes `runs/<name>/` in the
   repo manifest, which lists the nonce ids it holds; locator paths
   embed it. `protocol_id` stays: it names a Copland protocol
   configuration, with term/session/manifest hashes as its identity.

## J. Open decision: multi-member use of the ledger (deferred 2026-11-18)

Other ku-sldg members can already **read** the public mirror
(`ku-sldg/pybb-ledger`) with nothing more than a clone; `fetch_run`, the
audit scripts and `ledger_restore.py verify` work for anyone. Two things
need a decision before they can **write**:

1. **Repository permissions.** `ledger_push.py` needs write access on
   `ku-sldg/pybb-ledger`, granted to an org team (candidates seen in the
   org: `inspecta-team`, `caseteam`, `case`, `faa-a58`, `honeywell`) or to
   named collaborators. Branch protection on `main` (no force-push, no
   deletion, enforced for admins) does not block ordinary pushes. **No
   grants made yet.**
2. **A ledger they can reach.** The immudb behind the mirror is the
   Homebrew service on the appraiser's laptop, and the repository layout
   assumes **one ledger per repository**: `ledger/journal.jsonl` and
   `ledger/state/` record one transaction sequence, so two independent
   immudb instances pushing to the same repo would interleave tx ids and
   fail `verify_mirror`. Options:
   - **Shared immudb instance** (decision 3's deferred path): one server
     on a lab host, TLS, one database user per appraiser; clients change
     only `LedgerConfig` (host, port, credentials). Each member also needs
     `pip install -e '.[ledger]'`, the ledger ASPs built from asp-libs
     `ledger-asps` with rust-am-lib `ledger-verdict-b64`, and their own
     blessing of their stack (`provision_tools.py`; tooling refs are
     per host by design).
   - **Per-appraiser namespacing in the repo**: `ledger/<appraiser_id>/
     journal.jsonl` and `ledger/<appraiser_id>/state/`, blobs and records
     staying shared and content-addressed. A modest change to
     `ledger_repo.py` (`push_archive`, `last_journaled_tx`,
     `verify_mirror`, `replay`, `reconcile`) and the simpler path when
     members mostly work alone and share results.
   Until one of these lands, a member can run pybb with a ledger of their
   own (FileLedger or own immudb) and read the mirror, but must not push
   into it.

## K. Unified bundle records — schema v2 (planning, 2026-11-18; naming settled 2026-11-19)

**STATUS: implemented 2026-11-19** (`ledger.py`, `ledger_runs.py`, `ledger_immudb.py`, `ledger_repo.py`; v1 records readable via `ledger_v1.py`; schema reference in `docs/ledger_records.md`; database `pybb2`). Replaces the parallel `nonce` / `evidence` /
`verdict` / `appraisal` / `bundle` kinds with **one `bundle` record per CVM run
output**, keeping measurement evidence and appraisal evidence distinct by
*role* and *inputs* rather than by record shape, so that several different
appraisals can be recorded over one measurement, before or long after it.

### K.0 Why

Every CVM run — measurement, appraisal, provisioning, tooling blessing,
and (G) challenge — produces the same thing: a signed, nonce'd package
that pybb archives, hashes, lays out and labels. Section I gave each a
record kind with the same twenty fields and a few extras, plus a separate
`nonce` record carrying the identity those records already embed, plus a
`verdict` record that is a reading of one appraisal package. Writing and
reading five parallel kinds for one run is the onerous part. What must
stay distinct is only *what a package is evidence of*: a measurement is
about the target system, an appraisal is about another package, and one
measurement may be judged many times by different appraisal policies.

### K.1 The record: `bundle/<bid>`

`bid` is the bundle's own nonce id — sha256 of the nonce slot that
`generate_nonce` produced in that run (legacy nonce-less bundles:
`bundle/sha256:<blob hash>`). One record kind, one builder
(`describe_package` already computes most of it):

| field | meaning |
|---|---|
| envelope | as I.1 (`schema: pybb-ledger/v2`, `kind: package`, `created_at`, `committer_fp`, `pybb_version`, `appraiser_id`) |
| `role` | `measurement` · `appraisal` · `provision` · `challenge` (G) |
| `protocol_id` | the protocol configuration the run belongs to (for an appraisal: the protocol it appraises) |
| `term_sha256`, `session_sha256`, `manifest_sha256` | the exact term/session/manifest the CVM ran — for an appraisal these identify the **appraisal policy** (companion map, goldens) |
| `response_sha256`, `blob_sha256`, `blob_bytes`, `encoding`, `rawev_count`, `rawev_sha256` | the package's bytes, as today |
| `nonce` | `{slot, asp, asp_targid, b64, bytes}` — the nonce record folded in: the package *is* the nonce's existence |
| `signature` | `{slot, asp, signer_fp}` |
| `assurance`, `freshness`, `exception_reason` | as today |
| `tooling` | `{kind: bundle|run, ref}` as today |
| `inputs` | list of `{pid, binding_slot, binding_hash}`: the packages this run took as initial evidence — an appraisal names the package it judged (with its `hashevidence` binding), a G measurement names its challenge, a measurement or provision has none |
| `verdict` | **appraisal role only**: `{passed, components_total, components_failed, failing[], components_sha256, components_blob_sha256, interpreter}` — the `verdict` record folded in: a verdict is a reading of one appraisal package and lives with it |
| `appraisal_kind` | appraisal role only, caller-chosen label: `live`, `audit`, or a policy name such as `slices-only`, `tools-only`, `golden-set-2026-11` |
| `state` | `committed` today; G lifecycle (`issued`, `bound`, `consumed`, `expired`) lives on the **challenge** package, since that is the nonce that exists before anything else |
| `locations` | every place the blob is or will be, **stated once at commit**: `[{store: "local", path}, {store: "github:<owner/name>", path: "blobs/<blob_sha256>.json.gz"}, …]` — the local entry is where pybb archived the bytes; each remote entry is derived from configuration and the hash (content addressing fixes the path before any push); the components blob reference inside an appraisal bundle carries the same field |

Appraiser nonces no longer need a record of their own: an appraisal
package's `pid` *is* its appraiser nonce id, with the bytes in `nonce`.

### K.2 Links, keys, and the "many appraisals" query

- `judged_by/<input_bid>/<abid>` — a tiny pointer record written in the
  same batch as an appraisal package, so "every appraisal of measurement
  X" is one prefix scan with no secondary index (the role today's
  `appraisal/<nid>/<seq>` prefix plays). Audits and alternative appraisals
  of the same measurement simply add pointers; nothing is sequenced, the
  ledger's tx order is the sequence.
- `mirror/<state_tx>` — one record per push to a store (decision 7):
  `{store, repo, commit, state_tx, state_hash, journal_from_tx,
  journal_to_tx, blobs, blob_hashes_sha256, skipped[]}`. The ledger's
  witness that every bundle at or below `state_tx` had its records and
  blobs mirrored in that commit; the repo's `ledger/state/<tx>.json`
  holds the same `state_tx`/`state_hash` for cross-checking. The push
  verifies each copied blob against its hash before writing it; blobs it
  could not copy are listed in `skipped` with a reason — the one place
  "pending forever" is stated explicitly.
- No `locator` records: locations live on the bundle (K.1) and nothing
  about a run is written after its batch; the per-push `mirror` record is
  the ledger's only post-run write.
- `restore/<created_at>` — unchanged.
- Kinds drop from seven to four: `bundle`, `judged_by`, `mirror`,
  `restore`.

### K.3 What a run writes

| event | batch |
|---|---|
| live run (B.0) | `bundle/<mid>` (measurement) + `bundle/<abid>` (appraisal, `inputs=[mid]`, `appraisal_kind: live`, embedded verdict) + `judged_by/<mid>/<abid>` — locations are on the bundles |
| later appraisal of the same measurement (audit, or a *different policy*) | `bundle/<abid2>` (`inputs=[mid]`, `appraisal_kind` set, `session_sha256` identifying the policy) + `judged_by/<mid>/<abid2>` |
| audit of an appraisal package (B.6) | `bundle/<abid3>` with `inputs=[abid]` — the "audits_seq" field disappears: judging an appraisal is just an appraisal whose input is an appraisal |
| provisioning / blessing | `bundle/<bid>` (`provision`) |
| G challenge | `bundle/<cid>` (`challenge`, `state: issued`), later versions `bound`/`consumed`; the challenged measurement has `inputs=[cid]` |
| push to a store | `mirror/<state_tx>` |

Admission rule unchanged in spirit: a batch is refused if any `bundle/`
key it writes already exists (the nonce-uniqueness rule, now literally key
uniqueness), except the G challenge's own versions. immudb's
key-must-not-exist precondition can enforce it server-side for every
non-challenge package (the only writer that versions is the appraiser,
and only on `challenge` keys).

### K.4 Different appraisals over one measurement

The design's purpose. `appraise_bundle(client, ledger, mid, protocol,
session_override=None, appraisal_kind=...)` fetches the measurement
package by locator, runs the B.6 signed appraisal term with the chosen
session (companion map / goldens — e.g. a slices-only session omits the
hash companions, a historical-golden session injects an older golden set),
and writes one appraisal package plus pointer. Every such appraisal is
identified by its own nonce, bound to the measurement by hash, labelled
by `appraisal_kind` and pinned by `session_sha256`, so readers can compare
verdicts across policies for the same measured bytes. The blackboard's
`Verdict.ledger_ref` names the appraisal package it used (`bundle/<abid>`),
not a run.

### K.5 Readers

- `get(bid)` returns the bundle; `appraisals_of(mid)` scans `judged_by/<mid>/`;
  `inputs` walks the other way. The chain printed by
  `appraise_from_ledger.py` becomes a small graph: measurement → its
  appraisals → audits of those.
- `fetch(bid)` reads one bundle and tries its `locations` in order
  (local path, then each remote store's derived path in the configured
  clone — fetching if absent — then the hosting API), refusing bytes that
  do not hash to `blob_sha256`. One ledger read, no pointer scan.
- Durability: a bundle's remote location is live when the bundle's tx is
  at or below the latest `mirror` record for that store and its hash is
  not in that record's `skipped`. `reconcile` compares bundle txs with
  mirror records and spot-checks the clone; the backlog is "bundles above
  the latest mirrored tx" plus the skipped list.
- SQL mirror `attestation_records` v2 columns: `key, role, protocol_id,
  input_bid, appraisal_kind, passed, assurance, freshness, created_at,
  content_sha256`; "latest live verdict per protocol" is one query.
- Evidence repo layout: `ledger/bundles/<bid>.json`,
  `ledger/judged_by/<mid>/<abid>`, `ledger/mirror/<state_tx>.json`; blobs
  unchanged (content-addressed, so a bundle's remote `locations` entry is
  exactly where its blob lands).
- Other stores (a second git remote, an OCI registry) are configuration:
  new bundles carry one more `locations` entry and pushes to that store
  write their own `mirror` records; nothing per blob is written later.

### K.6 Migration

- `schema: pybb-ledger/v2`; `parse_record` keeps v1 classes so the 81 v1
  records in the current database remain readable, and `as_bundle(v1
  records of one run)` projects them into the v2 view for the chain and
  the mirror.
- Recommended: start v2 in a **new database** (`pybb2`, or re-bootstrap)
  rather than mixing kinds in one history; optionally backfill the Rocq
  runs by projection. The evidence repo gets a `ledger/v2/` prefix or a
  fresh repo branch — decision below.

### K.7 Code impact (estimate: comparable to steps 1+3 of the original plan)

| module | change |
|---|---|
| `ledger.py` | `BundleRecord` (v2, with `locations`), `JudgedByRecord`, `MirrorRecord`; `key_for`; `commit_batch(records)` generic with the uniqueness check over `bundle/` keys; `appraisals_of`; `latest_mirror(store)`; v1 projection |
| `ledger_runs.py` | one `build_bundle_record(role, payload, desc, inputs, ...)` replacing the five builders; `attest_with_ledger`, `appraise_record` and `audit_appraisal_package` collapse into `attest` (measurement + live appraisal) and `appraise_bundle` (any later appraisal, any policy) |
| `ledger_immudb.py` | prefix scan helper reused for `judged_by/`; precondition writes; mirror v2 columns |
| `ledger_repo.py` | layout under `ledger/bundles/` and `ledger/mirror/`; `push_archive` writes one `mirror` record instead of per-blob locators; `reconcile` and `fetch` work from `locations` + `mirror`; `verify_mirror` unchanged in principle |
| `ledger_tooling.py`, provisioning | the blessing is a `provision` bundle |
| `knowledge_sources.py` | `Verdict.ledger_ref` → appraisal bundle key |
| examples, docs, `ledger_records.md` | rewritten for v2 |
| asp-libs / rust-am-lib / CVM | none |

### K.8 Decisions (all seven resolved 2026-11-19; K is ready to schedule)

1. *Resolved 2026-11-19:* **fold the nonce record into the bundle.** A
   nonce has no existence apart from its bundle except for G's challenge,
   which becomes a `challenge` bundle; nonce uniqueness becomes `bundle/`
   key uniqueness (identical semantics, enforceable server-side). Id
   derivation, confirmed end to end: the term carries `generate_nonce`
   (first, in a `left_path` branch, for measurement/provision; after
   `APPR` for appraisal) → the CVM forks the ASP, which draws 32 CSPRNG
   bytes → `SIG` signs every slot, nonce included → pybb lays the type out
   with `slot_layout`, requires exactly one one-slot `generate_nonce`
   event and full slot accounting, base64-decodes that slot and takes its
   sha256 → `bid`; refused if `bundle/<bid>` exists; written with
   `execAll`, proof-checked with `verifiedGet`. Legacy nonce-less
   provisioning bundles key by blob hash.
2. *Resolved 2026-11-19:* **fold the verdict into the appraisal bundle.**
   A verdict is a reading of exactly one appraisal, so it lives on the
   appraisal bundle as a `verdict` object (`passed`, `components_total`,
   `components_failed`, `failing[]`, `components_sha256`,
   `components_blob_sha256`, `interpreter`); `evidence_assurance` is
   dropped (the input bundle carries its own assurance); the mirror keeps
   `passed` as a column on appraisal rows. A run whose appraisal never
   happened has no appraisal bundle; its measurement bundle's `error`
   field says why (that is the absence of a verdict, not a verdict).
   **Roles on the client side:** one `Bundle` class, not a hierarchy — a
   `role` enum with `inputs`, `verdict`, `appraisal_kind` and the
   challenge fields as optional members serialized only when set, and one
   validator enforcing the invariants (appraisal ⇒ `inputs` and
   `verdict`; measurement/provision ⇒ neither; challenge ⇒ `state`). The
   role is assigned by the producing flow (`attest` → measurement then
   appraisal; `appraise_bundle` → appraisal; provisioning/blessing →
   provision; G issuance → challenge) and asserted against the term
   actually sent (APPR present ⇒ appraisal; stripped+SIG ⇒
   measurement/provision; nonce+SIG only ⇒ challenge). Appraisal and
   challenge roles are structurally checkable from the package;
   measurement vs provision is the writer's claim, like `protocol_id`,
   and nothing security-relevant depends on it. New purposes map onto
   existing roles rather than adding roles.
3. *Resolved 2026-11-19:* **`judged_by/<measurement_bid>/<appraisal_bid>`
   pointer keys**, written in the same batch as the appraisal bundle with
   a minimal value, so "every appraisal of X" is one prefix scan that is
   verified, atomic with the appraisal, mirrored to the evidence repo and
   present after a replay restore; the SQL mirror additionally carries
   `input_bid` on appraisal rows for ad hoc queries. Rejected: mirror-only
   reverse lookup (unverified, written after the batch, absent from the
   git mirror until rebuilt).
4. *Resolved 2026-11-19:* **a new database** (`pybb2`, bootstrapped on the
   same server; `LedgerConfig.db` points at it) and a fresh prefix or
   branch of the evidence repo for the v2 mirror. The v1 database stays
   intact and readable as the record of the prototype runs; v2 starts at
   tx 1 with a single-schema journal. Optional backfill of the Rocq runs by
   projecting v1 records into v2 bundles (`as_bundle`), which also
   exercises the projection readers need. Rejected: in place (every
   reader, the journal, `verify_mirror` and the mirror table would carry
   two interleaved schemas forever, for prototype data of no production
   value).
5. *Resolved 2026-11-19:* **`bundle`** — Copland's own word for what `SIG`
   closes over and the project's existing usage; the provisioning case is
   folded in as `role: provision`. Rejected: `package` (unsatisfying),
   `evidence` (v1's narrower meaning), `attestation`, `capsule`,
   `envelope`.
6. *Resolved 2026-11-19:* **`session_sha256` + `appraisal_kind`**, no
   separate companion-map hash: `ASP_Comps` is part of the session, so
   `comps_sha256` would add nothing a reader cannot derive, and the policy
   *by name* is what a reader without the session file wants.
7. *Resolved 2026-11-19:* **no locator records.** Locations are stated once
   on the bundle at commit (`locations`, K.1): the local archive path and,
   for every configured store, the content-addressed path the blob will
   have there. Whether a push has happened is answered by one
   `mirror/<state_tx>` record per push (K.2). Rationale: the repo is
   content-addressed, so every remote location except "arrived yet" is a
   function of the hash and the configuration, and v1's per-blob `github`
   locators restated the repo's own index inside the ledger while being
   the only record kind that grew after a run was committed. Given up:
   per-blob "reached commit C" statements, replaced by the per-push
   statement at the granularity pushes actually happen. The `mirror`
   record is optional in principle (the repo's state snapshots and git
   history carry the same witness) and kept so `reconcile` can answer
   from the ledger alone.

## L. Position-free records (planning, 2026-11-19)

**STATUS: decided; implementation per L.5 (2026-11-20).** Removes every RawEv slot
position from the stored records. A bundle describes the evidence; where
pybb found things inside it is pybb's reading, done again at read time.

### L.0 Why the positions are there, and why they go

The CVM returns a flat `RawEv` list with no labels. pybb lays the evidence
type out against the session's ASP types (`slot_layout`) to learn which
slot holds the nonce, which the signature, which the `hashevidence`
binding, and to check that every slot is accounted for. v1 copied those
positions into the records (`nonce.slot`, `signature.slot`,
`binding.slot`) on the theory that a reader without the session could then
find the bytes in the archived package directly. In practice nothing reads
a position back from a record: the two-pass appraisal and the appraisal of
an appraisal both relocate the binding and the nonce live, from the fetched
package and the session (`span_for`), and the SQL mirror does not carry
them. The positions are redundant, and they leak pybb's layout conventions
(and its `asp_targid` labels) into a record that should describe evidence,
not pybb's handling of it. Slot accounting remains a check pybb performs
when it reads a package; it is not a fact about the package worth storing.

### L.1 What the ledger needs per package

Position-free, and each either not derivable from the package alone or the
value a reader without blobs compares:

| field | why |
|---|---|
| `bid` + `nonce.b64`/`bytes` | identity; a reader checks `bid == sha256(nonce)` without the session |
| `rawev_sha256` | what the `hashevidence` ASP computes over this package's flat RawEv; the value a binding is compared against (neither `response_sha256`, the whole response, nor `blob_sha256`, the stored bytes, equals it) |
| `inputs[].bid` | which bundle an appraisal judged (pybb's claim) |
| `inputs[].binding_hash` | the value of the appraisal package's `hashevidence` slot (the CVM's claim, under the appraiser's signature). **Kept** (decision L.4.2): it is a hash, not a position, and it lets a reader holding only records check `appraisal.inputs[0].binding_hash == measurement.rawev_sha256` without blobs or session. It is a cross-check, never a source of truth: the B.6 appraisal-of-appraisal takes its golden from the judged bundle's `rawev_sha256` and judges the binding slot inside the CVM |
| `signature.present`, `signature.asp`, `signer_fp` | that and by which ASP the package is signed, and whose key pybb trusts |
| `rawev_count` | a count, not a position; a cheap sanity check against the archived bytes. Kept |

Why `hashevidence` is load-bearing (restated from B.6 for this section):
REPLACE companions overwrite the slots they judge, so an appraisal package
holds verdicts, appraiser nonce and signature but none of the measured
bytes — nothing inside it says *which* bytes it judged. The `hashevidence`
slot, computed by the CVM over its input and signed with the rest, is the
only in-evidence link from appraisal to measurement; it is what makes the
pairing checkable from evidence and auditable by `goldenbytes_appr`.

### L.2 The change (schema stays `pybb-ledger/v2`; additive-compatible readers)

| model | now | after |
|---|---|---|
| `NonceInfo` | slot, asp, asp_targid, b64, bytes | asp, b64, bytes |
| `SignatureInfo` | present, slot, asp, signer_fp | present, asp, signer_fp |
| `InputRef` | bid, binding_slot, binding_hash | bid, binding_hash |

- `asp` stays on both: *which ASP produced* the nonce or signature is
  structural, matters for foreign packages, and is not a position.
- `asp_targid` goes: it is pybb's own target label (`nonce_targ` /
  `appraiser_nonce_targ`), used only to pick the right nonce event when
  reading; `describe_package` keeps taking it as a parameter.
- `SlotRef`, `SlotSpan`, `PackageDescription` remain as internal reading
  tools in `ledger.py` and never enter a record. `NonceInfo` stops
  inheriting from `SlotRef`.
- Readers: unknown fields are preserved, so bundles written before the
  change still parse; the position fields simply become unknown extras.
  No schema tag bump: nothing a v2 reader relied on is removed.

### L.3 Code impact (small)

| where | change |
|---|---|
| `ledger.py` | the three models; `BundleRecord` unchanged otherwise |
| `ledger_runs.py` | `build_bundle_record` stops copying `hs.start` / `desc.nonce.slot` / `asp_targid` |
| `examples/appraise_from_ledger.py` | drop the `sig_slot` / `nonce_slot` / `binding slot` prints |
| `docs/ledger_records.md` | NonceInfo, SignatureInfo, InputRef tables; `SlotRef` paragraph becomes "internal only" |
| tests | `test_ledger.py` / `test_ledger_runs.py` / `test_ledger_immudb.py` / `test_integration_ledger.py` assertions on `.slot` / `binding_slot` |
| `pybb2` | re-bootstrap (nothing pushed to the mirror yet), rerun the Rocq status run and the two post-hoc appraisals |
| asp-libs / rust-am-lib / CVM | none |

### L.4 Decisions

1. *Resolved 2026-11-19:* **remove every slot position from records**
   (`nonce.slot`, `signature.slot`, `inputs[].binding_slot`) and the
   `asp_targid` label; keep `asp`.
2. *Resolved 2026-11-19:* **keep `inputs[].binding_hash`** as the
   record-level cross-check against the judged bundle's `rawev_sha256`
   (rationale in L.1). Rejected: `inputs = [{bid}]` only, which would make
   checking the pairing require the appraisal blob and the session.
3. *Open (raised 2026-11-19, not decided):* **arbitrary Copland bundles
   from other writers**, including packages produced by terms with an
   inline `APPR`. Today the `role` enum is closed, only `role: appraisal`
   may carry a `verdict`, and an appraisal must name `inputs`, so a
   self-appraised package cannot record its verdicts and a foreign `role`
   fails to parse. Sketch, if wanted: `role` becomes an open string with a
   general `evidence` value; `verdict` allowed on any role with
   `verdict.scope ∈ {inputs, inline}` and `inputs` required only for
   scope `inputs`; an optional `context` BlobRef (session or
   `[payload, ctx]`) so pybb can lay a foreign package out later; a
   lenient `describe_package` (no nonce, no signature, unknown ASP types
   reported, not fatal); an optional `writer` field beside `appraiser_id`.
   Keys, uniqueness, `judged_by`, mirror records and the two-run flow are
   unaffected. Permissions for other writers stay in section J.

### L.5 Implementation plan (confirmed 2026-11-20)

Confirmed: `rawev_count` stays (a count, a cheap check against archived
bytes); `asp` stays on nonce and signature; `pybb2` is deleted and
recreated rather than migrated; the schema tag stays `pybb-ledger/v2`.

1. `ledger.py`: `NonceInfo` → `asp, b64, bytes` (no longer a `SlotRef`);
   `SignatureInfo` → `present, asp, signer_fp`; `InputRef` → `bid,
   binding_hash`. `PackageDescription` keeps `nonce: SlotRef` internally
   and gains `signature_ref: SlotRef` for the signature's position;
   `signature` becomes the position-free `SignatureInfo`. `describe_package`
   keeps `nonce_targid` as a reading parameter. Validators unchanged.
2. `ledger_runs.build_bundle_record` stops copying positions and
   `asp_targid`; it still locates the `hashevidence` span to read the
   binding value.
3. Archiving: lift the archive callback out of
   `knowledge_sources.make_attestation_predicate` into
   `ledger_runs.archiver(archive_dir)`, reuse it in the blackboard and give
   `examples/appraise_from_ledger.py` an `--archive-dir` (default
   `evidence/`) so post-hoc appraisal bundles have bytes behind them.
4. Tests: `test_ledger.py` helpers and the description assertions
   (`signature_ref.slot`), `test_ledger_runs.py` and
   `test_integration_ledger.py` slot assertions move to the description.
5. Docs: `ledger_records.md` nested-model tables (`SlotRef` becomes
   "internal to reading, never stored"), `ledger.md` key table, this status.
6. Schema compatibility note: readers at `36906fd` required `slot` and
   would reject L records; no such reader exists outside this checkout and
   nothing has been pushed to the mirror, so L is the one incompatible
   tweak made before the first v2 push. After that push, removals need a
   tag bump.
7. `pybb2`: `immuadmin database unload` + `delete`, then bootstrap; rerun
   the Rocq status run and the two post-hoc appraisals with archiving;
   refresh the `pybb2` summary; one commit on `ledger`.

## M. Configurable bundle shapes (planning, 2026-11-19)

**STATUS: plan only; shapes and setting decided, context blob open.** The
ledger does not prescribe one way to build a bundle. A protocol chooses a
**shape**: a Copland term construction that answers, for every package it
produces, the four questions the ledger needs — where the nonce is, what
the signature covers, where the verdicts are (if any), and how an appraisal
is bound to what it judged. Two shapes are defined now; others can be added
without touching the record schema.

### M.0 Semantics the shapes rely on (from `cvm/theories/Monad.v`)

- `EXTEND n` ASP: bits become `out ++ incoming`; type `asp_evt(asp, incoming)`.
- `REPLACE n` ASP: bits become `out`; type `asp_evt(asp, incoming)`. The type
  beneath survives, the bytes do not.
- `NULL` returns empty evidence (`mt_evc`). There is no copy primitive; the
  only way to carry evidence through a branch is an EXTEND ASP in that
  branch.
- `bseq`: left runs on the incoming evidence; right runs on it too
  (`both_paths`) or on empty (`left_path`); join concatenates bits and
  builds `split_evt`.
- `APPR` over `asp_evt(a, below)` with `a` EXTEND: the companion runs over
  **all remaining bits**, then `below` is appraised as a sibling (a split).
  With `a` REPLACE: the companion only. Over `split_evt`: each half with
  `left_evt`/`right_evt` wrappers in the type (the attribution path).
- Consequence rejected for the shapes below: EXTEND-typed *companions*
  keep the judged bytes but duplicate them — the outermost companion
  (over `SIG`) retains the whole package and the inner ones retain their
  slots again (P twice plus verdicts). Verified on the Rocq
  `run_command_rocq_appr` packages: 30 slots where 17 were measured.
- `WRAP`/`UNWRAP` are for reversible transforms whose dual is an inverse;
  a verdict is not an inverse of a measurement, so they do not apply.

### M.1 Shape `split` (today's B.0/B.6 flow; default)

Two CVM runs.

```
run 1   lseq (bseq left_path (asp generate_nonce) M) SIG                → P
run 2   lseq (bseq both_paths (asp hashevidence) APPR)
             (lseq (asp generate_nonce) SIG)         over P              → A
```

`hashevidence` REPLACE: A holds `H = sha256(P's RawEv)` and verdicts, none
of P's bytes. Bits for a two-measurement `M`: P `[sig, nonce, h_a, h_b]`,
A `[sig2, nonce2, H, v_sig, v_nonce, v_a, v_b]`.

Ledger: measurement bundle P + appraisal bundle A (`inputs=[P]`,
`binding_hash = H`, `appraisal_kind: live`) + `judged_by/P/A`, one batch.
Run 2 may happen at any later time instead, under any session, from the
recorded P (`appraise_bundle`). P is a signed measurement artifact that
stands on its own and can be handed to a third party.

### M.2 Shape `inline` (one run, one nonce, one SIG)

```
lseq (bseq left_path (asp generate_nonce) M)                            → P' (unsigned)
     (lseq (bseq both_paths (asp hashevidence) APPR) SIG)
```

`hashevidence` typed **EXTEND** with `EvInSig: ALL` (it must receive the
bits to hash them): the hash lane comes out as `H` followed by all of P'
exactly once; the APPR lane keeps REPLACE companions and adds verdicts
only. Bits for the two-measurement `M`:

```
[ sig, H, nonce, h_a, h_b, v_nonce, v_a, v_b ]        8 slots
       └── P' ──────────┘  └── verdicts ──┘
```

Type: `asp_evt SIG · split_evt(asp_evt hashevidence · et_P', APPR-tree)`,
where the APPR-tree is the same tree as in `split` minus `sig_appr`
(there is no inner signature to judge). No second nonce: one signed
object, one identity (`bid = sha256(nonce)`), one bundle.

Ledger: one appraisal bundle, `verdict.scope: inline`, no `inputs`,
`binding_hash = H` over its own retained P' span. `H` is what any later
appraiser's `hashevidence` computes over the extracted P' bits, so later
appraisals bind to the same value.

Why no inner `SIG`: a signed P plus an outer SIG duplicates signatures and
signature appraisals in one package (the "term 1" variant, 11 slots with a
second nonce); the user chose the single-signature form. What is given up:
P' is covered only by the outer SIG, so no excerpt of the package is a
signed measurement on its own. Clients that need that use `split`.

### M.3 What other clients can do with an inline package

With the session's `ASP_Types`/`ASP_Comps` and the signer's key: lay the
package out, lift `[RawEv_P', et_P']` out as evidence, verify `H`, and
either (a) extract-and-appraise P' under their own session in a CVM run of
the `split` run-2 term (binds to the same `H`), or (b) appraise the whole
package: `invoke_APPR'` judges the EXTEND `hashevidence` node with
`goldenbytes_appr` and then appraises `et_P'` beneath it as a sibling, so
their companions re-judge the measurements directly while pass-through
companions (`magic_appr`) carry the existing verdict nodes and `sig_appr`
judges the outer signature — the B.6 machinery without extraction. Both
yield an appraisal bundle with `inputs=[inline bid]` and a pointer.

### M.4 Configuration and code

- Per-protocol setting `bundle_shape: split | inline` (in the protocol
  directory alongside `ledger`-relevant settings, or in `LedgerConfig` as a
  map protocol → shape); default `split`.
- `measurement_term` (left_path nonce fork + `M`) and the both_paths
  hash-and-APPR fork are shared; `inline` composes them with `lseq`, types
  `hashevidence` EXTEND in the session copy it sends, and omits the second
  `generate_nonce`. `attest` dispatches on the shape and records whichever
  bundles the shape yields. `describe_package`, `slot_layout` (EXTEND ASP
  span = 1 + size of subtree, as for `SIG`), `build_bundle_record`,
  `commit_bundles`, the summarizer path over the extracted APPR branch:
  unchanged.
- Schema (additive within v2): `verdict.scope ∈ {inputs, inline}`;
  `inputs` required for scope `inputs`, absent for `inline`; the inline
  binding hash lives on the verdict (`verdict.binding_hash`) since it binds
  to a span of the same package, not to another bundle. Validator rule
  follows.
- Provisioning keeps stripping APPR regardless of shape (no goldens yet).
- The Rocq driver gets the setting per protocol; the demonstration is one
  protocol run `inline` into `pybb2` beside the `split` ones.

### M.5 Gate: the term-2 spike

One real-CVM run of the `inline` term on the l1a fixture: `hashevidence`
retyped EXTEND/`EvInSig: ALL` runs; the retained P' span lays out and
`sha256(P' bits) == H`; the APPR branch extracts and type-checks in the
verified summarizer; `describe_package` finds exactly one nonce. Nothing
in M is implemented before this passes.

### M.6 Decisions

1. *Resolved 2026-11-19:* **shapes are configurable per protocol**, not
   prescribed; the ledger needs only the four answers in the preamble.
2. *Resolved 2026-11-19:* **two shapes now**: `split` (default; appraisal
   now or later; signed measurement artifact) and `inline` (term 2; one
   nonce, one SIG, EXTEND `hashevidence` carrying P'). Rejected: EXTEND
   companions (duplication, M.0), inline with inner SIG (duplicate
   signatures), `NULL` branches (erase).
3. *Open — needs fleshing out:* **the context blob.** Sketch: optional
   `context: BlobRef` on a bundle pointing at an archived copy of the
   session (or the `[payload, ctx]` pair provision bundles already store),
   content-addressed and stated at commit like the package blob;
   `session_sha256` stays as its integrity check. Motivation: a client
   without pybb's protocol directory cannot derive slot spans
   (`ASP_Types`) or attribute verdicts (`ASP_Comps`) from the record alone,
   and inline packages are the first ones other clients would plausibly
   open (M.3). Not settled: whether it is the whole session or only
   `Session_Context`; whether it is per bundle or shared per
   `session_sha256` (one blob, many bundles); whether provision bundles'
   embedded `ctx` is reused or normalized to the same form; where it lives
   in the evidence repo layout; and whether `manifest`/`term` deserve the
   same treatment. Decide together with the rest of L.4.3 (open `role`,
   `writer`, lenient `describe_package`), since all of them serve clients
   that are not pybb.

## Order of work

1. A + `FileLedger` + unit tests (ledger shape settles independent of immudb).
2. C: `generate_nonce` / `nonce_appr` ASPs in asp-libs, then the spike.
3. B + D (nonce'd runs land in the ledger; backfill script).
4. `ImmudbLedger` + ops script + integration tests.
5. E (fetch + appraise + example + blackboard variant).
6. H (evidence repo, per-archive push, mirror, restore tooling + drill); bundle records.
7. F docs.
8. G (two-run pre-registration) — detailed plan in section G (2026-11-18), awaiting its decisions; separate change set.
9. K (unified bundle records, schema v2) — plan in section K, all decisions resolved 2026-11-19; precedes G, since G's challenge becomes a `challenge` bundle.

## Decisions (all resolved 2026-11-17)

1. **Nonce handling** — *resolved*: in-protocol `generate_nonce` ASP,
   signed with the measurements, whole package committed to the ledger
   after the run (section B). Guarantee: binding, uniqueness, ordering;
   records labelled `freshness: post-hoc`. No environment, file, or
   in-run ledger access. Two-run pre-registration (challenge freshness,
   valid locally or remotely) is the follow-up in section G.
2. **Inline evidence or pointer-only** — *resolved*: pointer-only
   (section H). immudb has no size cap, only time-based truncation that
   drops payloads while keeping proofs, so inline would degrade to
   pointers anyway; records stay ~1–2 KB. Locators: local path, GitHub
   blob; `durable` once two resolve.
3. **Deployment** — *resolved*: local single-node immudb for dev/demo
   via Homebrew (`immudb` 1.11.x bottle ships `immudb`, `immuadmin`,
   `immuclient`; `brew services start immudb`; data under
   `$(brew --prefix)/var/immudb`), bound to localhost, default admin
   password changed, db `pybb` + non-admin user, optional server signing
   key, web console/metrics off. Integration tests start an **ephemeral**
   server per session (temp `--dir`, random port, `--web-server=false
   --metrics-server=false`) and never touch the demo ledger; the restore
   drill runs there too. A shared lab instance (TLS, one user per
   appraiser) is a `LedgerConfig` change when multi-host writers arrive
   with section G; immudb Vault (REST, vendor) is not pursued. Docker is
   not installed on the dev Mac and is not required.
4. **Record payload format** — *resolved*: plain pybb JSON, schema in
   section I; no in-toto Statement for now. Fields are chosen so a
   derived Statement (subjects = blob and target digests) can be added
   later as a pure envelope without touching the stored records.
5. **GitHub home for evidence** — *resolved*: a separate private repo
   (working name `ku-sldg/pybb-evidence`), content-addressed, which also
   mirrors the ledger records, states, and hot-backup segments
   (section H). Private because bundles contain raw model bytes.
