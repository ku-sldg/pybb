"""
AutoVerus repair on an ATTESTED entry (the apk-merge integration):
repair repetition happens inside the knowledge source (AutoVerus's own
loop, driven here through the repair_fn seam — no AutoVerus install and
NO LLM calls in any of these tests), and the DEFINITIVE Verus run is the
fresh episode's CVM measurement, reached via the restart-episode
primitive.

Also pinned: the LLM safety latch (allow_llm defaults False and the rung
refuses the real bridge without it) and the key-hygiene invariant (the
config handed to AutoVerus carries no key material — the OpenAI key
crosses only via environment).

Attested arcs need the CVM stack and the local Verus distribution
(RUN_VERUS=1); the latch and key tests run everywhere.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.autoverus import AutoVerusConfig, AutoVerusRepairKS
from pybb.autoverus.bridge import _autoverus_config

REPO = Path(__file__).parent.parent
TARGET = REPO / "targets" / "find-max-verus" / "find_max.rs"
VERUS_WRAPPER = Path.home() / "Claude_workspace" / "bin" / "verus"
KEY = "find_max_verus:proof"

cvm_available = pytest.mark.skipif(
    not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
    reason="requires local CVM binary and asp-libs binaries")

needs_verus = pytest.mark.skipif(
    os.environ.get("RUN_VERUS") != "1" or not VERUS_WRAPPER.is_file(),
    reason="set RUN_VERUS=1 (and install the workspace verus wrapper) "
           "to run the attested Verus arcs")


def _example():
    sys.path.insert(0, str(REPO / "examples"))
    import find_max_verus
    return find_max_verus


def _rung(repair_fn, **kwargs):
    return AutoVerusRepairKS(target=str(TARGET), reattest=True,
                             repair_fn=repair_fn, **kwargs)


@pytest.fixture
def committed():
    original = TARGET.read_bytes()
    yield original.decode()
    TARGET.write_bytes(original)


# ── attested arcs (CVM + Verus) ───────────────────────────────────────────────

@cvm_available
@needs_verus
def test_clean_attested_episode(committed):
    ex = _example()
    ctl = ex.attest_episode(ex.load_protocol())
    assert ctl.blackboard.entries[KEY].good_standing
    assert not ctl.blackboard.escalate


@cvm_available
@needs_verus
def test_repair_then_definitive_attested_run(committed):
    """The flow the merge exists for: tamper -> the attested Verus run
    fails -> the rung 'repairs' (seam returns the reference solution;
    live AutoVerus iterates internally the same way) -> restart -> the
    DEFINITIVE attested Verus run judges the repaired file."""
    ex = _example()
    ex.tamper()
    ctl = ex.attest_episode(ex.load_protocol(),
                            repair_rung=_rung(lambda path, steps: committed))
    entry = ctl.blackboard.entries[KEY]
    assert entry.good_standing and not ctl.blackboard.escalate
    assert ctl.blackboard.restarts == {KEY: 1}
    verdicts = [e.result for k, e in ctl.blackboard.get_history()
                if k == KEY and e.result is not None
                and getattr(e.result, "protocol", "") == ex.PID]
    outcomes = [bool(v) for v in verdicts]
    assert not outcomes[0] and outcomes[-1], \
        "episode 1 refuted the tamper; the fresh episode judged the repair"
    assert TARGET.read_text() == committed  # the repair IS the reference


@cvm_available
@needs_verus
def test_cheated_repair_never_reaches_the_attested_verifier(committed):
    """A vacuous 'repair' (assume(false)) would PASS attested Verus —
    which is exactly why the rung's cheat gate refuses the restart:
    no re-attestation is spent, and the entry escalates."""
    ex = _example()
    ex.tamper()
    cheated = TARGET.read_text().replace(
        "    let mut max = nums[0];",
        "    proof { assume(false); }\n    let mut max = nums[0];")
    ctl = ex.attest_episode(ex.load_protocol(),
                            repair_rung=_rung(lambda path, steps: cheated))
    assert KEY in ctl.blackboard.escalate
    assert ctl.blackboard.restarts == {}  # no restart was ever spent


@cvm_available
@needs_verus
def test_unrepairable_fails_the_definitive_run_and_escalates(committed):
    """The seam returns the still-broken source: the restart is spent,
    the fresh attested run refutes it again, and the rung (one attempt,
    like live AutoVerus after its internal budget) escalates."""
    ex = _example()
    ex.tamper()
    still_broken = TARGET.read_text()
    ctl = ex.attest_episode(ex.load_protocol(),
                            repair_rung=_rung(lambda path, steps: still_broken))
    assert KEY in ctl.blackboard.escalate
    assert ctl.blackboard.restarts == {KEY: 1}
    assert not ctl.blackboard.escalate[KEY].result.passed


@cvm_available
@needs_verus
def test_llm_latch_refuses_the_real_bridge_by_default(committed):
    """No repair_fn and no allow_llm: the rung refuses to invoke the
    LLM-backed bridge (nothing is called, no key is read), and the entry
    escalates with the refusal on record."""
    ex = _example()
    ex.tamper()
    ctl = ex.attest_episode(ex.load_protocol(),
                            repair_rung=_rung(None))  # real bridge, unarmed
    assert KEY in ctl.blackboard.escalate
    assert ctl.blackboard.restarts == {}


# ── key hygiene (no gates — these must hold everywhere) ───────────────────────

def test_autoverus_config_carries_no_key_material(monkeypatch):
    """The config JSON handed to AutoVerus has an EMPTY key list even
    when a key is present in the environment: the key crosses the
    subprocess boundary via env only, never via files."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-SHOULD-NEVER-APPEAR")
    cfg = _autoverus_config(AutoVerusConfig(
        verus="/x/verus", autoverus="/x/verus-proof-synthesis"))
    assert cfg["aoai_api_key"] == []
    assert "sk-test-SHOULD-NEVER-APPEAR" not in json.dumps(cfg)


def test_llm_latch_defaults_off():
    assert AutoVerusRepairKS(target=str(TARGET)).allow_llm is False
