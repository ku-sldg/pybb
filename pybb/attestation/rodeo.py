"""
Rodeo transport: attestation via rust-rodeo-client (ku-sldg/rust-am-clients)
for HAMR attestation-report projects (e.g. INSPECTA-models isolette).

Workflow (two phases, provisioning out-of-band as always):

  provision (manual, once, from a known-good tree):
    rust-rodeo-client --cvm-filepath <cvm> \
      --hamr-report-filepath <root>/aadl_attestation_report.json \
      --manifest-filepath <manifest> --session-filepath <session> \
      --provisioned-evidence-filepath <root>/hamr_maestro_golden_evidence.json
    -> writes hamr_maestro_term.json + golden evidence next to the report

  appraise (what RodeoSubprocessClient runs):
    rust-rodeo-client --term-filepath <root>/hamr_maestro_term.json \
      --appraisal --output-dir <tmp>
    -> writes maestro_appsumm_response.json:
       {TYPE, ACTION: "APPSUMM", SUCCESS, APPRAISAL_RESULT,
        PAYLOAD: {asp_id: {targ_id: {meta, result}}}}

The appsumm response lands on the blackboard as evidence like any CVM
response; pybb.attestation.appraisal.parse_appraisal dispatches on ACTION.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel

from .client import (
    DEFAULT_ASP_BIN,
    DEFAULT_CVM_BINARY,
    DEFAULT_PATH_PREPEND,
    AttestationClient,
    CvmError,
)

DEFAULT_RUST_AM_CLIENTS = os.environ.get(
    "RUST_AM_CLIENTS",
    os.path.expanduser("~/Claude_workspace/rust-am-clients"),
)


class RodeoConfig(BaseModel):
    rodeo_binary: str = f"{DEFAULT_RUST_AM_CLIENTS}/target/release/rust-rodeo-client"
    cvm_binary: str = DEFAULT_CVM_BINARY
    asp_bin: str = DEFAULT_ASP_BIN
    manifest: str = f"{DEFAULT_RUST_AM_CLIENTS}/testing/manifests/Manifest_P0.json"
    session: str = f"{DEFAULT_RUST_AM_CLIENTS}/rodeo_configs/sessions/session_union.json"
    timeout_s: int = 1200
    path_prepend: List[str] = DEFAULT_PATH_PREPEND


class RodeoProtocol(BaseModel):
    """
    A provisioned HAMR attestation root: the directory holding the
    attestation report, the generated hamr_maestro_term.json, and the
    golden evidence.
    """

    protocol_id: str
    attestation_root: str
    term_filename: str = "hamr_maestro_term.json"

    @classmethod
    def load(cls, attestation_root: str, protocol_id: str | None = None) -> "RodeoProtocol":
        root = Path(attestation_root)
        proto = cls(
            protocol_id=protocol_id or root.parent.parent.parent.name,
            attestation_root=str(root),
        )
        term = root / proto.term_filename
        if not term.is_file():
            raise FileNotFoundError(
                f"{term} missing — provision this attestation root first "
                "(see pybb.attestation.rodeo module docstring)"
            )
        return proto

    @property
    def term_filepath(self) -> str:
        return str(Path(self.attestation_root) / self.term_filename)

    def target_records(self) -> List[dict]:
        return []


class RodeoSubprocessClient(AttestationClient):
    """Runs the rodeo appraisal phase and returns the appsumm response."""

    def __init__(self, config: RodeoConfig | None = None):
        self.config = config or RodeoConfig()

    def run_protocol(
        self, protocol: RodeoProtocol, path_map: Dict[str, str] | None = None
    ) -> dict:
        if path_map:
            raise ValueError(
                "RodeoSubprocessClient does not support path_map re-rooting: "
                "the provisioned term embeds absolute paths"
            )
        out_dir = tempfile.mkdtemp(prefix="pybb_rodeo_")
        cmd = [
            self.config.rodeo_binary,
            "--cvm-filepath", self.config.cvm_binary,
            "--term-filepath", protocol.term_filepath,
            "--manifest-filepath", self.config.manifest,
            "--session-filepath", self.config.session,
            "--libs-asp-bin", self.config.asp_bin,
            "--appraisal",
            "--output-dir", out_dir,
        ]
        env = dict(os.environ)
        env["ASP_BIN"] = self.config.asp_bin
        if self.config.path_prepend:
            env["PATH"] = ":".join(self.config.path_prepend + [env.get("PATH", "")])
        result = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=self.config.timeout_s,
            env=env,
        )
        appsumm_path = Path(out_dir) / "maestro_appsumm_response.json"
        if not appsumm_path.is_file():
            raise CvmError(
                f"rodeo produced no appraisal summary (exit {result.returncode}); "
                f"stderr: {result.stderr.strip()[-500:]}"
            )
        return json.loads(appsumm_path.read_text())
