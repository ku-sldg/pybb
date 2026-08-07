"""
LLM backend + armed-LlmEngine units — NO network calls anywhere.

Pinned: factories refuse cleanly without credentials (before any network
activity); the enriched prompt carries the context sources and the
only-the-proof instruction and NO key material; markdown fences are
stripped; the resume-feedback loop feeds a failed candidate back into
the next round's prompt; the driver rejects LLM flags without the
explicit opt-in chain.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from pybb.attestation.llm_backends import (
    BACKENDS,
    LlmBackendError,
    make_openai_complete,
)
from pybb.attestation.synthesis import GoalContext, LlmEngine

REPO = Path(__file__).parent.parent


def test_backend_registry_names():
    assert set(BACKENDS) == {"anthropic", "openai"}


def test_openai_factory_refuses_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LlmBackendError, match="OPENAI_API_KEY"):
        make_openai_complete()


def test_openai_describe_carries_no_key_material(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-SHOULD-NEVER-APPEAR")
    complete = make_openai_complete()
    assert "sk-test-SHOULD-NEVER-APPEAR" not in complete.describe
    assert "openai" in complete.describe


def _ctx(**overrides):
    base = dict(
        name="fanHold_in_band",
        statement="theorem fanHold_in_band : fanHold_in_band_prop computeFanCmd",
        prop="fanHold_in_band_prop",
        blessed_statement="def fanHold_in_band_prop (f : Step) : Prop := ...",
        detail="unsolved goals",
        seed="by\n  sorry",
        context_files={"TempControl/Impl.lean": "def computeFanCmd ...",
                       "TempControl/Props.lean": "def fanHold_in_band_prop ..."},
    )
    base.update(overrides)
    return GoalContext(**base)


def test_enriched_prompt_contents(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-SHOULD-NEVER-APPEAR")
    engine = LlmEngine(complete=lambda p: "")
    prompt = engine.prompt(_ctx())
    assert "TempControl/Impl.lean" in prompt
    assert "def computeFanCmd" in prompt        # the proving subject
    assert "ONLY the proof term" in prompt      # response contract
    assert "core Lean only" in prompt
    assert "unsolved goals" in prompt
    assert "sk-test-SHOULD-NEVER-APPEAR" not in prompt  # keys never enter


def test_fence_stripping():
    assert LlmEngine._strip_fences("```lean\nby\n  omega\n```") == "by\n  omega"
    assert LlmEngine._strip_fences("```\nby simp\n```") == "by simp"
    assert LlmEngine._strip_fences("  by omega  ") == "by omega"


def test_resume_feedback_carries_failed_candidate():
    """The KS resumes the iterator only when a candidate failed — round 2's
    prompt must carry round 1's rejected candidate."""
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return f"by\n  attempt_{len(prompts)}"

    engine = LlmEngine(complete=complete, attempts=3)
    it = engine(_ctx())
    first = next(it)
    assert first == "by\n  attempt_1"
    second = next(it)  # resumed => first was rejected
    assert second == "by\n  attempt_2"
    assert "Rejected attempt 1" in prompts[1]
    assert "attempt_1" in prompts[1]
    assert "Rejected attempt" not in prompts[0]


def test_unarmed_engine_still_yields_nothing():
    assert list(LlmEngine()(_ctx())) == []


# ── live arcs (RUN_LLM=1 + per-backend credentials + CVM stack) ───────────────
# Real API spend (a few thousand tokens). LLM success is nondeterministic:
# escalation is a valid outcome — the assertions cover the MECHANICS (the
# LLM was invoked, seeds restored, and a pass implies a fresh re-attestation).

needs_llm = pytest.mark.skipif(
    __import__("os").environ.get("RUN_LLM") != "1",
    reason="set RUN_LLM=1 (with credentials in the environment) to run "
           "live LLM synthesis arcs — real API spend")


@needs_llm
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_live_llm_repairs_broken_proof(provider):
    try:
        backend = BACKENDS[provider]()
    except LlmBackendError as e:
        pytest.skip(f"{provider}: {e}")
    from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
    if not (Path(DEFAULT_CVM_BINARY).is_file()
            and Path(DEFAULT_ASP_BIN).is_dir()):
        pytest.skip("requires the local CVM stack")

    sys.path.insert(0, str(REPO / "examples"))
    import lean_workflow as lw
    import temp_control_goals_lean as goals

    calls = []

    def counted(prompt):
        calls.append(prompt)
        return backend(prompt)

    proofs = goals.PACKAGE / goals.PROOFS_REL
    committed = proofs.read_bytes()
    protocols = lw.load_protocols(goals.CONFIG, validate=True)
    ctl = lw.synthesize_flow(
        goals.CONFIG, protocols, keep=False,
        engines=[LlmEngine(complete=counted, attempts=2)],
        stub="break")
    assert proofs.read_bytes() == committed  # seeds restored regardless
    assert calls, "the LLM was never invoked"
    key = "temp_control_goals_lean:verification"
    entry = ctl.blackboard.entries.get(key)
    if entry is not None and entry.good_standing:
        # the pass came from a fresh attested episode, not the memo
        assert ctl.blackboard.restarts.get(key, 0) >= 1
    else:
        # nondeterministic non-convergence: the human rung caught it
        assert key in ctl.blackboard.escalate


def test_cli_rejects_llm_flags_without_opt_in_chain():
    example = REPO / "examples" / "temp_control_goals_lean.py"
    for argv, expected in [
        (["--llm-only", "--synthesize"], "--llm-only requires --llm"),
        (["--llm", "openai"], "use it with --synthesize"),
    ]:
        proc = subprocess.run(
            [sys.executable, str(example), *argv],
            capture_output=True, text=True, cwd=REPO)
        assert proc.returncode != 0
        assert expected in proc.stderr
