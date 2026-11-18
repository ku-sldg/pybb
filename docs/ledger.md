# The attestation ledger

pybb can record every attestation run in an append-only, cryptographically
verifiable ledger (immudb) and mirror the evidence to a git repository, so
that any run can be fetched later, re-appraised by the CVM, and audited by
someone who has only the ledger and the repository. The design record is
[ledger_plan.md](ledger_plan.md); this page is the user guide.

## What the ledger is, in one paragraph

A ledger of **Copland runs**. Each protocol run is two CVM invocations: a
measurement run that produces a nonce'd, signed package, and an appraisal
run that judges it and is itself signed and nonce-bound. pybb archives both
packages and the interpreted component list, derives the run's identity from
the signed nonce slot, and commits the run's records to immudb in one
transaction. The ledger holds hashes and pointers, never evidence bytes; a
configured git repository holds the bytes and a complete mirror of the
records. Nothing in the ledger refers to blackboard concepts; the blackboard
links to the ledger through `Verdict.nonce_id`.

The division of labour is strict: **pybb identifies and describes, the CVM
judges**. pybb hashes bytes to key and index them and reads evidence
structure to label it. Signatures, nonces and goldens are judged only by
companion ASPs inside the CVM and read back through the verified summarizer.
The one check pybb owns is refusing a nonce the ledger already holds.

## Setup

1. **ASPs.** asp-libs must provide `generate_nonce`, `nonce_appr`,
   `hashevidence` and `magic_appr` beside the usual ones (`make` in asp-libs
   builds them into `target/release`), built against a rust-am-lib that
   base64-encodes negative appraisal reasons (branch `ledger-verdict-b64`;
   without it any ASP after `APPR` fails when a verdict fails). Readiness
   reports ASPs that are missing.
2. **immudb.** `scripts/immudb_dev.sh install` installs the Homebrew bottle
   and starts the service; set `PYBB_IMMUDB_PASSWORD` and run
   `scripts/immudb_dev.sh bootstrap` to create database `pybb` and user
   `pybb`; `scripts/immudb_dev.sh rotate-admin NEWPASS` replaces the default
   admin password. `pip install -e '.[ledger]'` adds `immudb-py`.
3. **Bless the stack.** `python examples/provision_tools.py` builds the
   `attestation_tools` protocol (CVM binary, verified summarizer, every ASP
   the configured protocols use, verifying key), provisions it — the CVM
   hashes the live binaries and signs — and records the bundle. This is the
   only time the tools are measured under the default cadence; repeat it
   after rebuilding asp-libs or the CVM.
4. **Evidence repository** (optional until you want durability). Clone any
   git repository you choose and set `PYBB_EVIDENCE_REPO` to the clone's
   path, or write the path to `~/.pybb/evidence_repo`. The repository's
   `owner/name` is read from its `origin` remote. Protect its default
   branch against force-pushes where the hosting plan allows (GitHub Free
   organizations cannot protect private repositories); the mirror's
   integrity rests on the ledger's hashes and state snapshots either way.
   The project's repository is the private `ku-sldg/pybb-ledger`.

## Configuration

`pybb.attestation.ledger.LedgerConfig`:

| field | default | meaning |
|---|---|---|
| `host`, `port`, `db` | `127.0.0.1`, `3322`, `pybb` | immudb connection |
| `user`, `password` | `PYBB_IMMUDB_USER` / `PYBB_IMMUDB_PASSWORD` | the non-admin user |
| `state_dir` | `~/.pybb` | client state (verified root) and the appraiser id |
| `verify_key_path` | `PYBB_VERIFY_KEY` or asp-libs' demo public key | fingerprinted into every record as `committer_fp` |
| `evidence_repo` | `PYBB_EVIDENCE_REPO` | local clone of the evidence repository |
| `golden_root` | `PYBB_GOLDEN_ROOT` or `golden` | where provisioning bundles live |
| `min_assurance` | `signed+nonce` | runs below it are refused at commit |
| `assurance_exceptions` | `{}` | `protocol_id -> reason` for protocols allowed below the minimum |
| `tooling.protocol_id` | `attestation_tools` | the tooling protocol; `None` disables tooling tracking |
| `tooling.measure` | `at_provisioning` | `every_episode` / `every_run` re-measure the tools as ordinary ledger runs |
| `fail_open` | `False` | with `True`, a ledger outage leaves the verdict unledgered instead of failing it |
| `appraiser_id` | generated once under `state_dir` | opaque id of this installation; never a hostname |

The Rocq scenario runs under the ledger with `python
examples/temp_control_rocq.py --ready --status --ledger immudb` (or
`--ledger PATH` for a FileLedger); every tamper and repair arc takes the
same flag.

## Using it in a workflow

```python
from pybb.attestation import ImmudbLedger, make_attestation_predicate, make_readiness_predicate
from pybb.attestation.ledger import LedgerConfig

cfg = LedgerConfig()
ledger = ImmudbLedger(cfg)                      # or FileLedger("ledger.jsonl") for tests
readiness = make_readiness_predicate(protocols, ledger_config=cfg)
attest = make_attestation_predicate(client, protocols, archive_dir=EVIDENCE_DIR,
                                    ledger=ledger, ledger_config=cfg)
```

Without `ledger=` the predicate runs the legacy single-run flow unchanged.
With it, every protocol runs as measurement + appraisal and the `Verdict`
carries `nonce_id`, `ledger_ref` (`evidence/<nid>`), `evidence_ref`,
`appraisal_ref` and `components_ref`. A verdict fails closed when the CVM
fails, the package is not describable, its assurance is below the minimum
without an exception, its nonce is already in the ledger, or the ledger is
unreachable.

Readiness with `ledger_config=` reports, before attestation starts: missing
ledger ASPs; each protocol's reachable assurance against `min_assurance`;
and a missing tooling protocol or blessing when tooling tracking is on.

`ledger_request(nid)` as an entry's measurement makes the predicate
re-appraise the ledger-held run instead of measuring the live tree (an audit
rung); the verdict is truthy only if the verified reads, the byte and nonce
checks, and the fresh signed appraisal all hold, and it fails with a reason
when the audit disagrees with the recorded verdict.

## Records and keys

Every record is canonical JSON (sorted keys, no whitespace, UTF-8) with a
common envelope: `schema` (`pybb-ledger/v1`), `kind`, `nid`, `created_at`,
`committer_fp`, `pybb_version`, `appraiser_id`. The full schema is section I
of the plan. Keys:

| key | holds |
|---|---|
| `nonce/<nid>` | the nonce bytes, `role` (`measurement` or `appraisal`, then `for_nid`), `state`, `freshness`, protocol |
| `evidence/<nid>` | the raw signed package: protocol and config hashes, `response_sha256`, `blob_sha256`, `rawev_sha256`, signature and nonce slots, `assurance`, `tooling`, local locator |
| `appraisal/<nid>/<seq>` | one appraisal run: seq 1 is the live one, later seqs are audits; `anid`, `binding` (hashevidence over the judged package), `audits_seq` when it judged an appraisal package |
| `verdict/<nid>` | pass/fail, counts, failing components, `components_sha256`, both assurance levels, interpreter |
| `locator/<nid>/<seq>` | where a blob is (`local` or `github`), `target` (`evidence`, `appraisal`, `components`, `bundle`), `verified` |
| `bundle/<nid>` | a provisioning bundle (legacy bundles: `bundle/sha256:<hash>`) |
| `restore/<created_at>` | a restore event |

A run's commit is one batch: measurement nonce, appraiser nonce, evidence,
appraisal, verdict, plus local locator records for the appraisal and
components blobs. Durability (two locator kinds resolve) is derived at read
time and never stored.

**Assurance** is computed from the package as produced: `signed+nonce`,
`signed`, `nonce` or `none`. **Freshness** is `post-hoc` for every run today:
the nonce binds the package and makes it unique and orderable, but the
appraiser first learns it from the package, so it is not a challenge.
Pre-registered challenges are the section G follow-up.

## Reading the ledger without pybb

```bash
immuclient login pybb
immuclient use pybb
immuclient get nonce/<nid>                       # any key, as canonical JSON
immuclient history nonce/<nid>                   # versions (section G will add states)
immuclient scan --prefix appraisal/<nid>/        # every appraisal of a run
immuclient query "SELECT key, kind, passed, assurance, created_at FROM attestation_records WHERE protocol_id = 'temp_control_aadl_slang_l1a' ORDER BY created_at DESC LIMIT 20"
immuclient query "SELECT key FROM attestation_records WHERE assurance <> 'signed+nonce'"
```

`attestation_records` is a SQL mirror written after each KV batch; each row's
`content_sha256` is the hash of the KV value, so a row can be checked against
`immuclient get`. The mirror is a convenience view and
`ImmudbLedger.rebuild_mirror()` regenerates it from the KV history.

## Re-appraising and auditing

```bash
python examples/appraise_from_ledger.py --latest temp_control_aadl_slang_l1a          # chain + fresh signed appraisal
python examples/appraise_from_ledger.py <nid> --audit-appraisal --seq 1                 # CVM-native audit of the appraisal package
python examples/appraise_from_ledger.py <nid> --no-run                                  # chain only
```

A fresh appraisal fetches the raw package through its locators (local path,
then GitHub), refuses bytes whose hash is not the record's, checks that the
package reproduces the recorded nonce id, runs the same signed appraisal
term, and appends `appraisal/<nid>/<seq>` with a fresh appraiser nonce and
`agrees_with_recorded_verdict`. An audit of an appraisal package judges its
signature, appraiser nonce and binding inside the CVM (`sig_appr`,
`nonce_appr`, `goldenbytes_appr` with the recorded hash as golden), with the
appraiser nodes passed through `magic_appr`; its record carries
`audits_seq`.

## The evidence repository

```bash
export PYBB_EVIDENCE_REPO=~/src/pybb-evidence
python examples/ledger_push.py [--archive-dir evidence/<dir>] [--bundles golden] [--backup-segment seg.bkp]
python examples/ledger_reconcile.py --verify-all
```

A push copies every blob the ledger holds locally but not remotely into
`blobs/<sha256>.json.gz`, writes every record under `ledger/records/<nid>/`,
appends `ledger/journal.jsonl` (one line per ledger tx with each key's
content hash), writes `ledger/state/<tx>.json` (the ledger head), updates
`runs/<archive_dir>/manifest.json`, makes one commit, pushes, and appends a
verified `github` locator per blob. Reconcile lists what is not yet durable,
re-verifies committed blobs, and compares the live head with the mirrored
state, which catches a rolled-back or replaced ledger.

Hot-backup segments for an exact immudb restore are produced by the
operator (`immuadmin hot-backup pybb -o seg.bkp` after `immuadmin login`)
and added with `--backup-segment`.

## Restore

```bash
python examples/ledger_restore.py verify  <clone>                 # hashes, journal contiguity, blobs
python examples/ledger_restore.py replay  <clone> --into-immudb   # content restore into a fresh database
python examples/ledger_restore.py exact   <clone> --db pybb       # prints the immuadmin hot-restore command
```

`verify` must pass before anything is loaded. Journal tx ids strictly
increase but are not contiguous on immudb, because SQL mirror and DDL
transactions carry no records. `replay` writes one batch per journal line
with the mirrored canonical values; the new instance has new tx ids, and a
`restore` record names the source commit. `exact` restores an
identical instance from backup segments so the old client state still
verifies. The full procedure and its timing estimate are in plan section H.4.

## Limits to keep in mind

- Freshness is post-hoc. A compromised CVM or ASP on the same host can
  produce a package the nonce cannot distinguish from a fresh one.
- Tool identity is drift detection and provenance, not a root of trust: the
  tools measure themselves. A TPM-backed mechanism is the right tool for
  that layer.
- The verified summarizer does not type-check an audit of an appraisal
  package; those verdicts are read by slot layout and recorded as
  `interpreter: legacy-walker`.
- Under `at_provisioning`, a record's `tooling` says which blessing was in
  force, not that the binaries were unchanged at run time.
- Legacy bundles (provisioned before nonces) are recorded by content hash
  with `assurance: signed` until the protocol is re-provisioned.
- Provisioning overwrites `golden/_bundles/<pid>/provision_bundle.json`. A
  bundle re-blessed before its predecessor was pushed leaves the older
  bundle record pointing at bytes that no longer exist; push after every
  blessing, or expect that record to stay pending in `ledger_reconcile.py`.
