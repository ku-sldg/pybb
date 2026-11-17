import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def temp_control_aadl_slang_l1a_dir() -> Path:
    return FIXTURES / "temp_control_aadl_slang_l1a"


@pytest.fixture
def temp_control_aadl_slang_l1b_dir() -> Path:
    return FIXTURES / "temp_control_aadl_slang_l1b"


@pytest.fixture
def temp_control_aadl_slang_l2_dir() -> Path:
    return FIXTURES / "temp_control_aadl_slang_l2"



# ── ephemeral immudb for the `ledger` marker (docs/ledger_plan.md, decision 3) ──

import shutil
import socket
import subprocess
import time


@pytest.fixture(scope="session")
def immudb_server(tmp_path_factory):
    """Start a throwaway immudb (temp data dir, free port, web/metrics/pgsql
    off), bootstrap database `pybb` and a read/write user, yield the
    connection details, and stop it. Skips when `immudb` is not on PATH."""
    binary = shutil.which("immudb")
    if not binary:
        pytest.skip("immudb binary not on PATH")
    pytest.importorskip("immudb", reason="immudb-py not installed")
    from pybb.attestation.ledger import LedgerConfig
    from pybb.attestation.ledger_immudb import ImmudbLedger

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    root = tmp_path_factory.mktemp("immudb")
    proc = subprocess.Popen(
        [binary, "--dir", str(root / "data"), "--logdir", str(root / "log"),
         "--address", "127.0.0.1", "--port", str(port),
         "--web-server=false", "--metrics-server=false", "--pgsql-server=false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                if proc.poll() is not None:
                    pytest.skip("ephemeral immudb exited at startup")
                time.sleep(0.2)
        else:
            pytest.skip("ephemeral immudb did not open its port")
        info = {"host": "127.0.0.1", "port": port, "db": "pybb",
                "user": "pybb", "password": "Pybb-test-1!"}
        cfg = LedgerConfig(host=info["host"], port=port, db=info["db"],
                           user=info["user"], password=info["password"])
        for attempt in range(20):  # the gRPC server accepts logins shortly after the port opens
            try:
                ImmudbLedger.bootstrap(cfg)
                break
            except Exception:
                if attempt == 19:
                    raise
                time.sleep(0.25)
        yield info
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
