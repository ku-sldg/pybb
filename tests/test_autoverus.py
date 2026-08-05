"""
AutoVerus repair rung on the core blackboard.

The KS and predicate are driven here through injected verify_fn/repair_fn
doubles, so these need neither WSL, a Verus build, nor an API key. Those
seams exist for testing only -- nothing ships a substitute, and the example
runs for real or refuses. The one live test is gated on RUN_AUTOVERUS=1 and
a working toolchain.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pybb import BlackboardController, KnowledgeSource
from pybb.autoverus import (
    AutoVerusConfig,
    AutoVerusError,
    AutoVerusRepairKS,
    find_cheat,
    make_verus_predicate,
    parse_verus_output,
    preflight,
    source_measurement,
)
# preflight resolves run_shell and VIA_WSL in this module, so that is what
# the tests below patch -- patching the package would silently no-op and
# send the preflight tests at real WSL.
from pybb.autoverus import config as av_config
from pybb.autoverus.shell import ShellError, to_wsl_path

FIXTURES = Path(__file__).parent / "fixtures" / "autoverus"
BROKEN = FIXTURES / "broken_proof.rs"

FAIL_OUT = "verification results:: 1 verified, 1 errors\n"
PASS_OUT = "verification results:: 2 verified, 0 errors\n"

REPAIRED = """use vstd::prelude::*;
fn main() {}
verus!{
pub fn f(n: u32) -> (r: u32) ensures r == n { n }
}
"""

# A config naming paths that do not exist here; what preflight sees is
# decided by the faked run_shell below, not by this machine.
CONFIG = AutoVerusConfig(verus="/home/u/verus/target-verus/release/verus",
                         autoverus="/home/u/verus-proof-synthesis")


def _fake_shell(*tokens):
    """A run_shell double reporting exactly which of the three paths exist."""
    def run_shell(script, timeout_s=None, extra_env=None):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=" ".join(tokens) + "\n", stderr="")
    return run_shell


@pytest.fixture
def target(tmp_path) -> Path:
    """A writable copy — the rung repairs in place."""
    dest = tmp_path / BROKEN.name
    shutil.copyfile(BROKEN, dest)
    return dest


def _controller(target: Path, verify_fn, repair_fn, max_attempts: int = 1):
    controller = BlackboardController()
    rung = AutoVerusRepairKS(repair_fn=repair_fn, max_attempts=max_attempts)
    controller.register_predicate("verus", make_verus_predicate(verify_fn))
    controller.add_ks(rung)
    controller.blackboard.write_entry(
        key="proof", predicate="verus", measurement=source_measurement(target))
    controller.route("proof", [rung])
    return controller


# --- convergence ----------------------------------------------------------


def test_repair_converges_in_one_run(target):
    """Broken -> repaired -> re-verified, inside a single controller.run()."""
    seen = []

    def verify_fn(path):
        seen.append(Path(path).read_text())
        # the repaired source is the one that verifies
        return PASS_OUT if "ensures r == n" in seen[-1] else FAIL_OUT

    controller = _controller(target, verify_fn, lambda p, n: REPAIRED)
    blackboard = controller.run()

    entry = blackboard.get_entry("proof")
    assert entry.good_standing
    assert entry.ks_history == {"repair:autoverus": 1}
    assert target.read_text() == REPAIRED
    assert len(seen) == 2  # verified once before repair, once after
    assert "proof" not in blackboard.get_escalate()


def test_content_hash_drives_reverification(target):
    """The re-verify happens because the measurement changed, not by luck."""
    before = source_measurement(target)
    controller = _controller(target, lambda p: FAIL_OUT, lambda p, n: REPAIRED)
    controller.run()
    after = source_measurement(target)
    assert before["sha256"] != after["sha256"]
    assert before["file"] == after["file"]


def test_already_verified_needs_no_repair(target):
    controller = _controller(target, lambda p: PASS_OUT, lambda p, n: REPAIRED)
    blackboard = controller.run()
    entry = blackboard.get_entry("proof")
    assert entry.good_standing
    assert entry.ks_history == {}  # the rung never ran
    assert target.read_text() == BROKEN.read_text()


# --- composition: more than one rung on the chain -------------------------

STILL_BROKEN = """use vstd::prelude::*;
fn main() {}
verus!{
pub fn g(n: u32) -> (r: u32) ensures r == n + 1 { n }
}
"""


class _RecordingKS(KnowledgeSource):
    """Trivial second rung: records the verdict it was handed."""

    name: str = "record:second-rung"
    partition: list[str] = []
    max_attempts: int = 1
    seen: list = []

    def execute(self, blackboard, keys) -> None:
        for key in keys:
            entry = blackboard.get_entry(key)
            self.seen.append(entry.result)


def test_second_rung_sees_the_file_as_it_is_now(target):
    """
    controller._advance restores the ORIGINAL measurement when one rung
    exhausts and hands off. A predicate that memoized on the measurement
    dict would then serve the second rung its pre-repair verdict, for a
    file the first rung has since rewritten -- a verdict describing a state
    that no longer exists on disk.

    The predicate must therefore key on the artifact as it is now, not on
    the measurement describing it.
    """
    def verify_fn(path):
        text = Path(path).read_text()
        # the first rung's output fails differently than the original
        return "verification results:: 0 verified, 2 errors" \
            if "fn g(" in text else FAIL_OUT  # 1 verified, 1 errors

    second = _RecordingKS()
    first = AutoVerusRepairKS(repair_fn=lambda p, n: STILL_BROKEN)
    controller = BlackboardController()
    controller.register_predicate("verus", make_verus_predicate(verify_fn))
    for rung in (first, second):
        controller.add_ks(rung)
    controller.blackboard.write_entry(
        key="proof", predicate="verus", measurement=source_measurement(target))
    controller.route("proof", [first, second])
    controller.run()

    assert "fn g(" in target.read_text(), "first rung should have rewritten it"
    assert second.seen, "second rung never ran"
    handed = second.seen[0]
    assert handed is not None
    assert (handed.verified, handed.errors) == (0, 2), (
        "second rung was handed a stale verdict: the measurement was restored "
        "to the original, but the file on disk is the first rung's output")


# --- escalation -----------------------------------------------------------


def test_unrepairable_escalates(target):
    """A repair that does not verify exhausts the chain and escalates."""
    controller = _controller(target, lambda p: FAIL_OUT, lambda p, n: REPAIRED)
    blackboard = controller.run()

    assert "proof" in blackboard.get_escalate()
    assert "proof" not in blackboard.get_all_entries()
    escalated = blackboard.get_escalate()["proof"]
    assert escalated.ks_history == {"repair:autoverus": 1}
    assert not escalated.good_standing


@pytest.mark.parametrize("boom", [
    AutoVerusError("wsl not found on PATH - WSL is required"),
    AutoVerusError("WSL command timed out after 1800s"),
    OSError("disk full"),
    RuntimeError("something entirely unexpected"),
])
def test_execute_never_raises(target, boom):
    """
    The controller does not wrap execute(), so any escape kills the run.
    Every bridge failure must become an escalation instead.
    """
    def repair_fn(path, steps):
        raise boom

    controller = _controller(target, lambda p: FAIL_OUT, repair_fn)
    blackboard = controller.run()  # must not raise

    assert "proof" in blackboard.get_escalate()
    assert target.read_text() == BROKEN.read_text()  # left untouched


def test_failing_result_is_falsy_but_present(target):
    """
    VerusResult truthiness IS the verdict, so a failing result is falsy
    while still being a real verdict. Anything reporting on an escalated
    entry must test `is None`, not truthiness, or it will claim there was
    no verdict exactly when there was one.
    """
    controller = _controller(target, lambda p: FAIL_OUT, lambda p, n: REPAIRED)
    blackboard = controller.run()
    result = blackboard.get_escalate()["proof"].result
    assert result is not None
    assert not result
    assert result.summary() == "1 verified, 1 error"


def test_verify_failure_is_a_verdict_not_a_crash(target):
    def verify_fn(path):
        raise AutoVerusError("verus produced no output (exit 127)")

    controller = _controller(target, verify_fn, lambda p, n: REPAIRED)
    blackboard = controller.run()
    assert "proof" in blackboard.get_escalate()
    assert "exit 127" in blackboard.get_escalate()["proof"].result.error


# --- verdict rules --------------------------------------------------------


def test_parse_verus_output():
    assert parse_verus_output(PASS_OUT) == (2, 0)
    assert parse_verus_output(FAIL_OUT) == (1, 1)
    assert parse_verus_output("verification results:: 12 verified, 3 errors") \
        == (12, 3)
    assert parse_verus_output("no results here") is None


def test_zero_verified_is_not_a_pass(tmp_path):
    """0 verified / 0 errors means nothing was checked, not that it passed."""
    rs = tmp_path / "empty.rs"
    rs.write_text("fn main() {}\n")
    predicate = make_verus_predicate(
        lambda p: "verification results:: 0 verified, 0 errors")
    assert not predicate(source_measurement(rs))


@pytest.mark.parametrize("cheat", ["assume(", "admit()"])
def test_cheated_proof_is_rejected_even_when_verus_passes(tmp_path, cheat):
    """
    A vacuous proof passes verification, so trusting Verus alone would call
    it repaired. AutoVerus applies the same rule scoring its own output.
    """
    rs = tmp_path / "cheat.rs"
    rs.write_text(f"verus!{{ fn f() {{ {cheat}false); }} }}\n")
    predicate = make_verus_predicate(lambda p: PASS_OUT)
    result = predicate(source_measurement(rs))
    assert not result
    assert "vacuous" in result.error


def test_find_cheat():
    assert find_cheat("let x = assume(true);") == "assume("
    assert find_cheat("admit()") == "admit()"
    assert find_cheat("let assumed = 1;") is None


def test_unreadable_file_is_a_failing_verdict(tmp_path):
    predicate = make_verus_predicate(lambda p: PASS_OUT)
    result = predicate({"file": str(tmp_path / "nope.rs"), "sha256": ""})
    assert not result
    assert "unreadable" in result.error


def test_predicate_memoizes_on_measurement(target):
    calls = []
    predicate = make_verus_predicate(lambda p: (calls.append(p), FAIL_OUT)[1])
    measurement = source_measurement(target)
    predicate(measurement)
    predicate(measurement)
    assert len(calls) == 1


# --- the shipped fixture --------------------------------------------------


def test_fixture_is_a_repair_task_not_a_generation_task():
    """
    --mode repair fixes a proof that exists and is wrong. If the fixture
    ever loses its invariant it becomes a generation task and the demo
    stops testing what it claims to.
    """
    source = BROKEN.read_text()
    assert "invariant" in source
    assert "ensures" in source
    assert find_cheat(source) is None


# --- the configured paths -------------------------------------------------


def test_code_dir_from_a_checkout_root():
    """The common case: the user types the checkout root."""
    assert CONFIG.code_dir() == "/home/u/verus-proof-synthesis/autoverus"
    assert CONFIG.root() == "/home/u/verus-proof-synthesis"
    assert CONFIG.main_py() == "/home/u/verus-proof-synthesis/autoverus/main.py"


@pytest.mark.parametrize("typed,code_dir", [
    ("/home/u/vps", "/home/u/vps/autoverus"),
    ("/home/u/vps/", "/home/u/vps/autoverus"),      # trailing slash
    ("/home/u/vps/autoverus", "/home/u/vps/autoverus"),  # the module dir
    ("/home/u/vps/code", "/home/u/vps/code"),       # pre-rename checkout
    ("/home/u/vps/autoverus/main.py", "/home/u/vps/autoverus"),
])
def test_code_dir_accepts_what_a_user_would_plausibly_type(typed, code_dir):
    """
    Upstream renamed code/ -> autoverus/, and "where AutoVerus is" is
    ambiguous between the checkout and the module directory. Resolving it
    here is what keeps the paths a pure function of what was typed --
    nothing probes the disk to decide.
    """
    config = AutoVerusConfig(autoverus=typed)
    assert config.code_dir() == code_dir
    assert config.root() == "/home/u/vps"
    assert config.python_bin() == "/home/u/vps/.venv/bin/python"


def test_explicit_python_wins_over_the_checkout_venv():
    config = CONFIG.model_copy(update={"python": "/usr/bin/python3"})
    assert config.python_bin() == "/usr/bin/python3"


def test_verus_dir_is_what_puts_verus_on_path():
    """
    AutoVerus resolves verus with shutil.which at import, so the repair
    script exports this onto PATH -- which is why no symlink into
    ~/.cargo/bin is needed.
    """
    assert CONFIG.verus_dir() == "/home/u/verus/target-verus/release"


# --- preflight ------------------------------------------------------------


def test_preflight_clean_when_everything_present(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/wsl")
    monkeypatch.setattr(av_config, "run_shell",
                        _fake_shell("verus", "main_py", "python"))
    assert preflight(CONFIG) == []


def test_preflight_reports_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/wsl")
    monkeypatch.setattr(av_config, "run_shell",
                        _fake_shell("verus", "main_py", "python"))
    assert any("OPENAI_API_KEY" in p for p in preflight(CONFIG))


def test_preflight_short_circuits_without_wsl(monkeypatch):
    """No WSL means nothing else is even checkable — don't guess."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(av_config, "VIA_WSL", True)
    monkeypatch.setattr(shutil, "which", lambda name: None)

    def explode(*a, **k):
        raise AssertionError("must not check paths when wsl is absent")

    monkeypatch.setattr(av_config, "run_shell", explode)
    assert any("wsl not found" in p for p in preflight(CONFIG))


def test_preflight_reports_every_missing_piece_at_once(monkeypatch):
    """Setting this up shouldn't be a game of whack-a-mole."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/wsl")
    monkeypatch.setattr(av_config, "run_shell", _fake_shell())  # nothing found
    problems = preflight(CONFIG)
    assert any("OPENAI_API_KEY" in p for p in problems)
    assert any("Verus binary" in p for p in problems)
    assert any("main.py" in p for p in problems)
    assert any("Python" in p and "venv" in p for p in problems)


def test_preflight_names_the_path_and_the_constant(monkeypatch):
    """
    A wrong path is the expected failure now that paths are typed in, so
    the message has to say which path was looked for and which constant
    changes it -- otherwise fixing setup means reading the source.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/wsl")
    monkeypatch.setattr(av_config, "run_shell", _fake_shell("python"))
    problems = " | ".join(preflight(CONFIG))
    assert CONFIG.verus in problems and "VERUS" in problems
    assert CONFIG.main_py() in problems and "AUTOVERUS" in problems


@pytest.mark.parametrize("typed", ["$HOME/verus-proof-synthesis",
                                   "~/verus-proof-synthesis"])
def test_preflight_rejects_an_unexpanded_home(monkeypatch, typed):
    """
    A $HOME path passes every shell check -- bash expands it -- and then
    fails ten minutes into a repair, because example_path and lemma_path
    are also written into AutoVerus's JSON config, where it stays a
    literal. Refuse it at preflight instead.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/wsl")
    monkeypatch.setattr(av_config, "run_shell",
                        _fake_shell("verus", "main_py", "python"))
    problems = preflight(AutoVerusConfig(autoverus=typed))
    assert any("absolute path" in p and "AUTOVERUS" in p for p in problems)


def test_preflight_reports_an_unusable_shell(monkeypatch):
    """A probe that could not run is a problem to report, not an exception."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/wsl")

    def explode(*a, **k):
        raise ShellError("command timed out after 60s")

    monkeypatch.setattr(av_config, "run_shell", explode)
    assert any("timed out" in p for p in preflight(CONFIG))


# --- WSL path translation -------------------------------------------------


@pytest.mark.parametrize("windows,wsl", [
    # the space is the case worth pinning: it must survive translation
    # untouched rather than being quoted or escaped
    (r"C:\Users\dev\My Documents\autoverus",
     "/mnt/c/Users/dev/My Documents/autoverus"),
    (r"D:\repo\file.rs", "/mnt/d/repo/file.rs"),
    (r"C:\a\b", "/mnt/c/a/b"),
])
def test_to_wsl_path_translates_drives(windows, wsl):
    assert to_wsl_path(windows) == wsl


def test_to_wsl_path_passes_posix_through():
    """No-op on Linux, and on a path that is already inside the distro."""
    assert to_wsl_path("/home/me/x.rs") == "/home/me/x.rs"
    assert to_wsl_path("/home/me/verus-proof-synthesis") == \
        "/home/me/verus-proof-synthesis"


# --- live -----------------------------------------------------------------

needs_autoverus = pytest.mark.skipif(
    os.environ.get("RUN_AUTOVERUS") != "1" or preflight() != [],
    reason="set RUN_AUTOVERUS=1, edit VERUS/AUTOVERUS at the top of "
           "pybb/autoverus/config.py and set OPENAI_API_KEY to run real repair")


@needs_autoverus
def test_live_repair_end_to_end(target):
    """Real AutoVerus, real Verus, real API calls. Minutes, and real spend."""
    controller = _controller(target, None, None)  # real bridge on both seams
    blackboard = controller.run()
    entry = blackboard.get_entry("proof")
    assert entry is not None and entry.good_standing, \
        f"live repair did not converge: {blackboard.get_escalate()}"
    assert find_cheat(target.read_text()) is None
