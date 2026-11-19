"""
Tooling identity for ledger runs (docs/ledger_plan.md, section B.8).

The binaries that produce a verdict — the CVM, the verified summarizer, the
ASP executables (which embed the verifying public key) and the public key
file — are measured only by Copland, never by pybb. The `attestation_tools`
protocol is a standard tools protocol (`tools.build_tools_protocol_dir`):
`hashfile` over each artifact, measure-in-place, then SIG. **Provisioning
it is the blessing**: the one measurement under the default cadence
`tooling.measure = at_provisioning`, repeated only when the stack is
rebuilt and re-provisioned. Every measurement and appraisal bundle then
carries `tooling: {kind: bundle, ref: <blessing bundle sha256>}` — "this
blessing was in force" — and nothing re-measures the tools at run time.

The opt-in cadences run the same protocol as an ordinary ledger run
(`every_episode`: once per predicate instance; `every_run`: before each
protocol run) and reference it as `{kind: run, ref: <its bundle id>}`.

This supersedes the 2026-07-30 scope note in `tools.py` that kept the
attestation stack out of the tool registry: measuring it is drift
detection and provenance, not a root of trust (plan B.8).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .ledger import Ledger, LedgerConfig, ToolingRef, sha256_hex
from .tools import build_tools_protocol_dir, register_tool

TOOLING_PROTOCOL_ID = "attestation_tools"
STACK_TOOL = "attestation_stack"


def attestation_stack_artifacts(cvm_binary: str, asp_bin: str, asp_names: List[str],
                                summarizer_bin: Optional[str], verify_key_path: str) -> List[str]:
    """Absolute paths of the stack's artifacts, existing ones only, stable order."""
    out: List[str] = []
    for p in [cvm_binary, summarizer_bin or "", verify_key_path]:
        p = os.path.expanduser(p)
        if p and Path(p).is_file():
            out.append(str(Path(p).resolve()))
    for name in sorted(set(asp_names)):
        p = Path(os.path.expanduser(asp_bin)) / name
        if p.is_file():
            out.append(str(p.resolve()))
    return out


def asp_names_in_use(protocols: Dict[str, Any]) -> List[str]:
    """Union of the configured protocols' manifest ASPs plus the ledger ASPs."""
    from .ledger_runs import LEDGER_ASPS

    names = set(LEDGER_ASPS)
    for p in protocols.values():
        names.update((p.manifest or {}).get("ASPS", []))
    return sorted(names)


def register_attestation_stack(cvm_config: Any, protocols: Dict[str, Any], config: LedgerConfig,
                               summarizer_bin: Optional[str] = None) -> List[str]:
    """Register the stack as a tool in `tools.py`'s registry; returns its artifacts."""
    if summarizer_bin is None:
        from . import summarizer

        summarizer_bin = summarizer.EVIDENCE_TOOLS_BIN
    artifacts = attestation_stack_artifacts(cvm_config.cvm_binary, cvm_config.asp_bin,
                                            asp_names_in_use(protocols), summarizer_bin,
                                            config.verify_key_path)
    register_tool(STACK_TOOL, list(artifacts))
    return artifacts


def build_attestation_tools_protocol(proto_dir: str | Path, cvm_config: Any,
                                     protocols: Dict[str, Any], config: LedgerConfig,
                                     summarizer_bin: Optional[str] = None) -> Any:
    """Write the `attestation_tools` protocol directory and load it."""
    from .client import ProtocolDir

    artifacts = register_attestation_stack(cvm_config, protocols, config, summarizer_bin)
    if not artifacts:
        raise FileNotFoundError("no attestation-stack artifacts found (CVM binary, ASPs, key)")
    build_tools_protocol_dir(
        proto_dir, "attestation", [STACK_TOOL],
        "identity of the attestation stack: CVM, verified summarizer, ASP executables, verifying key "
        "(docs/ledger_plan.md B.8); provisioning this protocol is the blessing")
    return ProtocolDir.load(str(proto_dir), protocol_id=TOOLING_PROTOCOL_ID)


class Blessing(BaseModel):
    protocol_id: str
    bundle_path: str
    bundle_sha256: str
    provisioned: List[str] = []
    ledger_key: Optional[str] = None
    error: str = ""

    def ref(self) -> Optional[ToolingRef]:
        return None if self.error else ToolingRef(kind="bundle", ref=self.bundle_sha256)


def bless_tools(client: Any, protocol: Any, golden_root: str | Path, ledger: Optional[Ledger],
                config: LedgerConfig, force: bool = False) -> Blessing:
    """
    The blessing (B.8): provision `attestation_tools` — the CVM hashes the
    live binaries and signs — store the bundle under `<golden_root>/_bundles/`,
    and record it in the ledger as a `provision` bundle keyed by the bundle's
    nonce id. Idempotent: unchanged tools re-provision to the same goldens
    and the stored bundle is left as it is (no new record); `force`
    re-blesses with a fresh nonce.
    """
    from .ledger_repo import record_provision_bundles
    from .provision import make_provision_predicate, provision_request

    pid = protocol.protocol_id
    outcome = make_provision_predicate(client, {pid: protocol}, Path(golden_root))(
        provision_request(pid, force_timestamp=force))
    if outcome.error:
        return Blessing(protocol_id=pid, bundle_path="", bundle_sha256="", error=outcome.error)
    bundle_path = Path(outcome.bundle_path)
    sha = sha256_hex(bundle_path.read_bytes())
    b = Blessing(protocol_id=pid, bundle_path=str(bundle_path), bundle_sha256=sha,
                 provisioned=list(outcome.provisioned))
    if ledger is not None:
        keys = record_provision_bundles(ledger, golden_root, {pid: protocol}, config)
        b.ledger_key = keys[0] if keys else _bundle_key_for(ledger, pid, sha)
    return b


def _bundle_key_for(ledger: Ledger, pid: str, sha: str) -> Optional[str]:
    for rec in ledger.records(kind="bundle", protocol_id=pid, role="provision"):
        if getattr(getattr(rec, "blob", None), "blob_sha256", "") == sha:
            from .ledger import key_for

            return key_for(rec)
    return None


def tooling_ref_for(ledger: Ledger, config: LedgerConfig, protocols: Dict[str, Any],
                    golden_root: Optional[str | Path] = None) -> Optional[ToolingRef]:
    """
    The `tooling` reference for a run under `at_provisioning`: the blessing
    bundle on disk for `config.tooling.protocol_id`, recorded in the ledger
    (recording it if the bundle is newer than the ledger knows). None when
    tooling tracking is off, the protocol is not configured, or no blessing
    exists yet — readiness reports the latter (plan B.7/B.8).
    """
    pid = config.tooling.protocol_id
    if not pid or pid not in protocols:
        return None
    root = Path(golden_root or config.golden_root)
    bundle = root / "_bundles" / pid / "provision_bundle.json"
    if not bundle.is_file():
        return None
    sha = sha256_hex(bundle.read_bytes())
    if _bundle_key_for(ledger, pid, sha) is None:
        from .ledger_repo import record_provision_bundles

        record_provision_bundles(ledger, root, {pid: protocols[pid]}, config)
    return ToolingRef(kind="bundle", ref=sha)


class ToolingResolver:
    """Per-predicate tooling policy (B.8): returns the ToolingRef each run
    should carry, running the tooling protocol when the cadence asks."""

    def __init__(self, client: Any, protocols: Dict[str, Any], ledger: Ledger, config: LedgerConfig,
                 archive: Any = None):
        self.client, self.protocols, self.ledger, self.config, self.archive = \
            client, protocols, ledger, config, archive
        self._episode_ref: Optional[ToolingRef] = None
        self._episode_done = False

    def _run_tooling(self) -> Optional[ToolingRef]:
        from .ledger_runs import attest

        pid = self.config.tooling.protocol_id
        if not pid or pid not in self.protocols:
            return None
        r = attest(self.client, self.protocols[pid], self.ledger, self.config,
                               archive=self.archive,
                               tooling=tooling_ref_for(self.ledger, self.config, self.protocols))
        return ToolingRef(kind="run", ref=r.bid) if r.bid and not r.error else None

    def ref(self, for_protocol: str) -> Optional[ToolingRef]:
        pid = self.config.tooling.protocol_id
        if not pid or for_protocol == pid:
            return tooling_ref_for(self.ledger, self.config, self.protocols) if pid else None
        measure = self.config.tooling.measure
        if measure == "at_provisioning":
            return tooling_ref_for(self.ledger, self.config, self.protocols)
        if measure == "every_run":
            return self._run_tooling()
        if not self._episode_done:  # every_episode
            self._episode_ref = self._run_tooling()
            self._episode_done = True
        return self._episode_ref
