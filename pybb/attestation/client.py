"""
Attestation clients and protocol-directory loading.

A ProtocolDir is the on-disk unit of protocol configuration (the layout
produced by cvm-mcp under protocol_dirs/): term.json, session.json,
manifest.json, asp_args.json, and optionally a prebuilt cvm_request.json.

CvmSubprocessClient invokes the CVM binary the same way cvm-mcp's
cvm_client.run_cvm does: request and manifest via temp files, JSON response
on stdout.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .copland import empty_evidence, inject_asp_args, normalize_term, rewrite_filepaths

DEFAULT_CVM_BINARY = os.environ.get(
    "CVM_BINARY",
    os.path.expanduser("~/Claude_workspace/cvm/_build/default/theories/cvm"),
)
DEFAULT_ASP_BIN = os.environ.get(
    "ASP_BIN",
    os.path.expanduser("~/Claude_workspace/asp-libs/target/release"),
)


class CvmError(RuntimeError):
    """CVM invocation failed before producing a parseable response."""


class CvmConfig(BaseModel):
    cvm_binary: str = DEFAULT_CVM_BINARY
    asp_bin: str = DEFAULT_ASP_BIN
    log_level: str = "Info"
    timeout_s: int = 1200


class ProtocolDir(BaseModel):
    """A loaded protocol configuration directory."""

    protocol_id: str
    path: str
    term: dict
    session: dict
    manifest: dict
    asp_args: dict = {}
    prebuilt_request: Optional[dict] = None

    @classmethod
    def load(cls, path: str, protocol_id: str | None = None) -> "ProtocolDir":
        base = Path(path)

        def _read(name: str, required: bool = True):
            p = base / name
            if not p.is_file():
                if required:
                    raise FileNotFoundError(f"{p} missing from protocol dir")
                return None
            return json.loads(p.read_text())

        return cls(
            protocol_id=protocol_id or base.name,
            path=str(base),
            term=_read("term.json"),
            session=_read("session.json"),
            manifest=_read("manifest.json"),
            asp_args=_read("asp_args.json", required=False) or {},
            prebuilt_request=_read("cvm_request.json", required=False),
        )

    def build_request(self, path_map: Dict[str, str] | None = None) -> dict:
        """
        Assemble the ProtocolRunRequest dict for this protocol.

        Uses the prebuilt cvm_request.json when present, otherwise splices
        asp_args into the term and wraps it with the session. path_map
        re-roots every matching filepath (in term args and session alike),
        allowing runs against a copied target tree.
        """
        if self.prebuilt_request is not None:
            request = self.prebuilt_request
        else:
            term = normalize_term(inject_asp_args(self.term, self.asp_args))
            plc = self.session.get("Session_Plc", "P0")
            request = {
                "TYPE": "REQUEST",
                "ACTION": "RUN",
                "REQ_PLC": plc,
                "TO_PLC": plc,
                "TERM": term,
                "EVIDENCE": empty_evidence(),
                "ATTESTATION_SESSION": self.session,
            }
        if path_map:
            request = rewrite_filepaths(request, path_map)
        return request

    def target_records(self) -> List[dict]:
        """
        Flatten asp_args into [{asp_id, targ_id, args}, ...] so appraisal
        results (which carry only args after normalize_term) can be matched
        back to stable target ids.
        """
        records = []
        for asp_id, targets in self.asp_args.items():
            for targ_id, args in targets.items():
                records.append({"asp_id": asp_id, "targ_id": targ_id, "args": args})
        return records


class AttestationClient(ABC):
    """Transport-agnostic interface the knowledge sources depend on."""

    @abstractmethod
    def run_protocol(
        self, protocol: ProtocolDir, path_map: Dict[str, str] | None = None
    ) -> dict:
        """Execute the protocol and return the parsed ProtocolRunResponse dict."""


class CvmSubprocessClient(AttestationClient):
    """Runs protocols by invoking the CVM binary as a subprocess."""

    def __init__(self, config: CvmConfig | None = None):
        self.config = config or CvmConfig()

    def run_protocol(
        self, protocol: ProtocolDir, path_map: Dict[str, str] | None = None
    ) -> dict:
        request = protocol.build_request(path_map=path_map)
        return self._run_cvm(protocol.manifest, request)

    def _write_temp(self, data: Any, suffix: str) -> str:
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="pybb_cvm_")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        return path

    def _run_cvm(self, manifest: dict, request: dict) -> dict:
        manifest_path = self._write_temp(manifest, "_manifest.json")
        request_path = self._write_temp(request, "_request.json")
        try:
            cmd = [
                self.config.cvm_binary,
                "--manifest_file", manifest_path,
                "--req_file", request_path,
                "--asp_bin", self.config.asp_bin,
                "--log_level", self.config.log_level,
                "--cvm_binary", self.config.cvm_binary,
            ]
            result = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_s,
            )
            stdout = result.stdout.strip()
            if not stdout:
                raise CvmError(
                    f"CVM produced no output (exit {result.returncode}); "
                    f"stderr: {result.stderr.strip()}"
                )
            try:
                return json.loads(stdout)
            except json.JSONDecodeError as e:
                raise CvmError(f"CVM output was not valid JSON: {e}; raw: {stdout[:500]}")
        finally:
            os.unlink(manifest_path)
            os.unlink(request_path)
