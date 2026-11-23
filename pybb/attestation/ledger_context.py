"""
Run context as Copland evidence (docs/ledger_plan.md, sections O and P).

Two bundle roles record what a CVM run ran on and with, measured by the CVM
itself and signed, never hashed by pybb:

  stack   `attestation_stack`: `hashfile` over the CVM binary, the verified
          summarizer, the verifying public key and every executable in the
          ASP directory, under a `hashevidence` whose output H_bin — the
          CVM's sha256 over those digests in term order — is the stack's
          FINGERPRINT (plan P.1); beside it a settings lane hashes the run's
          own term, session, manifest and `cvm_config.json`. One lineage
          per writer.
  config  `attestation_config`, one bundle PER PROTOCOL (`protocol_id` names
          it): the same shape over that protocol's materialized inputs —
          the canonical term, session and manifest handed to the CVM for
          every constructor pybb can run (`CONSTRUCTORS`) — yielding H_cfg.
          A run bundle's `term_sha256`, `session_sha256`, `manifest_sha256`
          are the hashes of exactly those bytes, so a reader joins runs to
          configurations by hash equality.

Both are `measure`-shaped runs (nonce + chain + SIG), committed
unconditionally when the OPERATOR asks (`examples/ledger_context.py`):
pybb has no cadence, performs no change detection and reads nothing from
the ledger at run time. pybb never computes a fingerprint: it reads the
H slot off the signed package and copies it into the record, the blessing
(`blessing/<stack bid>`, the operator's approval of one stack bundle) and
the per-writer cache `<state_dir>/context/claim.json` (plan P.3). Runs
carry no pointer to any of this: `derive_context` is what a reader does
with writer identity and transaction order (plan O.7).

Canonicity (plan P.1): H depends on which file contents are measured and in
which order, and on nothing else. The CVM fixes the byte encoding; pybb
owns order (the chain is sorted by target id) and membership (every
executable regular file in asp_bin, plus the CVM, summarizer and key), both
pure functions, and the term that ran is itself measured into the package.
"""

from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel

from .ledger import (
    BlessingRecord,
    BundleRecord,
    ConfigFile,
    ConfigInfo,
    EvidenceLayoutError,
    GoldenProvenance,
    Ledger,
    LedgerConfig,
    LedgerError,
    StackInfo,
    canonical_json,
    describe_package,
    key_for,
    sha256_hex,
    slot_layout,
    utc_now,
)
from .ledger_runs import (  # noqa: F401  (hashfile_targets, context_root, load_cache re-exported)
    HASHEVIDENCE_KEEP,
    LEDGER_ASPS,
    _SIG,
    _asp,
    _assurance_exception,
    _blob_copy,
    _bseq,
    _cvm_config_dump,
    _lseq,
    _measure_step,
    appraisal_term,
    audit_manifest,
    audit_session,
    blob_ref,
    build_bundle_record,
    cache_path,
    combined_session,
    combined_term,
    context_root,
    fetch_bundle,
    hashfile_targets,
    lane_files,
    lane_term,
    ledger_protocol,
    ledger_session,
    load_cache,
    measurement_request,
    measurement_term,
    record_env,
    remote_stores,
    shaped_protocol,
)
from .tools import _HASHFILE_TYPES, _hashfile_chain

# the term constructors a protocol's runs can use; `config` bundles measure
# the inputs of every one (plan O.2); the names appear on no record (P.9.9)
CONSTRUCTORS = ("measure", "appraise", "combined", "audit", "appraise_combined", "audit_combined")
INPUT_NAMES = ("term", "session", "manifest")
# the settings lane of a context run: its own inputs and the CVM invocation
SETTINGS = (("term", "term.json"), ("session", "session.json"), ("manifest", "manifest.json"),
            ("invocation", "cvm_config.json"))


def input_targ(constructor: str, name: str) -> str:
    return f"input:{constructor}:{name}"


def settings_targ(role: str, name: str) -> str:
    return f"{role}:{name}"


# ── the inputs of a protocol, per constructor ────────────────────────────────


def constructor_inputs(protocol: Any, constructor: str, config: LedgerConfig) -> Tuple[dict, dict, dict]:
    """(term, session, manifest) exactly as the run path hands them to the
    CVM for `constructor` (ledger_runs: `measurement_request`,
    `appraisal_request`, `combined_request`, `_appraise_appraisal_bundle`),
    claim lane included (its file paths are stable per protocol and
    constructor, so the term is a function of the configuration)."""
    lp = ledger_protocol(protocol)
    lane = lane_term(lane_files(config, protocol.protocol_id, constructor))
    if constructor == "measure":
        return measurement_term(lp, lane), lp.session, lp.manifest
    if constructor == "appraise":
        return appraisal_term(lane), lp.session, lp.manifest
    if constructor == "combined":
        cp = shaped_protocol(protocol, "combined")
        return combined_term(cp, lane), cp.session, cp.manifest
    if constructor == "appraise_combined":
        return appraisal_term(lane), combined_session(protocol.session), lp.manifest
    if constructor in ("audit", "audit_combined"):
        session = audit_session(protocol.session)
        if constructor == "audit_combined":
            session["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
        return appraisal_term(lane), session, audit_manifest(protocol.manifest)
    raise LedgerError(f"unknown constructor '{constructor}'")


def input_hashes(protocol: Any, config: LedgerConfig) -> Dict[str, str]:
    """`input:<constructor>:<name>` -> sha256 of the canonical bytes, without
    writing anything (what a run's pins will be)."""
    out: Dict[str, str] = {}
    for c in CONSTRUCTORS:
        for name, obj in zip(INPUT_NAMES, constructor_inputs(protocol, c, config)):
            out[input_targ(c, name)] = sha256_hex(canonical_json(obj))
    return out


def materialize_inputs(protocol: Any, config: LedgerConfig) -> Dict[str, Path]:
    """Write the protocol's inputs as canonical JSON under
    `<state_dir>/<context.dir>/<pid>/<constructor>/<name>.json` (the files
    `hashfile` measures; stable paths so the targets' args do not churn) and
    a content-addressed copy under `<context.dir>/blobs/<sha>.json`.
    Returns target id -> measured path."""
    root = context_root(config)
    out: Dict[str, Path] = {}
    for c in CONSTRUCTORS:
        for name, obj in zip(INPUT_NAMES, constructor_inputs(protocol, c, config)):
            data = canonical_json(obj)
            path = root / protocol.protocol_id / c / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            _blob_copy(root, data)
            out[input_targ(c, name)] = path
    return out


# ── the stack ────────────────────────────────────────────────────────────────


def stack_files(cvm_config: Any, config: LedgerConfig, summarizer_bin: Optional[str] = None) -> Dict[str, Path]:
    """Target id -> path for the installation (plan O.1): the CVM binary, the
    summarizer, the verifying key and EVERY executable regular file in
    `asp_bin` (the stack is independent of which protocols use which ASP).
    Missing files are skipped. Sorted by target id: the order of the chain,
    hence of the digests H_bin covers (plan P.1). The CVM invocation is not
    here — it is a settings-lane target beside H_bin, so identical builds
    under different paths or settings share a fingerprint."""
    if summarizer_bin is None:
        from . import summarizer

        summarizer_bin = summarizer.EVIDENCE_TOOLS_BIN
    out: Dict[str, Path] = {}
    for targ, p in (("stack:cvm", cvm_config.cvm_binary), ("stack:summarizer", summarizer_bin or ""),
                    ("stack:pubkey", config.verify_key_path)):
        path = Path(os.path.expanduser(p)) if p else None
        if path is not None and path.is_file():
            out[targ] = path.resolve()
    asp_bin = Path(os.path.expanduser(cvm_config.asp_bin))
    if asp_bin.is_dir():
        for p in sorted(asp_bin.iterdir()):
            if p.is_file() and os.access(p, os.X_OK) and not p.name.startswith("."):
                out[f"stack:asp:{p.name}"] = p.resolve()
    return dict(sorted(out.items()))


# ── the generated context protocol ───────────────────────────────────────────


def context_session(plc: str = "P0") -> dict:
    """The session every context run and audit lays out under: the tools
    protocol's hashfile/sig typing plus the ledger ASPs, with `hashevidence`
    typed EXTEND so the digests survive beneath H (plan P.1). The EXTEND
    typing is applied AFTER `ledger_session`, which re-applies the ledger's
    REPLACE default — with REPLACE the CVM silently erases the digests."""
    s = ledger_session({
        "Session_Plc": plc, "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {"ASP_Types": copy.deepcopy(_HASHFILE_TYPES),
                            "ASP_Comps": {"hashfile": "goldenbytes_appr", "sig": "sig_appr"}},
    })
    s["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
    return s


def context_manifest() -> dict:
    return {"ASPS": sorted({"hashfile", "goldenbytes_appr", "sig", "sig_appr", *LEDGER_ASPS}),
            "ASP_FS_MAP": {}, "POLICY": []}


def fingerprint_term(measured: Dict[str, dict], settings: Dict[str, dict]) -> dict:
    """`lseq (bseq both_paths (lseq M hashevidence) M_settings) SIG` (plan P.1):
    the measured chain under the fingerprint, the settings chain beside it,
    the signature over both; `measurement_term` adds the nonce split."""
    m = _lseq(_hashfile_chain(measured), _asp("hashevidence", {}))
    body = _bseq("both_paths", m, _hashfile_chain(settings)) if settings else m
    return _lseq(body, _SIG)


def context_protocol(target: Any, config: LedgerConfig, files: Optional[Dict[str, Path]] = None,
                     settings: Optional[Dict[str, Path]] = None, metadata: str = "") -> Any:
    """A ProtocolDir for a context run or audit. `target` is a role name
    (`stack` / `config`) with the measured `files` and the settings-lane
    `settings` for a measurement, or a stored stack/config BundleRecord for
    an audit (its `protocol_id` is kept, since a config bundle is filed under
    the protocol it describes)."""
    from .client import ProtocolDir

    if isinstance(target, BundleRecord):
        role, protocol_id = target.role, target.protocol_id
    else:
        role, protocol_id = str(target), (config.context.stack_protocol_id if str(target) == "stack"
                                          else config.context.config_protocol_id)
    measured = hashfile_targets(files or {}, metadata or f"{role}::context")
    setts = hashfile_targets(settings or {}, f"{role}::settings")
    term = fingerprint_term(measured, setts) if measured else _lseq(
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "NULL"}}, _SIG)
    plc = target.stack.plc if isinstance(target, BundleRecord) and target.stack else "P0"
    args = {**measured, **setts}
    return ProtocolDir(protocol_id=protocol_id, path="", term=term, session=context_session(plc),
                       manifest=context_manifest(), asp_args={"hashfile": args} if args else {})


# ── reading a context package (slots, no hashing) ────────────────────────────


class ContextReading(BaseModel):
    """What pybb reads off a stack/config package: the fingerprint slot, the
    measured digests beneath it (target id -> base64, in term order) and the
    settings-lane digests. Identification only."""

    fingerprint: str
    digests: Dict[str, str]
    settings: Dict[str, str]

    def goldens(self) -> Dict[str, str]:
        return {**self.digests, **self.settings}


def read_context_package(payload: list, session: dict) -> ContextReading:
    desc = describe_package(payload, session)
    raw = payload[0]["RawEv"]
    spans = slot_layout(payload[1], session)
    hs = [s for s in spans if s.asp == "hashevidence" and not s.input]
    if len(hs) != 1 or hs[0].count != 1:
        raise EvidenceLayoutError(f"context package has {len(hs)} fingerprint events, expected 1")
    digests = {s.asp_targid: raw[s.start] for s in spans if s.input and s.asp == "hashfile" and s.asp_targid}
    settings = {s.asp_targid: raw[s.start] for s in spans if not s.input and s.asp == "hashfile" and s.asp_targid}
    if desc.bid is None:
        raise EvidenceLayoutError("context package carries no generate_nonce event")
    return ContextReading(fingerprint=raw[hs[0].start], digests=digests, settings=settings)


def stack_goldens(payload: list, session: dict) -> Dict[str, str]:
    """`hashfile` target id -> measured value (base64) read off a stack or
    config package, measured digests and settings alike."""
    return read_context_package(payload, session).goldens()


# ── the cache (plan P.3) ─────────────────────────────────────────────────────


def write_cache(config: LedgerConfig, *, stack: Optional[dict] = None,
                config_entry: Optional[Tuple[str, dict]] = None) -> dict:
    """Update `<context>/claim.json`, the writer's log of what its CVM last
    measured about itself: slot copies and ledger keys, nothing pybb hashed."""
    cache = load_cache(config)
    cache["writer"] = config.appraiser_id or record_env(config)["appraiser_id"]
    if stack is not None:
        cache["stack"] = stack
    if config_entry is not None:
        cache.setdefault("configs", {})[config_entry[0]] = config_entry[1]
    p = cache_path(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canonical_json(cache))
    return cache


# ── operator commands: measure, bless ────────────────────────────────────────


class ContextMeasurement(BaseModel):
    role: str
    protocol_id: str = ""
    bid: str = ""
    ledger_ref: str = ""
    evidence_ref: str = ""
    targets: int = 0  # hashfile targets measured (digests under H plus the settings lane)
    fingerprint: str = ""  # the H slot, base64
    error: str = ""

    def __bool__(self) -> bool:
        return not self.error and bool(self.ledger_ref)


def _measure_context(client: Any, role: str, files: Dict[str, Path], run_dir: Path, cvm_config: Any,
                     ledger: Ledger, config: LedgerConfig, archive: Any, *, metadata: str,
                     protocol_id: Optional[str] = None) -> Tuple[ContextMeasurement, Optional[ContextReading],
                                                                 Optional[Any], Optional[list], Optional[Any], dict]:
    """The common half of `measure_stack` / `measure_config`: settings lane,
    canonical term as a fixed point, the run, the reading. Returns the
    measurement (error set on failure) plus what the caller needs to build
    the record: reading, lp, payload, desc, request."""
    run_dir.mkdir(parents=True, exist_ok=True)
    settings = {settings_targ(role, name): run_dir / fname for name, fname in SETTINGS}
    cp = context_protocol(role, config, files, settings, metadata)
    pid = protocol_id or cp.protocol_id
    out = ContextMeasurement(role=role, protocol_id=pid, targets=len(files) + len(settings))
    if archive is None:  # context evidence must keep its bytes: blessings and audits read them back
        from .ledger_runs import archiver

        archive = archiver(context_root(config) / "archive")
    # keep the EXTEND typing: ledger_protocol would re-apply the REPLACE default
    lp = ledger_protocol(cp).model_copy(update={"session": cp.session})
    req = measurement_request(lp)
    # the settings files hold exactly what the CVM is handed; the term file names itself (fixed point)
    (run_dir / "cvm_config.json").write_bytes(canonical_json(_cvm_config_dump(cvm_config)))
    (run_dir / "term.json").write_bytes(canonical_json(req["TERM"]))
    (run_dir / "session.json").write_bytes(canonical_json(req["ATTESTATION_SESSION"]))
    (run_dir / "manifest.json").write_bytes(canonical_json(lp.manifest))
    payload, desc, out.evidence_ref, err, req = _measure_step(client, lp, pid, archive, request=req)
    if err:
        out.error = err
        return out, None, None, None, None, req
    assert payload is not None and desc is not None and desc.bid is not None
    out.bid = desc.bid
    try:
        reading = read_context_package(payload, lp.session)
    except EvidenceLayoutError as e:
        out.error = f"context package not readable: {e}"
        return out, None, None, None, None, req
    out.fingerprint = reading.fingerprint
    _reason, err = _assurance_exception(desc, config, pid)
    if err:
        out.error = err
        return out, None, None, None, None, req
    return out, reading, lp, payload, desc, req


def _commit_context(out: ContextMeasurement, role: str, lp: Any, payload: list, desc: Any, req: dict,
                    ledger: Ledger, config: LedgerConfig, *, stack: Optional[StackInfo] = None,
                    config_info: Optional[ConfigInfo] = None) -> ContextMeasurement:
    try:
        rec = build_bundle_record(role, lp, payload, desc,
                                  blob_ref(out.evidence_ref, remote_stores=remote_stores(config)), config,
                                  protocol_id=out.protocol_id, shape="measure", request=req,
                                  stack=stack, config_info=config_info)
        ledger.commit_bundles([rec])
        out.ledger_ref = key_for(rec)
    except (LedgerError, OSError) as e:
        out.error = f"ledger commit failed: {e}"
    return out


def measure_stack(client: Any, ledger: Ledger, config: LedgerConfig, cvm_config: Any = None,
                  archive: Any = None, summarizer_bin: Optional[str] = None) -> ContextMeasurement:
    """Operator command (plan O.4 / P.1): one `measure` run of
    `attestation_stack` over the installation, committed unconditionally as a
    `stack` bundle whose `stack.fingerprint` is the package's H_bin slot."""
    if cvm_config is None:
        cvm_config = getattr(client, "config", None)
    if cvm_config is None:
        from .client import CvmConfig

        cvm_config = CvmConfig()
    files = stack_files(cvm_config, config, summarizer_bin)
    if not files:
        return ContextMeasurement(role="stack", protocol_id=config.context.stack_protocol_id,
                                  error="no stack artifacts found (CVM binary, ASP directory, key)")
    out, reading, lp, payload, desc, req = _measure_context(
        client, "stack", files, context_root(config) / "stack", cvm_config, ledger, config, archive,
        metadata="stack::installation")
    if out.error:
        return out
    executables = sum(1 for t in files if t.startswith("stack:asp:")) + sum(
        1 for t in ("stack:cvm", "stack:summarizer") if t in files)
    info = StackInfo(plc=lp.session.get("Session_Plc", "P0"), executables=executables,
                     fingerprint=reading.fingerprint, invocation=reading.settings.get("stack:invocation", ""))
    out = _commit_context(out, "stack", lp, payload, desc, req, ledger, config, stack=info)
    if out:
        write_cache(config, stack={"bid": out.bid, "fingerprint": reading.fingerprint,
                                   "invocation": info.invocation, "measured_at": utc_now()})
    return out


def measure_config(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                   archive: Any = None, cvm_config: Any = None) -> ContextMeasurement:
    """Operator command (plan O.4 / P.1): materialize `protocol`'s inputs, run
    `attestation_config` over them, commit one `config` bundle filed under
    the protocol's id, every input stated as a blob and `config.fingerprint`
    the package's H_cfg slot."""
    if cvm_config is None:
        cvm_config = getattr(client, "config", None)
    if cvm_config is None:
        from .client import CvmConfig

        cvm_config = CvmConfig()
    files = materialize_inputs(protocol, config)
    root = context_root(config)
    out, reading, lp, payload, desc, req = _measure_context(
        client, "config", files, root / protocol.protocol_id / "config", cvm_config, ledger, config, archive,
        metadata=f"config::{protocol.protocol_id}", protocol_id=protocol.protocol_id)
    if out.error:
        return out
    stores = remote_stores(config)
    cfiles: List[ConfigFile] = []
    for targ, path in files.items():
        data = path.read_bytes()
        cfiles.append(ConfigFile(targ_id=targ, blob=blob_ref(str(_blob_copy(root, data)), data,
                                                              encoding="json", remote_stores=stores)))
    info = ConfigInfo(constructors=list(CONSTRUCTORS), files=cfiles, fingerprint=reading.fingerprint,
                      settings=dict(reading.settings))
    out = _commit_context(out, "config", lp, payload, desc, req, ledger, config, config_info=info)
    if out:
        write_cache(config, config_entry=(protocol.protocol_id, {
            "bid": out.bid, "fingerprint": reading.fingerprint, "measured_at": utc_now()}))
    return out


def bless(ledger: Ledger, config: LedgerConfig, stack_bid: str, note: str = "") -> BlessingRecord:
    """Operator command (plan O.5): approve stack bundle `stack_bid`. Reads
    the goldens and the fingerprint off its signed package (fetched by stated
    location, bytes verified) and writes `blessing/<stack_bid>`."""
    fetched = fetch_bundle(ledger, stack_bid, config)
    if fetched.record.role != "stack":
        raise LedgerError(f"{stack_bid} is a {fetched.record.role} bundle, not a stack bundle")
    cp = context_protocol(fetched.record, config)
    try:
        reading = read_context_package(fetched.payload, cp.session)
    except EvidenceLayoutError as e:
        raise LedgerError(f"stack package not readable: {e}") from e
    goldens = reading.goldens()
    rec = BlessingRecord(stack_bid=stack_bid, targets=sorted(goldens), goldens=goldens,
                         fingerprint=reading.fingerprint, note=note, **record_env(config))
    ledger.commit_blessing(rec)
    return rec


def blessings(ledger: Ledger) -> List[Tuple[int, str, BlessingRecord]]:
    """Every blessing with its tx, in ledger order."""
    out = []
    for tx, key, rec in ledger.history():
        if isinstance(rec, BlessingRecord):
            out.append((tx, key, rec))
    return out


def latest_blessing(ledger: Ledger, appraiser_id: Optional[str] = None) -> Optional[Tuple[str, BlessingRecord]]:
    hits = [(tx, k, r) for tx, k, r in blessings(ledger) if appraiser_id is None or r.appraiser_id == appraiser_id]
    return (hits[-1][1], hits[-1][2]) if hits else None


def context_goldens(ledger: Ledger, target: BundleRecord, against: Optional[str]
                    ) -> Tuple[Dict[str, str], Optional[str], List[GoldenProvenance], str]:
    """Expectations for an audit of `target` (plan O.6 / P.5 / P.11):
    (per-target goldens, fingerprint golden or None, golden_provenance,
    error). Stack: the blessing named by `against` (a `blessing/<bid>` key or
    a stack bid), else the latest blessing. Config: the hashes of the files
    the bundle archived, as base64 of the raw digest (what `hashfile`
    outputs), and its own recorded fingerprint."""
    if target.role == "config":
        if target.config is None:
            return {}, None, [], "config bundle carries no file list"
        goldens = {f.targ_id: base64.b64encode(bytes.fromhex(f.blob.blob_sha256)).decode()
                   for f in target.config.files if f.blob.blob_sha256}
        goldens.update(target.config.settings)  # the settings lane: slot copies on the record
        ref = f"bundle/{target.key_id}"
        prov = [GoldenProvenance(source="bundle", ref=ref, targets=["input:*", "config:*"])]
        fp = target.config.fingerprint or None
        if fp:
            prov.append(GoldenProvenance(source="bundle", ref=ref, asp="hashevidence"))
        return goldens, fp, prov, ""
    if against:
        key = against if against.startswith("blessing/") else f"blessing/{against}"
        rec = ledger.get_record(key)
        if not isinstance(rec, BlessingRecord):
            return {}, None, [], f"no blessing at {key}"
    else:
        hit = latest_blessing(ledger)
        if hit is None:
            return {}, None, [], "no blessing in the ledger to audit the stack against (bless a stack bundle first)"
        key, rec = hit
    prov = [GoldenProvenance(source="blessing", ref=key, targets=["stack:*"])]
    fp = rec.fingerprint or None
    if fp:
        prov.append(GoldenProvenance(source="blessing", ref=key, asp="hashevidence"))
    return dict(rec.goldens), fp, prov, ""


# ── refresh policy (plan P.4): operator-set, pybb carries it out ─────────────


def _age_seconds(stamp: str) -> Optional[float]:
    import datetime as dt

    try:
        t = dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None
    return (dt.datetime.now(dt.timezone.utc) - t).total_seconds()


def refresh_due(config: LedgerConfig, protocol_id: str, state: dict, demand: bool = False) -> Tuple[bool, bool]:
    """(re-measure the stack?, re-measure this protocol's config?) under
    `config.context.refresh`: `manual` never (operator commands only),
    `every_run` always, `every_episode` once per `state` (a dict the
    predicate owns), `max_age:<seconds>` when the cache entry is older or
    missing; `demand` (a run asking for fresh context) always both. pybb
    compares a clock to a timestamp at most; it never compares evidence."""
    if demand:
        return True, True
    policy = config.context.refresh
    if policy == "every_run":
        return True, True
    if policy == "every_episode":
        done = state.setdefault("episode_refreshed", set())
        stack = "stack" not in done
        cfg = protocol_id not in done
        done.update({"stack", protocol_id})
        return stack, cfg
    if policy.startswith("max_age:"):
        try:
            limit = float(policy.split(":", 1)[1])
        except ValueError:
            raise LedgerError(f"bad refresh policy '{policy}' (max_age:<seconds>)")
        cache = load_cache(config)
        s_age = _age_seconds((cache.get("stack") or {}).get("measured_at", ""))
        c_age = _age_seconds(((cache.get("configs") or {}).get(protocol_id) or {}).get("measured_at", ""))
        return (s_age is None or s_age > limit), (c_age is None or c_age > limit)
    if policy == "manual":
        return False, False
    raise LedgerError(f"unknown refresh policy '{policy}'")


def refresh_if_due(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig, state: dict,
                   demand: bool = False, archive: Any = None) -> str:
    """Carry out the refresh policy before a run of `protocol`: ordinary
    stack / config measurements (O.4 commits), nothing else. Returns the
    claim's `fresh` label: none | stack | config | both."""
    do_stack, do_cfg = refresh_due(config, protocol.protocol_id, state, demand)
    if do_stack:
        m = measure_stack(client, ledger, config, archive=archive)
        if not m:
            raise LedgerError(f"stack refresh failed: {m.error}")
    if do_cfg:
        m = measure_config(client, protocol, ledger, config, archive=archive)
        if not m:
            raise LedgerError(f"config refresh failed: {m.error}")
    return {(True, True): "both", (True, False): "stack", (False, True): "config"}.get((do_stack, do_cfg), "none")


# ── what a reader checks about a claim (plan P.5) ────────────────────────────


class ClaimVerification(BaseModel):
    """A reader's report on a run bundle's claim — consistency of the claim
    with the bundles it names. A report, not a verdict: the CVM's judgment
    is the audit that injects these bundles' values as goldens."""

    bid: str
    has_claim: bool = False
    stack_ok: Optional[bool] = None  # claimed stack exists, is a stack bundle by the same writer at a lower tx, same fingerprint
    config_ok: Optional[bool] = None  # likewise for the config bundle, for this protocol
    times_ok: Optional[bool] = None  # measured_at not after the run
    stack_is_latest: Optional[bool] = None  # the claimed stack was the writer's latest at the run's tx
    pins_match: Optional[bool] = None  # the run's pins appear among the config bundle's inputs
    constructor: str = ""
    blessing_key: str = ""
    problems: List[str] = []

    def __bool__(self) -> bool:
        return self.has_claim and not self.problems


def verify_claim(ledger: Ledger, bundle: BundleRecord) -> ClaimVerification:
    v = ClaimVerification(bid=bundle.key_id)
    c = bundle.claim
    if c is None or not (c.stack_bid or c.config_bid):  # a lane without a claim: nothing to verify
        return v
    v.has_claim = True
    my_tx = ledger.tx_of(key_for(bundle))

    def check_bundle(bid: str, role: str, fp: str, label: str) -> Optional[BundleRecord]:
        if not bid:
            v.problems.append(f"claim names no {label} bundle")
            return None
        rec = ledger.get_record(f"bundle/{bid}")
        if not isinstance(rec, BundleRecord) or rec.role != role:
            v.problems.append(f"claimed {label} {bid[:16]}… is not a {role} bundle in the ledger")
            return None
        if rec.appraiser_id != bundle.appraiser_id:
            v.problems.append(f"claimed {label} was written by {rec.appraiser_id}, the run by {bundle.appraiser_id}")
        their_tx = ledger.tx_of(f"bundle/{bid}")
        if my_tx is not None and their_tx is not None and their_tx >= my_tx:
            v.problems.append(f"claimed {label} was recorded at tx {their_tx}, not before the run (tx {my_tx})")
        recorded = (rec.stack.fingerprint if role == "stack" and rec.stack else
                    rec.config.fingerprint if role == "config" and rec.config else "")
        if fp != recorded:
            v.problems.append(f"claimed {label} fingerprint differs from the bundle's recorded slot")
        return rec

    s = check_bundle(c.stack_bid, "stack", c.stack_fingerprint, "stack")
    v.stack_ok = s is not None and not any("stack" in p for p in v.problems)
    cfg = check_bundle(c.config_bid, "config", c.config_fingerprint, "config")
    if cfg is not None and cfg.protocol_id != bundle.protocol_id:
        v.problems.append(f"claimed config describes {cfg.protocol_id}, the run is {bundle.protocol_id}")
    v.config_ok = cfg is not None and not any("config" in p for p in v.problems)
    v.times_ok = all(t <= bundle.created_at for t in (c.stack_measured_at, c.config_measured_at) if t)
    if not v.times_ok:
        v.problems.append("a claimed measurement is timestamped after the run")
    if cfg is not None and cfg.config is not None:
        files = {f.targ_id: f.blob.blob_sha256 for f in cfg.config.files}
        mine = {"term": bundle.term_sha256, "session": bundle.session_sha256, "manifest": bundle.manifest_sha256}
        for k in CONSTRUCTORS:
            if all(files.get(input_targ(k, n)) == mine[n] for n in INPUT_NAMES):
                v.constructor, v.pins_match = k, True
                break
        else:
            v.pins_match = False
            v.problems.append("the run's inputs are not among the claimed config bundle's measured inputs")
    if s is not None:
        d = derive_context(ledger, bundle)
        v.stack_is_latest = (d.stack_bid == s.key_id)
        v.blessing_key = d.blessing_key if v.stack_is_latest else (
            f"blessing/{s.key_id}" if ledger.blessing_of(s.key_id) else "")
    return v


# ── what a reader derives (plan O.7) ─────────────────────────────────────────


class ContextDerivation(BaseModel):
    """The stack and configuration in force for one bundle, derived from the
    same writer's earlier records: no pointer is stored anywhere."""

    bid: str
    writer: str = ""
    tx: Optional[int] = None
    stack_bid: str = ""
    stack_tx: Optional[int] = None
    blessing_key: str = ""  # the latest blessing of that stack bundle, if any
    config_bid: str = ""
    config_tx: Optional[int] = None
    constructor: str = ""  # the constructor whose inputs the run's pins match
    pins: Dict[str, bool] = {}  # term / session / manifest against that constructor's files
    status: str = "none"  # measured | stale | none (no config bundle from this writer)
    stack_status: str = "none"  # blessed | unblessed | none

    def __bool__(self) -> bool:
        return self.status == "measured"


def derive_context(ledger: Ledger, bundle: BundleRecord) -> ContextDerivation:
    """For a run bundle R by writer W: W's latest `stack` bundle and latest
    `config` bundle for R's protocol at a lower tx, that stack's blessing,
    and R's three pins against the config bundle's recorded file hashes
    (the CVM-measured values are the same bytes' hashes; a `config` audit
    confirms it). Writer identity is `appraiser_id`."""
    me = key_for(bundle)
    my_tx = ledger.tx_of(me)
    d = ContextDerivation(bid=bundle.key_id, writer=bundle.appraiser_id, tx=my_tx)
    stack: Optional[Tuple[int, BundleRecord]] = None
    cfg: Optional[Tuple[int, BundleRecord]] = None
    bless_keys: Dict[str, str] = {}
    for tx, key, rec in ledger.history():
        if my_tx is not None and tx >= my_tx:
            break
        if getattr(rec, "appraiser_id", None) != bundle.appraiser_id:
            continue
        if isinstance(rec, BlessingRecord):
            bless_keys[rec.stack_bid] = key
        elif isinstance(rec, BundleRecord):
            if rec.role == "stack":
                stack = (tx, rec)
            elif rec.role == "config" and rec.protocol_id == bundle.protocol_id:
                cfg = (tx, rec)
    if stack is not None:
        d.stack_bid, d.stack_tx = stack[1].key_id, stack[0]
        d.blessing_key = bless_keys.get(stack[1].key_id, "")
        d.stack_status = "blessed" if d.blessing_key else "unblessed"
    if cfg is None:
        return d
    d.config_bid, d.config_tx = cfg[1].key_id, cfg[0]
    files = {f.targ_id: f.blob.blob_sha256 for f in (cfg[1].config.files if cfg[1].config else [])}
    mine = {"term": bundle.term_sha256, "session": bundle.session_sha256, "manifest": bundle.manifest_sha256}
    for c in CONSTRUCTORS:
        pins = {n: files.get(input_targ(c, n)) == mine[n] for n in INPUT_NAMES}
        if all(pins.values()):
            d.constructor, d.pins, d.status = c, pins, "measured"
            return d
    d.status = "stale"
    if bundle.shape in ("measure", "appraise", "combined"):
        c = bundle.shape
        d.pins = {n: files.get(input_targ(c, n)) == mine[n] for n in INPUT_NAMES}
    return d
