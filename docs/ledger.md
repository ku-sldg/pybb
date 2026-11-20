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
links to the ledger through `Verdict.bid` and `Verdict.ledger_ref`.

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
3. **Measure and bless the stack; measure the configurations.**
   `python examples/ledger_context.py measure stack --bless` runs the CVM
   once over the installation — the CVM binary, the verified summarizer,
   the verifying key, every executable in the ASP directory and the CVM
   invocation settings — and records a signed `stack` bundle plus your
   `blessing` of it. `python examples/ledger_context.py measure config
   --all` records one `config` bundle per protocol: the exact term, session
   and manifest pybb hands the CVM for every term constructor. Both commit
   unconditionally and only when you run them: pybb has no cadence and
   never measures its stack or inputs on its own. Repeat `measure stack`
   after rebuilding asp-libs or the CVM (then `audit` and `bless` the new
   bundle), and `measure config <pid>` after editing a protocol. Runs carry
   no pointer to either; `ledger_context.py show` and
   `appraise_from_ledger.py` derive what was in force (plan section O).
4. **Evidence repository** (optional until you want durability). Clone any
   git repository you choose and set `PYBB_EVIDENCE_REPO` to the clone's
   path, or write the path to `~/.pybb/evidence_repo`. The repository's
   `owner/name` is read from its `origin` remote. Protect its default
   branch against force-pushes and deletion; the mirror's integrity rests
   on the ledger's hashes and state snapshots either way. The project's
   repository is `ku-sldg/pybb-ledger`, public (like `ku-sldg/pybb`, whose
   model bytes the bundles contain) with `main` protected. Note that
   records embed the appraiser's local archive paths.

## Configuration

`pybb.attestation.ledger.LedgerConfig`:

| field | default | meaning |
|---|---|---|
| `host`, `port`, `db` | `127.0.0.1`, `3322`, `pybb2` (`PYBB_IMMUDB_DB`) | immudb connection; `pybb` holds the schema v1 records |
| `user`, `password` | `PYBB_IMMUDB_USER` / `PYBB_IMMUDB_PASSWORD` | the non-admin user |
| `state_dir` | `~/.pybb` | client state (verified root) and the appraiser id |
| `verify_key_path` | `PYBB_VERIFY_KEY` or asp-libs' demo public key | fingerprinted into every record as `committer_fp` |
| `evidence_repo` | `PYBB_EVIDENCE_REPO` | local clone of the evidence repository |
| `golden_root` | `PYBB_GOLDEN_ROOT` or `golden` | where provisioning bundles live |
| `min_assurance` | `signed+nonce` | runs below it are refused at commit |
| `assurance_exceptions` | `{}` | `protocol_id -> reason` for protocols allowed below the minimum |
| `context.stack_protocol_id`, `context.config_protocol_id` | `attestation_stack`, `attestation_config` | the generated protocols `ledger_context.py` measures the installation and each protocol's inputs with (plan O); no cadence exists |
| `context.dir` | `context` | under `state_dir`: materialized inputs, their content-addressed copies, `stack/cvm_config.json`, and the default archive of context packages |
| `fail_open` | `False` | with `True`, a ledger outage leaves the verdict unledgered instead of failing it |
| `default_shape`, `shapes` | `split` (`PYBB_BUNDLE_SHAPE`), `{}` | the bundle shape per protocol: `split` (two CVM runs; the appraisal can also happen later, by anyone with the package) or `combined` (one run yielding the same two artifacts; the live appraisal judges the measurements only) — plan section M |
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
carries `bid` (the measurement bundle id), `ledger_ref` (`bundle/<appraisal
bid>`, the appraisal the verdict came from), `evidence_ref`, `appraisal_ref`
and `components_ref`. The judged outcome's class is `Appraised` (`Verdict`
remains as an alias); the recorded-but-unjudged outcome is `Measured`. A verdict fails closed when the CVM
fails, the package is not describable, its assurance is below the minimum
without an exception, its nonce is already in the ledger, or the ledger is
unreachable.

Readiness with `ledger_config=` reports, before attestation starts: missing
ledger ASPs and each protocol's reachable assurance against `min_assurance`.
With `ledger=` too, it reports as problems a writer with no `stack` bundle
or no blessing in the ledger, and informationally (`report.context`)
whether the latest stack bundle is blessed and how its last audit against
the latest blessing went.

`ledger_request(bid)` as an entry's measurement makes the predicate
appraise the ledger-held bundle again instead of measuring the live tree (an
audit rung); the verdict is truthy only if the verified reads, the byte and
bundle-id checks, and the fresh signed appraisal all hold, and it fails with
a reason when the audit disagrees with the live appraisal.

## Measure now, appraise later

Appraisal does not have to happen in the run that measured. With a ledger,
`make_measurement_predicate` records a protocol's signed measurement as one
bundle and returns a `Measured` outcome — truthy when recorded, carrying
`bid` and `ledger_ref`, and deliberately not an `Appraised`: nothing has
judged it, and the trust-decision logic consumes judged outcomes only.
Later, `ledger_request(bid)` on an attestation predicate, or
`examples/appraise_from_ledger.py`, judges the stored measurement under the
protocol's session or any other policy; the first such appraisal is
labelled `deferred`, later ones `audit` or whatever the caller names them.
The Rocq driver does this with `--ledger --ledger-mode measure`. In the
ordinary live flow, a measurement whose appraisal run fails is still
recorded, with `error` saying why, and the outcome fails (plan N.4).

## Records and keys

Field-by-field reference: [ledger_records.md](ledger_records.md).

Every record is canonical JSON (sorted keys, no whitespace, UTF-8) with a
common envelope: `schema` (`pybb-ledger/v2`), `kind`, `bid`, `created_at`,
`committer_fp`, `pybb_version`, `appraiser_id`. The full schema is section K
of the plan. Every CVM run output is one **bundle**, keyed by the sha256 of
the nonce drawn inside that run; what it is evidence of is its `role` and
its `inputs`. Keys:

| key | holds |
|---|---|
| `bundle/<bid>` | one CVM run output: `role` (`measurement`, `appraisal`, `provision`, `challenge`, `stack`, `config`), the hashes of the exact term/session/manifest the CVM was handed, `response_sha256`, `blob` (hash, size, every location), `rawev_sha256`, `nonce` (which ASP, the bytes), `signature`, `assurance`, `freshness`; an appraisal adds `inputs` (the bundle it judged, with its `hashevidence` binding), `verdict`, `appraisal_kind` and, for a stack audit, `baseline`; a provisioning bundle adds `provision`; a `stack` bundle adds `stack`, a `config` bundle `config` (its archived input files) (legacy nonce-less bundles: `bundle/sha256:<hash>`) |
| `blessing/<stack bid>` | the operator's approval of a `stack` bundle: its target ids and the measured values read off its signed package, the goldens later stack audits judge against |
| `judged_by/<bid>/<appraisal bid>` | pointer from a bundle to each appraisal of it: "every appraisal of X" is one prefix scan |
| `mirror/<store>/<state_tx>` | one push to an evidence store: commit, ledger head, journal range, blobs carried, blobs skipped |
| `restore/<created_at>` | a restore event |

A live run's commit is one batch: the measurement bundle, its live appraisal
bundle (`appraisal_kind: live`) and the pointer between them. A later
appraisal of the same measurement — an audit, or a *different policy* via a
session override — is one more appraisal bundle plus pointer; judging an
appraisal bundle (its signature, nonce and binding, inside the CVM) is just
an appraisal whose input is an appraisal. Bundles state at commit time where
their bytes are and will be (`local` plus the content-addressed path in each
configured store); durability is whether the store has the file, and mirror
records witness the pushes. Nothing is appended to a bundle after its batch.

**Assurance** is computed from the package as produced: `signed+nonce`,
`signed`, `nonce` or `none`. **Freshness** is `post-hoc` for every run today:
the nonce binds the package and makes it unique and orderable, but the
appraiser first learns it from the package, so it is not a challenge.
Pre-registered challenges are the section G follow-up.

## Reading the ledger without pybb

```bash
immuclient login pybb
immuclient use pybb2
immuclient get bundle/<bid>                      # any key, as canonical JSON
immuclient scan --prefix judged_by/<bid>/        # every appraisal of a bundle
immuclient scan --prefix mirror/                 # every push to an evidence store
immuclient query "SELECT key, role, appraisal_kind, passed, assurance, created_at FROM attestation_records WHERE protocol_id = 'temp_control_aadl_slang_l1a' AND role = 'appraisal' ORDER BY created_at DESC LIMIT 20"
immuclient query "SELECT key, appraisal_kind, passed FROM attestation_records WHERE input_bid = '<bid>'"
immuclient query "SELECT key FROM attestation_records WHERE kind = 'bundle' AND assurance <> 'signed+nonce'"
```

`attestation_records` is a SQL mirror written after each KV batch; each row's
`content_sha256` is the hash of the KV value, so a row can be checked against
`immuclient get`. The mirror is a convenience view and
`ImmudbLedger.rebuild_mirror()` regenerates it from the KV history.

## Re-appraising and auditing

```bash
python examples/appraise_from_ledger.py --latest temp_control_aadl_slang_l1a       # graph + fresh signed appraisal (audit)
python examples/appraise_from_ledger.py <appraisal bid>                              # judge an appraisal bundle inside the CVM
python examples/appraise_from_ledger.py <bid> --kind slices-only --session s.json    # a different appraisal policy
python examples/appraise_from_ledger.py <bid> --no-run                               # graph only
```

`appraise_bundle` fetches the bundle through its stated locations (local
path, then the evidence store), refuses bytes whose hash is not the
record's, checks that the package reproduces the recorded bundle id, runs
the same signed appraisal term under the protocol's session (or a session
override: a different policy, pinned by `session_sha256`), and commits one
appraisal bundle with `inputs=[bid]`, its `appraisal_kind` label and, under
the same session, `agrees_with_live`. Given an appraisal bundle it judges
that package's signature, appraiser nonce and binding inside the CVM
(`sig_appr`, `nonce_appr`, `goldenbytes_appr` with the judged bundle's
`rawev_sha256` as golden), with the appraiser nodes passed through
`magic_appr`. Every appraisal is its own nonce'd, signed bundle; the graph
printed by the example is measurement → its appraisals → appraisals of
those.

## The evidence repository

```bash
export PYBB_EVIDENCE_REPO=~/src/pybb-evidence
python examples/ledger_push.py [--archive-dir evidence/<dir>] [--bundles golden] [--backup-segment seg.bkp]
python examples/ledger_reconcile.py --verify-all
```

A push copies every blob a bundle states for this store but the clone does
not have into `blobs/<sha256>.json.gz`, writes every record under
`ledger/bundles/`, `ledger/judged_by/`, `ledger/mirror/`, appends
`ledger/journal.jsonl` (one line per ledger tx with each key's content
hash), writes `ledger/state/<tx>.json` (the ledger head), updates
`runs/<archive_dir>/manifest.json`, makes one commit, pushes, and writes
one `mirror` record witnessing the push (commit, head, journal range, blobs
carried and skipped). Reconcile lists what is stated but not yet in the
store, re-verifies committed blobs, and compares the live head with the
mirrored state, which catches a rolled-back or replaced ledger.

Hot-backup segments for an exact immudb restore are produced by the
operator (`immuadmin hot-backup pybb2 -o seg.bkp` after `immuadmin login`)
and added with `--backup-segment`.

## Restore

```bash
python examples/ledger_restore.py verify  <clone>                 # hashes, journal contiguity, blobs
python examples/ledger_restore.py replay  <clone> --into-immudb   # content restore into a fresh database
python examples/ledger_restore.py exact   <clone> --db pybb2      # prints the immuadmin hot-restore command
```

`verify` must pass before anything is loaded. Journal tx ids strictly
increase but are not contiguous on immudb, because SQL mirror and DDL
transactions carry no records. `replay` writes one batch per journal line
with the mirrored canonical values; the new instance has new tx ids, and a
`restore` record names the source commit. `exact` restores an
identical instance from backup segments so the old client state still
verifies. The full procedure and its timing estimate are in plan section H.4.

## Other members

Anyone can read the public mirror and run the fetch, audit, and verify
tooling against it. Pushing needs write access on `ku-sldg/pybb-ledger`,
and the ledger behind it is a single immudb instance: the repository
layout assumes one ledger per repository, so a second immudb must not
push into it. The two ways to open it up — a shared immudb instance, or
per-appraiser namespacing of the journal and state in the repo — are
documented and awaiting a decision in plan section J.

## Limits to keep in mind

- Freshness is post-hoc. A compromised CVM or ASP on the same host can
  produce a package the nonce cannot distinguish from a fresh one.
- Tool identity is drift detection and provenance, not a root of trust: the
  tools measure themselves. A TPM-backed mechanism is the right tool for
  that layer.
- The verified summarizer does not type-check an audit of an appraisal
  package; those verdicts are read by slot layout and recorded as
  `interpreter: legacy-walker`.
- A run's stack and configuration are derived from the same writer's
  latest `stack` and `config` bundles at a lower transaction. They say what
  was last measured, not that nothing changed since: a rebuilt binary is
  invisible until the operator runs `measure stack` again, and only an
  `audit` against a blessing turns the difference into a verdict. A run
  whose pins do not match the config in force ran under inputs nobody
  measured.
- Legacy bundles (provisioned before nonces) are recorded by content hash
  with `assurance: signed` until the protocol is re-provisioned.
- Provisioning overwrites `golden/_bundles/<pid>/provision_bundle.json`. A
  bundle re-blessed before its predecessor was pushed leaves the older
  bundle record pointing at bytes that no longer exist; push after every
  blessing, or expect that record to stay pending in `ledger_reconcile.py`.
