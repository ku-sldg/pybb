"""
The evidence repository: durable blobs, ledger mirror, and restore
(docs/ledger_plan.md, section H, K decision 7; decisions 2 and 5).

A git repository — any repository the operator chooses, named by the path
of a local clone in `LedgerConfig.evidence_repo`; its store id
(`github:owner/name`) is read from the clone's `origin` remote — holds,
content-addressed and append-only by convention:

    blobs/<sha256>.json.gz              packages and component lists (provision bundles: .json)
    ledger/journal.jsonl                one line per ledger tx: {tx, ts, db, keys:{key: content_sha256}}
    ledger/bundles/<bid>.json           bundle records
    ledger/judged_by/<mid>/<abid>.json  pointer records
    ledger/mirror/<store>/<tx>.json     mirror records
    ledger/restores/<created_at>.json   restore records
    ledger/state/<tx>.json              the ledger backend's head at each push
    ledger/backups/                     immuadmin hot-backup segments (operator-produced, H.3)
    runs/<archive_dir>/manifest.json    push-time grouping: protocol -> bid -> blobs

Every bundle states at commit time where its bytes are and will be (`local`
plus the content-addressed path in each configured store), so no record is
ever appended to say "now it is there". `push_archive` copies what is stated
but not yet present into the clone, makes one commit per push (a consistent
snapshot), pushes, and writes ONE `mirror` record witnessing the push: the
store, commit, ledger state and journal range it covers, and a hash over the
blobs it carried. `reconcile` reports what is stated but not durable and
checks the live head against the mirrored states. `verify_mirror` /
`replay` are the restore path (H.4): a mirror is checked against its own
hashes before anything is loaded, then replayed tx by tx into a fresh
ledger. The exact restore of an immudb instance from backup segments is
`immuadmin hot-restore`, documented in `exact_restore_command`.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .ledger import (
    BundleRecord,
    Ledger,
    LedgerConfig,
    LedgerError,
    Location,
    MirrorRecord,
    ProvisionInfo,
    RestoreRecord,
    canonical_json,
    describe_package,
    key_for,
    load_appraiser_id,
    parse_record,
    pybb_version,
    sha256_hex,
    store_slug,
    utc_now,
)

# ── git plumbing ─────────────────────────────────────────────────────────────


class EvidenceRepo:
    """A local clone of the evidence repository (plan H.1)."""

    def __init__(self, path: str | Path, remote: str = "origin", slug: Optional[str] = None):
        self.path = Path(os.path.expanduser(str(path)))
        self.remote = remote
        self._slug = slug
        self._hosted: Optional[bool] = None
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
        repository's basename for a local or file remote."""
        if self._slug:
            return self._slug
        url = self.git("remote", "get-url", self.remote, check=False) or str(self.path)
        m = re.match(r"^(?:[a-z+]+://)?(?:[^@/]+@)?[^/:]+[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?/?$", url)
        if m and not url.startswith(("/", "file://", ".")):
            self._slug = f"{m.group('owner')}/{m.group('name')}"
            self._hosted = True
        else:
            name = url.rstrip("/").rsplit("/", 1)[-1]
            self._slug = name[:-4] if name.endswith(".git") else name
            self._hosted = False
        return self._slug

    def store_id(self) -> str:
        """The store id recorded in bundle locations and mirror records:
        `github:owner/name` for a hosted remote, `git:<name>` for a local one."""
        slug = self.slug()
        return f"github:{slug}" if self._hosted else f"git:{slug}"

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def blob_sha(self, relpath: str) -> str:
        return self.git("hash-object", str(self.path / relpath))

    def has_commit(self, commit: str) -> bool:
        return subprocess.run(["git", "-C", str(self.path), "cat-file", "-e", f"{commit}^{{commit}}"],
                              capture_output=True).returncode == 0

    def show(self, commit: str, relpath: str) -> bytes:
        return self.git_bytes("show", f"{commit}:{relpath}")

    def has_path(self, relpath: str, commit: str = "HEAD") -> bool:
        return subprocess.run(["git", "-C", str(self.path), "cat-file", "-e", f"{commit}:{relpath}"],
                              capture_output=True).returncode == 0

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


def blob_relpath(sha256: str, encoding: str = "gzip+json") -> str:
    return f"blobs/{sha256}.json.gz" if encoding.startswith("gzip") else f"blobs/{sha256}.json"


def record_relpath(key: str, rec: Any) -> str:
    kind = rec.kind
    if kind == "bundle":
        return f"ledger/bundles/{key.split('/', 1)[1].replace(':', '-')}.json"
    if kind == "judged_by":
        return f"ledger/judged_by/{rec.bid}/{rec.appraisal_bid}.json"
    if kind == "mirror":
        return f"ledger/mirror/{store_slug(rec.store)}/{rec.state_tx:012d}.json"
    if kind == "restore":
        return f"ledger/restores/{rec.created_at}.json"
    # v1 kinds (readable mirrors of a v1 database)
    if kind in ("nonce", "evidence", "verdict"):
        return f"ledger/records/{rec.nid}/{kind}.json"
    if kind in ("appraisal", "locator"):
        return f"ledger/records/{rec.nid}/{kind}-{rec.seq}.json"
    return f"ledger/other/{key.replace('/', '_')}.json"


def _record_file_for_key(repo_path: Path, key: str) -> Optional[Path]:
    kind, rest = key.split("/", 1)
    if kind == "bundle":
        p = repo_path / f"ledger/bundles/{rest.replace(':', '-')}.json"
    elif kind == "judged_by":
        p = repo_path / f"ledger/judged_by/{rest}.json"
    elif kind == "mirror":
        p = repo_path / f"ledger/mirror/{rest}.json"
    elif kind == "restore":
        p = repo_path / f"ledger/restores/{rest}.json"
    elif kind in ("nonce", "evidence", "verdict"):
        p = repo_path / f"ledger/records/{rest}/{kind}.json"
    elif kind in ("appraisal", "locator"):
        nid, seq = rest.split("/")
        p = repo_path / f"ledger/records/{nid}/{kind}-{seq}.json"
    else:
        p = repo_path / f"ledger/other/{key.replace('/', '_')}.json"
    return p if p.is_file() else None


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


# ── stated blobs: every blob a bundle says is (or will be) somewhere ──────────


class StatedBlob(BaseModel):
    """One blob as a bundle states it: its hash, which bundle, which part
    (`package` or `components`), its local path and its path in `store`."""

    bid: str
    protocol_id: str = ""
    part: str  # package | components
    blob_sha256: str
    encoding: str
    local_path: str = ""
    remote_path: str = ""
    key: str


def stated_blobs(ledger: Ledger, store: str) -> List[StatedBlob]:
    """Every blob whose bundle states a location in `store`, deduplicated by
    hash, with its local path when the bundle states one."""
    out: Dict[str, StatedBlob] = {}
    for _tx, key, rec in ledger.history():
        if not isinstance(rec, BundleRecord):
            continue
        parts = [("package", rec.blob)]
        if rec.verdict is not None and rec.verdict.components_blob is not None:
            parts.append(("components", rec.verdict.components_blob))
        for part, blob in parts:
            remote = next((l.path for l in blob.locations if l.store == store), None)
            if remote is None or not blob.blob_sha256:
                continue
            local = next((l.path for l in blob.locations if l.store == "local"), "")
            out.setdefault(blob.blob_sha256, StatedBlob(
                bid=rec.key_id, protocol_id=rec.protocol_id, part=part, blob_sha256=blob.blob_sha256,
                encoding=blob.encoding, local_path=local, remote_path=remote, key=key))
    return list(out.values())


def pending_blobs(ledger: Ledger, repo: EvidenceRepo, archive_dir: Optional[Path] = None) -> List[StatedBlob]:
    """Stated for this store but not at that path in the clone's HEAD."""
    out = [sb for sb in stated_blobs(ledger, repo.store_id()) if not repo.has_path(sb.remote_path)]
    if archive_dir is not None:
        root = Path(archive_dir).resolve()
        out = [sb for sb in out if sb.local_path and _under(Path(sb.local_path).resolve(), root)]
    return out


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


# ── push ─────────────────────────────────────────────────────────────────────


class PushReport(BaseModel):
    store: str = ""
    commit: str = ""
    committed: bool = False
    pushed: bool = False
    blobs: List[str] = []
    skipped: List[str] = []  # blobs whose local bytes are gone or mismatch
    journal_from_tx: int = 0
    journal_to_tx: int = 0
    state_tx: int = 0
    mirror_key: str = ""
    problems: List[str] = []


def push_archive(ledger: Ledger, repo: EvidenceRepo, config: LedgerConfig,
                 archive_dir: Optional[Path] = None, push: bool = True,
                 backup_segment: Optional[Path] = None) -> PushReport:
    """
    Plan H.2 / K.7: copy pending blobs and every ledger record into the
    clone, append journal lines for txs since the last push, write the state
    file, optionally add a hot-backup segment, commit once, push, then write
    ONE `mirror` record witnessing what this push carried.
    """
    rep = PushReport(store=repo.store_id())
    manifest: Dict[str, Dict[str, Dict[str, str]]] = {}
    skipped: List[Dict[str, str]] = []

    # 1. blobs
    pend = pending_blobs(ledger, repo, archive_dir)
    for sb in pend:
        src = Path(sb.local_path) if sb.local_path else None
        if src is None or not src.is_file():
            rep.skipped.append(sb.blob_sha256)
            skipped.append({"blob_sha256": sb.blob_sha256, "reason": "local bytes missing"})
            rep.problems.append(f"{sb.part} blob {sb.blob_sha256[:12]}… not at {src}")
            continue
        data = src.read_bytes()
        if sha256_hex(data) != sb.blob_sha256:
            rep.skipped.append(sb.blob_sha256)
            skipped.append({"blob_sha256": sb.blob_sha256, "reason": "local bytes mismatch"})
            rep.problems.append(f"{src}: bytes do not match the ledger's blob_sha256")
            continue
        dest = repo.path / sb.remote_path
        if not dest.exists():
            _write(dest, data)
        rep.blobs.append(sb.blob_sha256)
        manifest.setdefault(src.parent.name, {}).setdefault(sb.protocol_id, {})[f"{sb.part}:{sb.bid}"] = sb.remote_path

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

    # 8. the mirror record (K decision 7): one per push that carried anything
    if rep.committed:
        for sha in rep.blobs:  # verify by re-reading the committed bytes
            sb = next(s for s in pend if s.blob_sha256 == sha)
            if sha256_hex(repo.show(rep.commit, sb.remote_path)) != sha:
                rep.problems.append(f"{sb.remote_path}: committed bytes do not hash to the blob name")
        mirror = MirrorRecord(
            store=rep.store, repo=repo.slug(), commit=rep.commit, state_tx=rep.state_tx,
            state_hash=str(st.get("tx_hash_hex", "")), journal_from_tx=rep.journal_from_tx,
            journal_to_tx=rep.journal_to_tx, blobs=len(rep.blobs),
            blob_hashes_sha256=sha256_hex("".join(sorted(rep.blobs)).encode()), skipped=skipped,
            appraiser_id=config.appraiser_id or load_appraiser_id(config.state_dir),
            pybb_version=pybb_version())
        try:
            ledger.commit_mirror(mirror)
            rep.mirror_key = key_for(mirror)
        except LedgerError as e:
            rep.problems.append(f"mirror record not committed: {e}")
    return rep


# ── resolving remote locations ───────────────────────────────────────────────

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


def resolve_remote_location(loc: Location, config: Optional[LedgerConfig] = None) -> Optional[bytes]:
    """Bytes of a remote location: from the configured clone when it is that
    store (fetching first if the path is unknown), else — for a `github:`
    store — through `gh api` on the repository contents. None when neither
    is available."""
    repo = configured_repo(config)
    if repo is not None and repo.store_id() == loc.store:
        if not repo.has_path(loc.path):
            repo.fetch()
            branch = repo.git("rev-parse", "--abbrev-ref", "HEAD", check=False) or "main"
            ref = f"{repo.remote}/{branch}"
            if repo.has_path(loc.path, ref):
                try:
                    return repo.show(ref, loc.path)
                except LedgerError:
                    pass
        else:
            try:
                return repo.show("HEAD", loc.path)
            except LedgerError:
                pass
    if loc.store.startswith("github:") and shutil.which("gh"):
        slug = loc.store.split(":", 1)[1]
        r = subprocess.run(["gh", "api", f"repos/{slug}/contents/{loc.path}", "--jq", ".content"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return base64.b64decode(r.stdout.replace("\n", ""))
    return None


# ── reconcile ────────────────────────────────────────────────────────────────


class ReconcileReport(BaseModel):
    store: str = ""
    pending: List[StatedBlob] = []
    verified_remote: int = 0
    remote_mismatches: List[str] = []
    last_mirror: Optional[MirrorRecord] = None
    live_state: dict = {}
    mirrored_state: dict = {}
    state_ok: Optional[bool] = None
    problems: List[str] = []

    def __bool__(self) -> bool:
        return not self.pending and not self.remote_mismatches and self.state_ok is not False and not self.problems


def reconcile(ledger: Ledger, repo: EvidenceRepo, verify_all: bool = False) -> ReconcileReport:
    """Plan H.2 step 3: what is stated for this store but not durable, whether
    committed blobs still hash right, and whether the live head is consistent
    with the latest mirrored state (a rolled-back or rewritten server is
    caught here)."""
    store = repo.store_id()
    rep = ReconcileReport(store=store, pending=pending_blobs(ledger, repo))
    if verify_all:
        for sb in stated_blobs(ledger, store):
            if not repo.has_path(sb.remote_path):
                continue
            try:
                data = repo.show("HEAD", sb.remote_path)
            except LedgerError as e:
                rep.remote_mismatches.append(f"{sb.key}: {e}")
                continue
            if sha256_hex(data) != sb.blob_sha256:
                rep.remote_mismatches.append(f"{sb.key}: committed bytes do not hash to blob_sha256")
            else:
                rep.verified_remote += 1
    rep.last_mirror = ledger.latest_mirror(store)
    if rep.last_mirror is not None and not repo.has_commit(rep.last_mirror.commit):
        repo.fetch()
        if not repo.has_commit(rep.last_mirror.commit):
            rep.problems.append(f"mirror record names commit {rep.last_mirror.commit[:12]} which the clone does not have")
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


def read_journal(repo_path: Path) -> List[dict]:
    jp = Path(repo_path) / "ledger/journal.jsonl"
    if not jp.is_file():
        return []
    return [json.loads(l) for l in jp.read_text(encoding="utf-8").splitlines() if l.strip()]


def verify_mirror(repo_path: str | Path) -> MirrorReport:
    """H.4 step 1: every record file re-hashes to its journal entry, the
    journal is in order, and every blob a record points to is present
    and hashes right. Nothing is loaded until this passes."""
    root = Path(repo_path)
    rep = MirrorReport()
    journal = read_journal(root)
    rep.txs = len(journal)
    # tx ids must strictly increase; they need not be contiguous, because an
    # immudb ledger interleaves SQL transactions (mirror rows, DDL) that carry
    # no records and therefore no journal line
    last_tx = 0
    for line in journal:
        if line["tx"] <= last_tx:
            rep.problems.append(f"journal order: tx {line['tx']} after tx {last_tx}")
        last_tx = line["tx"]
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
            for sha, enc in _blob_hashes(rec):
                bp = root / blob_relpath(sha, enc)
                if not bp.is_file():
                    continue  # pointer-only records may reference blobs never pushed here
                if sha256_hex(bp.read_bytes()) != sha:
                    rep.problems.append(f"{bp.relative_to(root)}: blob does not hash to its name")
                else:
                    rep.blobs_checked += 1
    return rep


def _blob_hashes(rec: Any) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    if isinstance(rec, BundleRecord):
        if rec.blob.blob_sha256:
            out.append((rec.blob.blob_sha256, rec.blob.encoding))
        if rec.verdict is not None and rec.verdict.components_blob is not None and rec.verdict.components_blob.blob_sha256:
            cb = rec.verdict.components_blob
            out.append((cb.blob_sha256, cb.encoding))
        return out
    d = rec.to_dict()
    if d.get("blob_sha256"):
        out.append((d["blob_sha256"], d.get("encoding", "gzip+json")))
    return out


def replay(repo_path: str | Path, ledger: Ledger, require_verified: bool = True) -> int:
    """H.4 step 3 (content restore): one batch per journal line, in order,
    writing the mirrored canonical values; returns the number of txs
    replayed. Keys already present are skipped (idempotent). The new
    backend's tx ids differ from the originals; the restore record names
    the last mirrored tx."""
    root = Path(repo_path)
    if require_verified:
        mr = verify_mirror(root)
        if not mr:
            raise LedgerError("mirror does not verify: " + "; ".join(mr.problems[:5]))
    n = 0
    for line in read_journal(root):
        batch: List[Any] = []
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


# ── provision bundles → `provision` bundle records (plan D / K.3) ────────────


def provision_bundle_record(bundle_path: str | Path, protocol: Any, config: LedgerConfig,
                            golden_ts: str = "") -> BundleRecord:
    """A `provision` bundle record for a provision bundle on disk (a signed
    golden baseline). Legacy bundles (no `generate_nonce`) key by content
    hash with `assurance: signed`."""
    from .ledger_runs import blob_ref, build_bundle_record, ledger_protocol, remote_stores

    p = Path(bundle_path)
    data = p.read_bytes()
    payload, _ctx = json.loads(data)
    lp = ledger_protocol(protocol)
    desc = describe_package(payload, lp.session, nonce_targid="nonce_targ")
    comps = protocol.session.get("Session_Context", {}).get("ASP_Comps", {})
    targets = sum(len(t) for a, t in protocol.asp_args.items() if a in comps)
    blob = blob_ref(str(p), data, encoding="json", remote_stores=remote_stores(config))
    return build_bundle_record("provision", lp, payload, desc, blob, config,
                               provision=ProvisionInfo(golden_ts=golden_ts, targets=targets),
                               shape="measure" if desc.nonce else None)


def record_provision_bundles(ledger: Ledger, golden_root: str | Path, protocols: Dict[str, Any],
                             config: LedgerConfig) -> List[str]:
    """Record every provision bundle under `<golden_root>/_bundles/<pid>/`
    whose protocol dir is known; returns the keys committed (existing ones
    are skipped)."""
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
        rec = provision_bundle_record(bp, protocol, config, golden_ts)
        key = key_for(rec)
        if ledger.exists(key):
            continue
        ledger.commit_bundles([rec])
        keys.append(key)
    return keys
