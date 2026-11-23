# From scratch: pybb, your own attestation ledger, and the Rocq scenario

This guide is for someone who has none of it yet: it takes a fresh machine
to a working pybb stack, a fresh immudb ledger of your own, the context
evidence (stack and configuration bundles) recorded and blessed, and the
temp-control Rocq scenario running under that ledger — then shows how to
read what the ledger says. It assumes nothing from the maintainer's
machine: no shared database, no shared evidence repository, no shared keys.

Companion documents: [INSTALL.md](INSTALL.md) (the installer in detail, all
platforms and both demos), [ledger.md](ledger.md) (the ledger's model and
day-to-day use), [ledger_records.md](ledger_records.md) (every record
field), [demo_rocq.md](demo_rocq.md) (the scenario's arcs).

## 0. What you end up with

| piece | where |
|---|---|
| pybb checkout with its virtualenv | `~/Claude_workspace/pybb/.venv` |
| CVM and asp-libs, built | `~/Claude_workspace/cvm`, `~/Claude_workspace/asp-libs/target/release` |
| Rocq Prover (opam switch `5.2`) and tool wrappers | `~/.opam/5.2`, `~/Claude_workspace/bin` |
| the Rocq target, provisioned and blessed on **your** paths and tool bytes | `targets/temp-control-rocq`, `golden/`, `tests/fixtures/temp_control_rocq_*` |
| an immudb server with database `pybb2` and user `pybb` | `127.0.0.1:3322` |
| your installation's identity | `~/.pybb/appraiser_id` (random, created once) and the verifying key's fingerprint |
| `stack` and `config` bundles, a `blessing` | in `pybb2`, bytes archived under `~/.pybb/context/` and `evidence/` |
| the Rocq scenario's runs as bundles, derivable to that stack and config | in `pybb2`, bytes under `evidence/` |

Budget 10–15 GB of disk and 25–60 minutes for the stack (the opam build
of the CVM dominates); the ledger steps take minutes.

## 1. The pybb stack

Supported: macOS arm64 and Linux x86_64 (Debian/Ubuntu). Prerequisites
are in [INSTALL.md § Prerequisites](INSTALL.md#prerequisites): Xcode
command-line tools and Homebrew on macOS, `sudo` on Linux, network access
to github.com, the opam repositories and crates.io. No API keys.

```bash
git clone -b dev https://github.com/ku-sldg/pybb.git ~/Claude_workspace/pybb
```

```bash
cd ~/Claude_workspace/pybb && scripts/install.sh --skip-sireum
```

`--skip-sireum` leaves out the isolette/HAMR toolchain, which the Rocq
scenario does not need. The installer is idempotent and resumable
(`--from <step>`); its last Rocq step provisions and blesses the target on
your machine, which **rewrites tracked files** under `tests/fixtures/` and
`golden/` — expected, leave them uncommitted. Check the result:

```bash
scripts/check_install.sh --ready
```

You want `readiness: PASS` for the Rocq driver. If you prefer to run the
Rocq provisioning yourself:

```bash
.venv/bin/python examples/temp_control_rocq.py --provision --bless-model --bless-tools
```

From here on, `python` means `.venv/bin/python` from the pybb checkout.

## 2. A fresh immudb and the ledger database

The ledger is one immudb database. Everything pybb needs lives in the
`ledger` extra of the package and one helper script.

```bash
.venv/bin/pip install -e '.[ledger]'
```

**macOS** (Homebrew installs immudb 1.11+ and starts it as a service):

```bash
scripts/immudb_dev.sh install
```

**Linux**: download the `immudb` and `immuclient` binaries for your
platform from the immudb releases page (codenotary/immudb on GitHub), put
them on your `PATH`, and run the server with a data directory of your
choice, for example as a systemd service or, to start with:

```bash
immudb --dir ~/immudb-data
```

Either way the server listens on `127.0.0.1:3322` with the default admin
account (`immudb` / `immudb`). Now create the database and pybb's own
non-admin user. Choose a password of 8–32 characters with upper and lower
case, a digit and a symbol:

```bash
export PYBB_IMMUDB_PASSWORD='<your pybb password>'
```

```bash
scripts/immudb_dev.sh bootstrap
```

This creates database `pybb2` (or the name in `PYBB_IMMUDB_DB`) and user
`pybb` with read/write on it. pybb reads the password from
`PYBB_IMMUDB_PASSWORD` or, when that is unset, from
`~/.pybb/immudb_password`; store it there so every later command and shell
finds it:

```bash
mkdir -p ~/.pybb && umask 077 && printf '%s\n' "$PYBB_IMMUDB_PASSWORD" > ~/.pybb/immudb_password
```

Change the default admin password once, and keep the new one for yourself:

```bash
scripts/immudb_dev.sh rotate-admin '<new admin password>'
```

(`export IMMUDB_ADMIN_PASSWORD=...` afterwards if you re-run `bootstrap`.)
`scripts/immudb_dev.sh status` shows the service state and version. The
first time pybb talks to the database it writes a client state file,
`~/.pybb/immudb_state_127.0.0.1_3322_pybb2`, the verified root every
later read is checked against. Do not copy that file between machines.

The ledger backend tests confirm the client end to end against an
ephemeral server:

```bash
.venv/bin/python -m pytest -m ledger -q
```

## 3. Your installation's identity

Two values go into every record you write:

- `appraiser_id`: a random id created once at `~/.pybb/appraiser_id` the
  first time pybb needs it. It is never a hostname or user name.
- `committer_fp`: the fingerprint of the verifying public key, by default
  asp-libs' demo key (`PYBB_VERIFY_KEY` overrides it). The ASP binaries
  sign with the matching private key; if you deploy your own key pair in
  asp-libs, point `PYBB_VERIFY_KEY` at the public half before step 4, since
  the stack bundle measures that file.

Nothing else identifies you. Two installations writing one ledger are told
apart by these and by the signatures inside their packages.

## 4. Record the context: stack and configurations

Before the first run, record what your runs will run on. Both commands
run the CVM once over live files and commit unconditionally; pybb never
does this on its own (plan section O).

The installation — the CVM binary, the verified summarizer, the verifying
key, every executable in asp-libs' `target/release`, and how pybb invokes
the CVM — becomes a signed `stack` bundle, and `--bless` records your
approval of it:

```bash
.venv/bin/python examples/ledger_context.py measure stack --bless --note "fresh install"
```

Each protocol's exact inputs (the term, session and manifest pybb hands the
CVM, for every term constructor) become one `config` bundle per protocol:

```bash
.venv/bin/python examples/ledger_context.py measure config temp_control_rocq_model temp_control_rocq_contracts temp_control_rocq_verification
```

(`--all` does every protocol under `tests/fixtures/`.) List what you have:

```bash
.venv/bin/python examples/ledger_context.py list
```

Repeat `measure stack` after rebuilding asp-libs or the CVM (then `audit`
and `bless` the new bundle, step 7), and `measure config <protocol>` after
editing or re-provisioning a protocol. Nothing reminds you; the ledger
shows afterwards which runs happened under an unmeasured configuration. If
you would rather pybb re-measure for you, set the refresh policy
(`LedgerConfig.context.refresh`: `every_episode`, `every_run` or
`max_age:<seconds>`); every run's claim records which policy was in force
and what it re-measured.

## 5. Run the Rocq scenario under the ledger

Readiness first. With a ledger it also checks that your installation has a
stack bundle and a blessing:

```bash
.venv/bin/python examples/temp_control_rocq.py --ready --ledger immudb
```

Then the status episode: every protocol runs as the nonce'd two-run flow
(a signed measurement, then a signed appraisal of it), and both bundles
land in one ledger transaction:

```bash
.venv/bin/python examples/temp_control_rocq.py --ready --status --ledger immudb
```

Every arc of the scenario takes the same flag — the tamper and repair
scenes, for example:

```bash
.venv/bin/python examples/temp_control_rocq.py --tamper-axiom --ledger immudb
```

Two variations worth seeing once. Record measurements only, to be judged
later by anyone with the package (`--ledger-mode measure`), and do the
measurement and appraisal in one CVM run (`--bundle-shape combined`):

```bash
.venv/bin/python examples/temp_control_rocq.py --status --ledger immudb --ledger-mode measure
```

```bash
.venv/bin/python examples/temp_control_rocq.py --status --ledger immudb --bundle-shape combined
```

The whole scripted demo also runs under the ledger; see
[demo_rocq.md](demo_rocq.md) for the arcs and pass `--ledger immudb`
through where the scene takes driver flags.

## 6. Read the ledger

For the newest verification measurement, what a reader derives — your
stack bundle and whether it is blessed, the config bundle in force, and
whether the run's term/session/manifest hashes match that config:

```bash
.venv/bin/python examples/ledger_context.py show --latest temp_control_rocq_verification
```

The bundle graph — the measurement, every appraisal recorded over it, the
derived context beside each — without running anything:

```bash
.venv/bin/python examples/appraise_from_ledger.py --latest temp_control_rocq_verification --no-run
```

Appraise a stored bundle again (a fresh, signed CVM appraisal, recorded as
one more bundle pointing at it; there are no kinds of appraisal, the chain
order says which came first):

```bash
.venv/bin/python examples/appraise_from_ledger.py --latest temp_control_rocq_verification
```

Straight from immudb, with the client the server ships:

```bash
immuclient login pybb && immuclient use pybb2 && immuclient scan --prefix bundle/
```

```bash
immuclient query "SELECT key, role, passed, created_at FROM attestation_records WHERE kind = 'bundle' ORDER BY created_at"
```

## 7. Audit the context itself

A stack bundle is judged inside the CVM against the goldens of a blessing
(the latest, or `--against blessing/<bid>`); a config bundle against the
hashes of the files it archived. Take the bundle ids from `list`:

```bash
.venv/bin/python examples/ledger_context.py audit <stack bid>
```

```bash
.venv/bin/python examples/ledger_context.py audit <config bid>
```

After a rebuild the sequence is: `measure stack` (new bundle S2), `audit
S2` (fails on the rebuilt targets against the old blessing — that failing
appraisal stays on the ledger), review, `bless S2`, `audit S2` again
(passes). Runs between the rebuild and the new measurement derive the old
stack bundle, which is the honest record.

## 8. Optional: your own evidence repository

The ledger holds hashes and pointers; a git repository of your choice
holds the bytes and a complete mirror of the records, so someone with only
the repository can verify and even rebuild the ledger. Create an empty
repository on your hosting of choice, clone it, and tell pybb where:

```bash
git clone <your evidence repo url> ~/Claude_workspace/pybb-ledger-mirror
```

```bash
echo ~/Claude_workspace/pybb-ledger-mirror > ~/.pybb/evidence_repo
```

(or `export PYBB_EVIDENCE_REPO=<clone path>`). From now on every new
bundle states, at commit time, the content-addressed path its bytes will
have in that store. After an episode, push, then check:

```bash
.venv/bin/python examples/ledger_push.py
```

```bash
.venv/bin/python examples/ledger_reconcile.py --verify-all
```

Bundles recorded before you configured the repository state no location in
it; `ledger_reconcile.py` lists them as pending and they stay local. The
repository's `origin` remote names the store (`github:owner/name`); protect
its default branch. `examples/ledger_restore.py verify <clone>` checks a
clone end to end, and `replay` rebuilds a ledger from it.

## 9. Starting over

A fresh ledger is a new database name: set `PYBB_IMMUDB_DB=pybb3`, run
`scripts/immudb_dev.sh bootstrap` again, and record the context again
(step 4). Deleting an immudb database needs the service restarted before a
database of the same name can be recreated; the old client state file
under `~/.pybb/` must be removed too, or verified reads fail against the
new instance. Running the same scenario twice is fine: every run draws a
new nonce, and the ledger refuses only a package whose nonce it already
holds.

## Troubleshooting

- **`readiness: FAIL` with "no stack bundle for this writer"** or **"no
  blessing"**: step 4 was skipped, or you are writing with a different
  `appraiser_id` (a different `~/.pybb`). Measure and bless the stack.
- **`show` says `inputs stale`**: the protocol's inputs changed after the
  last `measure config` (an edit, a re-provisioning). Run `measure config
  <protocol>`; the run that was stale stays stale, truthfully.
- **`show` says `none` for a run**: it was recorded before any stack or
  config bundle from this writer existed.
- **`duplicate nonce`**: the same package was submitted twice; nothing is
  recorded. A fresh run is a fresh nonce.
- **`ledger commit failed`** with a connection error: the service is down
  (`scripts/immudb_dev.sh status`) or the password is missing from both
  `PYBB_IMMUDB_PASSWORD` and `~/.pybb/immudb_password`.
- **verified read fails right after recreating a database**: stale
  `~/.pybb/immudb_state_127.0.0.1_3322_<db>`; remove it (only when you
  know the server was recreated).
- **`git status` shows `tests/fixtures/` and `golden/` modified**: the
  Rocq provisioning rooted the baselines in your paths; expected, keep
  them uncommitted.
