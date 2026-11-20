"""
Run context as Copland evidence (docs/ledger_plan.md, section O).

Two bundle roles record what a CVM run ran on and with, measured by the CVM
itself and signed, never hashed by pybb:

  stack   `attestation_stack`: `hashfile` over the CVM binary, the verified
          summarizer, the verifying public key, every executable in the
          ASP directory, and `stack:invocation` (the CvmConfig as pybb
          invokes the CVM). The installation. One lineage per writer.
  config  `attestation_config`, one bundle PER PROTOCOL (`protocol_id` names
          it): `hashfile` over that protocol's materialized inputs — the
          canonical term, session and manifest for every constructor pybb
          can run (`CONSTRUCTORS`). A run bundle's `term_sha256`,
          `session_sha256`, `manifest_sha256` are the hashes of exactly
          those bytes (ledger_runs.build_bundle_record, `request=`), so a
          reader joins runs to configurations by hash equality.

Both are `measure`-shaped runs (nonce + hashfile chain + SIG), committed
unconditionally when the OPERATOR asks (`examples/ledger_context.py`):
pybb has no cadence, performs no change detection and reads nothing from
the ledger at run time. The blessing (`blessing/<stack bid>`) is the
operator's approval of one stack bundle; its goldens are read off that
bundle's signed package so later stack audits take expectations from the
ledger alone (ledger_runs._appraise_context_bundle). Runs carry no pointer
to any of this: `derive_context` is what a reader does with writer identity
and transaction order (plan O.7).
"""

from __future__ import annotations

import base64
import copy
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
    Ledger,
    LedgerConfig,
    LedgerError,
    Location,
    StackInfo,
    canonical_json,
    describe_package,
    key_for,
    sha256_hex,
)
from .ledger_runs import (
    LEDGER_ASPS,
    _SIG,
    _assurance_exception,
    _measure_step,
    appraisal_term,
    audit_manifest,
    audit_session,
    blob_ref,
    build_bundle_record,
    combined_session,
    combined_term,
    fetch_bundle,
    ledger_protocol,
    measurement_term,
    record_env,
    remote_stores,
    shaped_protocol,
    HASHEVIDENCE_KEEP,
)
from .tools import _HASHFILE_TYPES, _hashfile_chain

# the term constructors a protocol's runs can use; `config` bundles measure
# the inputs of every one (plan O.2)
CONSTRUCTORS = ("measure", "appraise", "combined", "audit", "appraise_combined", "audit_combined")
INPUT_NAMES = ("term", "session", "manifest")
STACK_TARGETS = ("stack:cvm", "stack:summarizer", "stack:pubkey", "stack:invocation")  # plus stack:asp:<name>


def input_targ(constructor: str, name: str) -> str:
    return f"input:{constructor}:{name}"


# ── the inputs of a protocol, per constructor ────────────────────────────────


def constructor_inputs(protocol: Any, constructor: str) -> Tuple[dict, dict, dict]:
    """(term, session, manifest) exactly as the run path hands them to the
    CVM for `constructor` (ledger_runs: `measurement_request`,
    `appraisal_request`, `combined_request`, `_appraise_appraisal_bundle`)."""
    lp = ledger_protocol(protocol)
    if constructor == "measure":
        return measurement_term(lp), lp.session, lp.manifest
    if constructor == "appraise":
        return appraisal_term(), lp.session, lp.manifest
    if constructor == "combined":
        cp = shaped_protocol(protocol, "combined")
        return combined_term(cp), cp.session, cp.manifest
    if constructor == "appraise_combined":
        return appraisal_term(), combined_session(protocol.session), lp.manifest
    if constructor in ("audit", "audit_combined"):
        session = audit_session(protocol.session)
        if constructor == "audit_combined":
            session["Session_Context"]["ASP_Types"]["hashevidence"] = copy.deepcopy(HASHEVIDENCE_KEEP)
        return appraisal_term(), session, audit_manifest(protocol.manifest)
    raise LedgerError(f"unknown constructor '{constructor}'")


def input_hashes(protocol: Any) -> Dict[str, str]:
    """`input:<constructor>:<name>` -> sha256 of the canonical bytes, without
    writing anything (what a run's pins will be)."""
    out: Dict[str, str] = {}
    for c in CONSTRUCTORS:
        for name, obj in zip(INPUT_NAMES, constructor_inputs(protocol, c)):
            out[input_targ(c, name)] = sha256_hex(canonical_json(obj))
    return out


def context_root(config: LedgerConfig) -> Path:
    return Path(os.path.expanduser(config.state_dir)) / config.context.dir


def materialize_inputs(protocol: Any, config: LedgerConfig) -> Dict[str, Path]:
    """Write the protocol's inputs as canonical JSON under
    `<state_dir>/<context.dir>/<pid>/<constructor>/<name>.json` (the files
    `hashfile` measures; stable paths so the targets' args do not churn) and
    a content-addressed copy under `<context.dir>/blobs/<sha>.json` (the
    stated local location of the `config` bundle's file blobs). Returns
    target id -> measured path."""
    root = context_root(config)
    out: Dict[str, Path] = {}
    for c in CONSTRUCTORS:
        for name, obj in zip(INPUT_NAMES, constructor_inputs(protocol, c)):
            data = canonical_json(obj)
            path = root / protocol.protocol_id / c / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            blob = root / "blobs" / f"{sha256_hex(data)}.json"
            blob.parent.mkdir(parents=True, exist_ok=True)
            if not blob.exists():
                blob.write_bytes(data)
            out[input_targ(c, name)] = path
    return out


def hashfile_targets(files: Dict[str, Path], metadata: str) -> Dict[str, dict]:
    return {targ: {"filepath": str(path), "env_var": "", "measure_in_place": True,
                   "metadata": metadata, "asp_targid": targ}
            for targ, path in files.items()}


# ── the stack ────────────────────────────────────────────────────────────────


def stack_files(cvm_config: Any, config: LedgerConfig, summarizer_bin: Optional[str] = None,
                write_invocation: bool = True) -> Dict[str, Path]:
    """Target id -> path for the installation (plan O.1): the CVM binary, the
    summarizer, the verifying key, EVERY executable in `asp_bin` (the stack
    is independent of which protocols use which ASP), and
    `stack:invocation`, the CvmConfig written as canonical JSON. Missing
    files are skipped (the record says how many executables there were)."""
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
    if write_invocation:
        inv = context_root(config) / "stack" / "cvm_config.json"
        inv.parent.mkdir(parents=True, exist_ok=True)
        dump = cvm_config.model_dump(mode="json") if hasattr(cvm_config, "model_dump") else dict(vars(cvm_config))
        inv.write_bytes(canonical_json(dump))
        out["stack:invocation"] = inv
    return out


# ── the generated context protocol ───────────────────────────────────────────


def context_session(plc: str = "P0") -> dict:
    """The session every context run and audit lays out under: the tools
    protocol's hashfile/sig typing plus the ledger ASPs (nonce, binding)."""
    from .ledger_runs import ledger_session

    return ledger_session({
        "Session_Plc": plc, "Plc_Mapping": {}, "PubKey_Mapping": {},
        "Session_Context": {"ASP_Types": copy.deepcopy(_HASHFILE_TYPES),
                            "ASP_Comps": {"hashfile": "goldenbytes_appr", "sig": "sig_appr"}},
    })


def context_manifest() -> dict:
    return {"ASPS": sorted({"hashfile", "goldenbytes_appr", "sig", "sig_appr", *LEDGER_ASPS}),
            "ASP_FS_MAP": {}, "POLICY": []}


def context_protocol(target: Any, config: LedgerConfig, files: Optional[Dict[str, Path]] = None,
                     metadata: str = "") -> Any:
    """A ProtocolDir for a context run or audit. `target` is a role name
    (`stack` / `config`) with `files` for a measurement, or a stored
    stack/config BundleRecord for an audit (its `protocol_id` is kept, since
    a config bundle is filed under the protocol it describes)."""
    from .client import ProtocolDir

    if isinstance(target, BundleRecord):
        role, protocol_id = target.role, target.protocol_id
    else:
        role, protocol_id = str(target), (config.context.stack_protocol_id if str(target) == "stack"
                                          else config.context.config_protocol_id)
    targets = hashfile_targets(files or {}, metadata or f"{role}::context")
    chain = _hashfile_chain(targets) if targets else {"TERM_CONSTRUCTOR": "asp",
                                                      "TERM_BODY": {"ASP_CONSTRUCTOR": "NULL"}}
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [chain, _SIG]}
    plc = target.stack.plc if isinstance(target, BundleRecord) and target.stack else "P0"
    return ProtocolDir(protocol_id=protocol_id, path="", term=term, session=context_session(plc),
                       manifest=context_manifest(), asp_args={"hashfile": targets} if targets else {})


# ── operator commands: measure, bless ────────────────────────────────────────


class ContextMeasurement(BaseModel):
    role: str
    protocol_id: str = ""
    bid: str = ""
    ledger_ref: str = ""
    evidence_ref: str = ""
    targets: int = 0
    error: str = ""

    def __bool__(self) -> bool:
        return not self.error and bool(self.ledger_ref)


def _measure_context(client: Any, cp: Any, ledger: Ledger, config: LedgerConfig, role: str,
                     archive: Any, *, stack: Optional[StackInfo] = None,
                     config_info: Optional[ConfigInfo] = None, protocol_id: Optional[str] = None
                     ) -> ContextMeasurement:
    out = ContextMeasurement(role=role, protocol_id=protocol_id or cp.protocol_id,
                             targets=len(cp.asp_args.get("hashfile", {})))
    if archive is None:  # context evidence must keep its bytes: blessings and audits read them back
        from .ledger_runs import archiver

        archive = archiver(context_root(config) / "archive")
    lp = ledger_protocol(cp)
    payload, desc, out.evidence_ref, err, req = _measure_step(client, lp, out.protocol_id, archive)
    if err:
        out.error = err
        return out
    assert payload is not None and desc is not None and desc.bid is not None
    out.bid = desc.bid
    exception_reason, err = _assurance_exception(desc, config, out.protocol_id)
    if err:
        out.error = err
        return out
    try:
        rec = build_bundle_record(role, lp, payload, desc,
                                  blob_ref(out.evidence_ref, remote_stores=remote_stores(config)), config,
                                  protocol_id=out.protocol_id, exception_reason=exception_reason,
                                  shape="measure", request=req, stack=stack, config_info=config_info)
        ledger.commit_bundles([rec])
        out.ledger_ref = key_for(rec)
    except (LedgerError, OSError) as e:
        out.error = f"ledger commit failed: {e}"
    return out


def measure_stack(client: Any, ledger: Ledger, config: LedgerConfig, cvm_config: Any = None,
                  archive: Any = None, summarizer_bin: Optional[str] = None) -> ContextMeasurement:
    """Operator command (plan O.4): one `measure` run of `attestation_stack`
    over the installation, committed unconditionally as a `stack` bundle."""
    if cvm_config is None:
        cvm_config = getattr(client, "config", None)
    if cvm_config is None:
        from .client import CvmConfig

        cvm_config = CvmConfig()
    files = stack_files(cvm_config, config, summarizer_bin)
    if not files:
        return ContextMeasurement(role="stack", protocol_id=config.context.stack_protocol_id,
                                  error="no stack artifacts found (CVM binary, ASP directory, key)")
    cp = context_protocol("stack", config, files, "stack::installation")
    plc = cp.session.get("Session_Plc", "P0")
    executables = sum(1 for t in files if t.startswith("stack:asp:")) + sum(
        1 for t in ("stack:cvm", "stack:summarizer") if t in files)
    return _measure_context(client, cp, ledger, config, "stack", archive,
                            stack=StackInfo(plc=plc, executables=executables))


def measure_config(client: Any, protocol: Any, ledger: Ledger, config: LedgerConfig,
                   archive: Any = None) -> ContextMeasurement:
    """Operator command (plan O.4): materialize `protocol`'s inputs, run
    `attestation_config` over them, commit one `config` bundle filed under
    the protocol's id, with every file stated as a blob."""
    files = materialize_inputs(protocol, config)
    cp = context_protocol("config", config, files, f"config::{protocol.protocol_id}")
    stores = remote_stores(config)
    root = context_root(config)
    cfiles: List[ConfigFile] = []
    for targ, path in files.items():
        data = path.read_bytes()
        sha = sha256_hex(data)
        cfiles.append(ConfigFile(targ_id=targ, blob=blob_ref(str(root / "blobs" / f"{sha}.json"), data,
                                                              encoding="json", remote_stores=stores)))
    info = ConfigInfo(constructors=list(CONSTRUCTORS), files=cfiles)
    return _measure_context(client, cp, ledger, config, "config", archive, config_info=info,
                            protocol_id=protocol.protocol_id)


def stack_goldens(payload: list, session: dict) -> Dict[str, str]:
    """`hashfile` target id -> measured value (base64) read off a stack or
    config package: identification, no judgment."""
    desc = describe_package(payload, session)
    raw = payload[0]["RawEv"]
    return {sp.asp_targid: raw[sp.start] for sp in desc.spans
            if sp.asp == "hashfile" and sp.asp_targid and sp.count == 1}


def bless(ledger: Ledger, config: LedgerConfig, stack_bid: str, note: str = "") -> BlessingRecord:
    """Operator command (plan O.5): approve stack bundle `stack_bid`. Reads
    the goldens off its signed package (fetched by stated location, bytes
    verified) and writes `blessing/<stack_bid>`."""
    fetched = fetch_bundle(ledger, stack_bid, config)
    if fetched.record.role != "stack":
        raise LedgerError(f"{stack_bid} is a {fetched.record.role} bundle, not a stack bundle")
    cp = context_protocol(fetched.record, config)
    try:
        goldens = stack_goldens(fetched.payload, cp.session)
    except EvidenceLayoutError as e:
        raise LedgerError(f"stack package not describable: {e}") from e
    rec = BlessingRecord(stack_bid=stack_bid, targets=sorted(goldens), goldens=goldens, note=note,
                         **record_env(config))
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


def context_goldens(ledger: Ledger, target: BundleRecord, baseline: Optional[str]
                    ) -> Tuple[Dict[str, str], str, str]:
    """Expectations for an audit of `target` (plan O.6): (goldens, baseline
    key, error). Stack: the blessing named by `baseline` (a `blessing/<bid>`
    key or a stack bid), else the latest blessing. Config: the hashes of the
    files the bundle archived, as base64 of the raw digest (what `hashfile`
    outputs)."""
    if target.role == "config":
        if target.config is None:
            return {}, "", "config bundle carries no file list"
        return ({f.targ_id: base64.b64encode(bytes.fromhex(f.blob.blob_sha256)).decode()
                 for f in target.config.files if f.blob.blob_sha256}, "", "")
    if baseline:
        key = baseline if baseline.startswith("blessing/") else f"blessing/{baseline}"
        rec = ledger.get_record(key)
        if not isinstance(rec, BlessingRecord):
            return {}, "", f"no blessing at {key}"
    else:
        hit = latest_blessing(ledger)
        if hit is None:
            return {}, "", "no blessing in the ledger to audit the stack against (bless a stack bundle first)"
        key, rec = hit
    return dict(rec.goldens), key, ""


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
