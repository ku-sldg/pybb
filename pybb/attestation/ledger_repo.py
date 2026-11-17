"""
The evidence repository: durable blobs, ledger mirror, and restore
(docs/ledger_plan.md, section H; decisions 2 and 5).

A git repository — any repository the operator chooses, named by the path
of a local clone in `LedgerConfig.evidence_repo`; its GitHub slug is read
from the clone's `origin` remote — holds, content-addressed and append-only
by convention:

    blobs/<sha256>.json.gz              evidence, appraisal, components, bundles
    ledger/journal.jsonl                one line per ledger tx: {tx, ts, db, keys:{key: content_sha256}}
    ledger/records/<nid>/<kind>.json    nonce/evidence/verdict, appraisal-<seq>, locator-<seq>
    ledger/bundles/<id>.json            bundle records
    ledger/restores/<created_at>.json   restore records
    ledger/state/<tx>.json              the ledger backend's head at each push
    ledger/backups/                     immuadmin hot-backup segments (operator-produced, H.3)
    runs/<archive_dir>/manifest.json    push-time grouping: protocol -> nid -> blobs

`push_archive` copies what the ledger holds locally into the clone, makes
one commit per push (a consistent snapshot), pushes, and appends `github`
locator records so runs become durable. `reconcile` reports what is not yet
durable and checks the live head against the mirrored states.
`verify_mirror` / `replay` are the restore path (H.4): a mirror is checked
against its own hashes before anything is loaded, then replayed tx by tx
into a fresh ledger. The exact restore of an immudb instance from backup
segments is `immuadmin hot-restore`, documented in `exact_restore_command`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from pydantic import BaseModel

from .ledger import (
    BundleRecord,
    Ledger,
    LedgerConfig,
    LedgerError,
    LedgerRecord,
    Locator,
    LocatorRecord,
    RestoreRecord,
    SignatureInfo,
    canonical_json,
    describe_package,
    key_for,
    load_appraiser_id,
    parse_record,
    pybb_version,
    sha256_hex,
    utc_now,
)

# ── git plumbing ─────────────────────────────────────────────────────────────


class EvidenceRepo:
    """A local clone of the evidence repository (plan H.1)."""

    def __init__(self, path: str | Path, remote: str = "origin", slug: Optional[str] = None):
        self.path = Path(os.path.expanduser(str(path)))
        self.remote = remote
        self._slug = slug
        if not (self.path / ".git").exists():
            raise LedgerError(f"{self.path} is not a git clone (LedgerConfig.evidence_repo)")

    def git(self, *args: str, check: bool = True, input_bytes: Optional[bytes] = None) -> str:
        r = subprocess.run(["git", "-C", str(self.path), *args], capture_output=True,
                           input=input_bytes, check=False)
        if check and r.returncode != 0:
            raise LedgerError(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
        return r.stdout.decode(errors="replace").strip()

    def git_bytes(self, *args: str) -> bytes:
        r = subprocess.run(["git", "-C", str(self.path), *args], capture_output=True, check=False)
        if r.returncode != 0:
            raise LedgerError(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
        return r.stdout

    def slug(self) -> str:
        """`owner/name` for a hosted remote (GitHub or any host), the bare
        repository's basename for a local or file remote; recorded as the
        `repo` of github locators."""
        if self._slug:
            return self._slug
        url = self.git("remote", "get-url", self.remote, check=False) or str(self.path)
        m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?[^/:]+[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$", url)
        if m and not url.startswith(("/", "file://", ".")):
            self._slug = f"{m.group('owner')}/{m.group('name')}"
        else:
            name = url.rstrip("/").rsplit("/", 1)[-1]
            self._slug = name[:-4] if name.endswith(".git") else name
        return self._slug

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def blob_sha(self, relpath: str) -> str:
        return self.git("hash-object", str(self.path / relpath))

    def has_commit(self, commit: str) -> bool:
        return subprocess.run(["git", "-C", str(self.path), "cat-file", "-e", f"{commit}^{{commit}}"],
                              capture_output=True).returncode == 0

    def show(self, commit: str, relpath: str) -> bytes:
        return self.git_bytes("show", f"{commit}:{relpath}")

    def commit_all(self, message: str) -> Tuple[str, bool]:
        """Stage everything and commit; returns (head, committed)."""
        self.git("add", "-A")
        if not self.git("status", "--porcelain"):
            return self.head(), False
        self.git("commit", "-q", "-m", message)
        return self.head(), True

    def push(self) -> None:
        branch = self.git("rev-parse", "--abbrev-ref", "HEAD")
        self.git("push", "-q", self.remote, branch)

    def fetch(self) -> None:
        self.git("fetch", "-q", self.remote, check=False)


# ── layout ───────────────────────────────────────────────────────────────────


def blob_relpath(sha256: str) -> str:
    return f"blobs/{sha256}.json.gz"


def record_relpath(key: str, rec: LedgerRecord) -> str:
    kind = rec.kind
    if kind in ("nonce", "evidence", "verdict"):
        return f"ledger/records/{rec.nid}/{kind}.json"
    if kind in ("appraisal", "locator"):
        return f"ledger/records/{rec.nid}/{kind}-{rec.seq}.json"  # type: ignore[attr-defined]
    if kind == "bundle":
        return f"ledger/bundles/{key.split('/', 1)[1].replace(':', '-')}.json"
    if kind == "restore":
        return f"ledger/restores/{rec.created_at}.json"
    return f"ledger/other/{key.replace('/', '_')}.json"


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def last_journaled_tx(repo: EvidenceRepo) -> int:
    jp = repo.path / "ledger/journal.jsonl"
    if not jp.is_file():
        return 0
    last = 0
    with open(jp, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                last = json.loads(line)["tx"]
    return last


# ── pending blobs: what the ledger holds locally but not yet in the repo ──────


class PendingBlob(BaseModel):
    nid: Optional[str]
    target: str  # evidence | appraisal | components | bundle
    blob_sha256: str
    local: Locator
    key: str  # the record whose blob this is (for the manifest)


def pending_blobs(ledger: Ledger, archive_dir: Optional[Path] = None) -> List[PendingBlob]:
    """Every blob with a local locator and no github locator (per blob)."""
    local: Dict[str, PendingBlob] = {}
    remote: set = set()
    for _tx, key, rec in ledger.history():
        if rec.kind == "evidence":
            for loc in rec.locators:  # type: ignore[attr-defined]
                if loc.kind == "local":
                    local.setdefault(rec.blob_sha256, PendingBlob(  # type: ignore[attr-defined]
                        nid=rec.nid, target="evidence", blob_sha256=rec.blob_sha256,  # type: ignore[attr-defined]
                        local=loc, key=key))
                elif loc.kind == "github":
                    remote.add(rec.blob_sha256)  # type: ignore[attr-defined]
        elif rec.kind == "bundle":
            for loc in rec.locators:  # type: ignore[attr-defined]
                if loc.kind == "local":
                    local.setdefault(rec.blob_sha256, PendingBlob(  # type: ignore[attr-defined]
                        nid=rec.nid, target="bundle", blob_sha256=rec.blob_sha256, local=loc, key=key))  # type: ignore[attr-defined]
                elif loc.kind == "github":
                    remote.add(rec.blob_sha256)  # type: ignore[attr-defined]
        elif rec.kind == "locator":
            loc = rec.locator  # type: ignore[attr-defined]
            if loc.kind == "local":
                local.setdefault(rec.blob_sha256, PendingBlob(  # type: ignore[attr-defined]
                    nid=rec.nid, target=rec.target, blob_sha256=rec.blob_sha256, local=loc, key=key))  # type: ignore[attr-defined]
            elif loc.kind == "github":
                remote.add(rec.blob_sha256)  # type: ignore[attr-defined]
    out = [pb for sha, pb in local.items() if sha not in remote]
    if archive_dir is not None:
        root = Path(archive_dir).resolve()
        out = [pb for pb in out if _under(Path(pb.local.path).resolve(), root)]
    return out


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


# ── push ─────────────────────────────────────────────────────────────────────


class PushReport(BaseModel):
    commit: str = ""
    committed: bool = False
    pushed: bool = False
    blobs: List[str] = []
    skipped: List[str] = []  # blobs whose local bytes are gone or mismatch
    journal_from_tx: int = 0
    journal_to_tx: int = 0
    locators_appended: int = 0
    state_tx: int = 0
    problems: List[str] = []


def push_archive(ledger: Ledger, repo: EvidenceRepo, config: LedgerConfig,
                 archive_dir: Optional[Path] = None, push: bool = True,
                 backup_segment: Optional[Path] = None) -> PushReport:
    """
    Plan H.2: copy pending blobs and every ledger record into the clone,
    append journal lines for txs since the last push, write the state file,
    optionally add a hot-backup segment, commit once, push, then append a
    `github` locator record per pushed blob (verified by re-reading the
    committed bytes).
    """
    rep = PushReport()
    appraiser_id = config.appraiser_id or load_appraiser_id(config.state_dir)
    manifest: Dict[str, Dict[str, Dict[str, str]]] = {}

    # 1. blobs
    pend = pending_blobs(ledger, archive_dir)
    for pb in pend:
        src = Path(pb.local.path)
        if not src.is_file():
            rep.skipped.append(pb.blob_sha256)
            rep.problems.append(f"{pb.target} blob {pb.blob_sha256[:12]}… not at {src}")
            continue
        data = src.read_bytes()
        if sha256_hex(data) != pb.blob_sha256:
            rep.skipped.append(pb.blob_sha256)
            rep.problems.append(f"{src}: bytes do not match the ledger's blob_sha256")
            continue
        dest = repo.path / blob_relpath(pb.blob_sha256)
        if not dest.exists():
            _write(dest, data)
        rep.blobs.append(pb.blob_sha256)
        run_dir = src.parent.name
        proto = _protocol_of(ledger, pb)
        manifest.setdefault(run_dir, {}).setdefault(proto, {})[f"{pb.target}:{pb.nid or ''}"] = blob_relpath(pb.blob_sha256)

    # 2. records (every record, canonical bytes; existing files are identical by construction)
    for _tx, key, rec in ledger.history():
        dest = repo.path / record_relpath(key, rec)
        if not dest.exists():
            _write(dest, rec.canonical())

    # 3. journal
    since = last_journaled_tx(repo)
    rep.journal_from_tx = since + 1
    jp = repo.path / "ledger/journal.jsonl"
    jp.parent.mkdir(parents=True, exist_ok=True)
    with open(jp, "a", encoding="utf-8") as f:
        for line in ledger.journal(since):
            f.write(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n")
            rep.journal_to_tx = line["tx"]
    if rep.journal_to_tx == 0:
        rep.journal_to_tx = since

    # 4. state
    st = ledger.state()
    st["captured_at"] = utc_now()
    rep.state_tx = int(st["tx_id"])
    _write(repo.path / f"ledger/state/{st['tx_id']:012d}.json", canonical_json(st))

    # 5. backup segment (operator-produced, H.3)
    if backup_segment is not None:
        seg = Path(backup_segment)
        if seg.is_file():
            shutil.copy2(seg, repo.path / "ledger/backups" / seg.name)
        else:
            rep.problems.append(f"backup segment {seg} not found")

    # 6. manifests
    for run_dir, protos in manifest.items():
        mp = repo.path / "runs" / run_dir / "manifest.json"
        existing = json.loads(mp.read_text()) if mp.is_file() else {}
        for proto, entries in protos.items():
            existing.setdefault(proto, {}).update(entries)
        _write(mp, canonical_json(existing))

    # 7. commit, push
    rep.commit, rep.committed = repo.commit_all(
        f"ledger push: txs {rep.journal_from_tx}-{rep.journal_to_tx}, {len(rep.blobs)} blob(s), state tx {rep.state_tx}")
    if push and rep.committed:
        try:
            repo.push()
            rep.pushed = True
        except LedgerError as e:
            rep.problems.append(str(e))
    elif push and not rep.committed:
        rep.pushed = True  # nothing new; the remote already has it

    # 8. github locators (only for blobs actually in the commit; verified by re-reading)
    slug = repo.slug()
    env = dict(committer_fp="", pybb_version=pybb_version(), appraiser_id=appraiser_id)
    for pb in pend:
        if pb.blob_sha256 not in rep.blobs:
            continue
        rel = blob_relpath(pb.blob_sha256)
        committed_bytes = repo.show(rep.commit, rel)
        verified = sha256_hex(committed_bytes) == pb.blob_sha256
        loc = Locator(kind="github", path=rel, repo=slug, commit=rep.commit, git_blob_sha=repo.blob_sha(rel))
        if pb.target == "bundle":
            nid = pb.nid or f"sha256:{pb.blob_sha256}"
            seq = _next_locator_seq(ledger, nid)
            rec = LocatorRecord(nid=nid, seq=seq, target="bundle", blob_sha256=pb.blob_sha256,
                                locator=loc, verified=verified, **env)
        else:
            seq = _next_locator_seq(ledger, pb.nid or "")
            rec = LocatorRecord(nid=pb.nid or "", seq=seq, target=pb.target,  # type: ignore[arg-type]
                                blob_sha256=pb.blob_sha256, locator=loc, verified=verified, **env)
        ledger.append_locator(rec)
        rep.locators_appended += 1
    return rep


def _protocol_of(ledger: Ledger, pb: PendingBlob) -> str:
    if pb.nid:
        for key in (f"evidence/{pb.nid}", f"bundle/{pb.nid}"):
            rec = ledger.get_record(key)
            if rec is not None:
                return getattr(rec, "protocol_id", "") or ""
    rec = ledger.get_record(pb.key)
    return getattr(rec, "protocol_id", "") or "" if rec else ""


def _next_locator_seq(ledger: Ledger, nid: str) -> int:
    seq = 0
    for _tx, key, rec in ledger.history():
        if rec.kind == "locator" and rec.nid == nid:
            seq = max(seq, rec.seq)  # type: ignore[attr-defined]
    return seq + 1


# ── resolving github locators ────────────────────────────────────────────────

_REPO_CACHE: Dict[str, EvidenceRepo] = {}


def configured_repo(config: Optional[LedgerConfig] = None) -> Optional[EvidenceRepo]:
    path = (config.evidence_repo if config else None) or os.environ.get("PYBB_EVIDENCE_REPO")
    if not path:
        return None
    if path not in _REPO_CACHE:
        try:
            _REPO_CACHE[path] = EvidenceRepo(path)
        except LedgerError:
            return None
    return _REPO_CACHE[path]


def resolve_github_locator(loc: Locator, config: Optional[LedgerConfig] = None) -> Optional[bytes]:
    """Bytes of a `github` locator: from the configured clone at the recorded
    commit (fetching first if the commit is unknown), else through `gh api`
    on the recorded git blob. None when neither is available."""
    repo = configured_repo(config)
    if repo is not None and loc.commit and loc.path:
        if not repo.has_commit(loc.commit):
            repo.fetch()
        if repo.has_commit(loc.commit):
            try:
                return repo.show(loc.commit, loc.path)
            except LedgerError:
                pass
    if loc.repo and loc.git_blob_sha and shutil.which("gh") and "/" in loc.repo:
        r = subprocess.run(["gh", "api", f"repos/{loc.repo}/git/blobs/{loc.git_blob_sha}", "--jq", ".content"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return base64.b64decode(r.stdout.replace("\n", ""))
    return None


# ── reconcile ────────────────────────────────────────────────────────────────


class ReconcileReport(BaseModel):
    pending: List[PendingBlob] = []
    verified_remote: int = 0
    remote_mismatches: List[str] = []
    live_state: dict = {}
    mirrored_state: dict = {}
    state_ok: Optional[bool] = None
    problems: List[str] = []

    def __bool__(self) -> bool:
        return not self.pending and not self.remote_mismatches and self.state_ok is not False and not self.problems


def reconcile(ledger: Ledger, repo: EvidenceRepo, verify_all: bool = False) -> ReconcileReport:
    """Plan H.2 step 3: what is not durable, whether committed blobs still hash
    right, and whether the live head is consistent with the latest mirrored
    state (a rolled-back or rewritten server is caught here)."""
    rep = ReconcileReport(pending=pending_blobs(ledger))
    if verify_all:
        for _tx, key, rec in ledger.history():
            if rec.kind != "locator" or rec.locator.kind != "github":  # type: ignore[attr-defined]
                continue
            loc = rec.locator  # type: ignore[attr-defined]
            try:
                data = repo.show(loc.commit, loc.path)
            except LedgerError as e:
                rep.remote_mismatches.append(f"{key}: {e}")
                continue
            if sha256_hex(data) != rec.blob_sha256:  # type: ignore[attr-defined]
                rep.remote_mismatches.append(f"{key}: committed bytes do not hash to blob_sha256")
            else:
                rep.verified_remote += 1
    rep.live_state = ledger.state()
    states = sorted((repo.path / "ledger/state").glob("*.json")) if (repo.path / "ledger/state").is_dir() else []
    if states:
        rep.mirrored_state = json.loads(states[-1].read_text())
        live_tx, mir_tx = int(rep.live_state["tx_id"]), int(rep.mirrored_state["tx_id"])
        if live_tx < mir_tx:
            rep.state_ok = False
            rep.problems.append(f"live ledger is at tx {live_tx}, behind the mirrored tx {mir_tx}: rollback or wrong instance")
        elif live_tx == mir_tx:
            rep.state_ok = rep.live_state.get("tx_hash_hex") == rep.mirrored_state.get("tx_hash_hex")
            if not rep.state_ok:
                rep.problems.append(f"live head hash at tx {live_tx} differs from the mirrored one: history rewritten")
        else:
            rep.state_ok = True  # ahead; the next push will witness the new head
    return rep


# ── restore (plan H.4) ───────────────────────────────────────────────────────


class MirrorReport(BaseModel):
    txs: int = 0
    records: int = 0
    blobs_checked: int = 0
    problems: List[str] = []

    def __bool__(self) -> bool:
        return not self.problems


def _record_file_for_key(repo_path: Path, key: str) -> Optional[Path]:
    kind, rest = key.split("/", 1)
    if kind in ("nonce", "evidence", "verdict"):
        p = repo_path / f"ledger/records/{rest}/{kind}.json"
    elif kind in ("appraisal", "locator"):
        nid, seq = rest.split("/")
        p = repo_path / f"ledger/records/{nid}/{kind}-{seq}.json"
    elif kind == "bundle":
        p = repo_path / f"ledger/bundles/{rest.replace(':', '-')}.json"
    elif kind == "restore":
        p = repo_path / f"ledger/restores/{rest}.json"
    else:
        p = repo_path / f"ledger/other/{key.replace('/', '_')}.json"
    return p if p.is_file() else None


def read_journal(repo_path: Path) -> List[dict]:
    jp = Path(repo_path) / "ledger/journal.jsonl"
    if not jp.is_file():
        return []
    return [json.loads(l) for l in jp.read_text(encoding="utf-8").splitlines() if l.strip()]


def verify_mirror(repo_path: str | Path) -> MirrorReport:
    """H.4 step 1: every record file re-hashes to its journal entry, the
    journal is contiguous, and every blob a record points to is present
    and hashes right. Nothing is loaded until this passes."""
    root = Path(repo_path)
    rep = MirrorReport()
    journal = read_journal(root)
    rep.txs = len(journal)
    expect = 1
    for line in journal:
        if line["tx"] != expect:
            rep.problems.append(f"journal gap: expected tx {expect}, found {line['tx']}")
        expect = line["tx"] + 1
        for key, csha in line["keys"].items():
            f = _record_file_for_key(root, key)
            if f is None:
                rep.problems.append(f"{key}: record file missing")
                continue
            data = f.read_bytes()
            if sha256_hex(data) != csha:
                rep.problems.append(f"{key}: record file does not hash to the journal's content_sha256")
                continue
            rep.records += 1
            rec = parse_record(json.loads(data))
            for sha in _blob_hashes(rec):
                bp = root / blob_relpath(sha)
                if not bp.is_file():
                    continue  # pointer-only records may reference blobs never pushed here
                if sha256_hex(bp.read_bytes()) != sha:
                    rep.problems.append(f"{blob_relpath(sha)}: blob does not hash to its name")
                else:
                    rep.blobs_checked += 1
    return rep


def _blob_hashes(rec: LedgerRecord) -> List[str]:
    d = rec.to_dict()
    out = []
    if d.get("blob_sha256"):
        out.append(d["blob_sha256"])
    return out


def replay(repo_path: str | Path, ledger: Ledger, require_verified: bool = True) -> int:
    """H.4 step 3 (content restore): one batch per journal line, in order,
    writing the mirrored canonical values; returns the number of txs
    replayed. Keys already present are skipped (idempotent). The new
    backend's tx ids differ from the originals; the original tx id is kept
    under `restore/txmap/<new_tx>` by the caller's restore record."""
    root = Path(repo_path)
    if require_verified:
        mr = verify_mirror(root)
        if not mr:
            raise LedgerError("mirror does not verify: " + "; ".join(mr.problems[:5]))
    n = 0
    for line in read_journal(root):
        batch: List[LedgerRecord] = []
        for key in line["keys"]:
            if ledger.exists(key):
                continue
            f = _record_file_for_key(root, key)
            if f is None:
                raise LedgerError(f"{key}: record file missing during replay")
            rec = parse_record(json.loads(f.read_bytes()))
            if rec.content_sha256() != line["keys"][key]:
                raise LedgerError(f"{key}: canonical form differs from the journal (schema drift?)")
            batch.append(rec)
        if batch:
            ledger._write_batch(batch)
            n += 1
    return n


def record_restore(ledger: Ledger, repo: EvidenceRepo, mode: str, source_last_state_tx: int,
                   tx_count: int, config: LedgerConfig) -> RestoreRecord:
    rec = RestoreRecord(mode=mode, source_repo=repo.slug(), source_commit=repo.head(),  # type: ignore[arg-type]
                        source_last_state_tx=source_last_state_tx, tx_count=tx_count,
                        appraiser_id=config.appraiser_id or load_appraiser_id(config.state_dir),
                        pybb_version=pybb_version())
    ledger.commit_restore(rec)
    return rec


def exact_restore_command(db: str, segments: List[Path], output: Path) -> List[str]:
    """H.4 step 2: the `immuadmin hot-restore` invocation for the concatenated
    backup segments (the operator runs it; it needs an immuadmin login)."""
    with open(output, "wb") as out:
        for seg in sorted(segments):
            out.write(Path(seg).read_bytes())
    return ["immuadmin", "hot-restore", db, "-i", str(output)]


# ── legacy bundles → bundle records (plan D / open point 4) ──────────────────


def bundle_record_from_file(bundle_path: str | Path, protocol: Any, config: LedgerConfig,
                            golden_ts: str = "") -> BundleRecord:
    """A `bundle` record for a provision bundle on disk. Legacy bundles (no
    `generate_nonce`) key by content hash with `assurance: signed`."""
    from .ledger_runs import ledger_protocol

    p = Path(bundle_path)
    data = p.read_bytes()
    payload, _ctx = json.loads(data)
    lp = ledger_protocol(protocol)
    desc = describe_package(payload, lp.session, nonce_targid="nonce_targ")
    appraiser_id = config.appraiser_id or load_appraiser_id(config.state_dir)
    targets = sum(len(t) for a, t in protocol.asp_args.items()
                  if a in {k for k, c in protocol.session.get("Session_Context", {}).get("ASP_Comps", {}).items()})
    return BundleRecord(
        nid=desc.nid, protocol_id=protocol.protocol_id, response_sha256=desc.response_sha256,
        blob_sha256=sha256_hex(data), blob_bytes=len(data), encoding="json",
        golden_ts=golden_ts, targets=targets, rawev_count=desc.rawev_count,
        rawev_sha256=desc.rawev_sha256,
        signature=desc.signature if desc.signature.present else SignatureInfo(present=False),
        nonce=desc.nonce, assurance=desc.assurance,
        freshness="post-hoc" if desc.nonce else "none",
        locators=[Locator(kind="local", path=str(p), appraiser_id=appraiser_id)],
        appraiser_id=appraiser_id, pybb_version=pybb_version())


def commit_bundles(ledger: Ledger, golden_root: str | Path, protocols: Dict[str, Any],
                   config: LedgerConfig) -> List[str]:
    """Backfill `bundle` records for every provision bundle under
    `<golden_root>/_bundles/<pid>/` whose protocol dir is known; returns the
    keys committed (existing ones are skipped)."""
    keys: List[str] = []
    for pid, protocol in protocols.items():
        bp = Path(golden_root) / "_bundles" / pid / "provision_bundle.json"
        if not bp.is_file():
            continue
        golden_ts = ""
        args = Path(golden_root) / "_bundles" / pid / "asp_args.json"
        if args.is_file():
            try:
                stamps = {a.get("golden_ts", "") for t in json.loads(args.read_text()).values() for a in t.values()}
                golden_ts = max(s for s in stamps if s) if any(stamps) else ""
            except Exception:
                golden_ts = ""
        rec = bundle_record_from_file(bp, protocol, config, golden_ts)
        key = key_for(rec)
        if ledger.exists(key):
            continue
        ledger.commit_bundle(rec)
        keys.append(key)
    return keys
