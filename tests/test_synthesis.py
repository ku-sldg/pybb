"""
Synthesis / black-box repair units (no CVM, no Lean toolchain).

The BLACK-BOX layer is the AutoVerus integration shape, proven with
stubs: an opaque tool the KS never inspects mutates external state; the
blackboard machinery (restart-episode) is the re-appraisal between its
attempts — each attempt sees the FRESH failure context, bounded by KS
attempts and the controller's restart cap, escalating as the human rung.

The LEAN layer units pin the mechanics under ProofSynthesisKS: statement-
preserving proof splicing, the engine ladder's candidate shapes, and the
LLM slot's prompt/stub behavior.
"""

import json

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    BlackBoxRepairKS,
    GoalContext,
    LlmEngine,
    TacticPortfolioEngine,
    splice_proof,
)


# ── black-box layer ───────────────────────────────────────────────────────────

def make_stub_predicate(state):
    cache = {}
    calls = []

    def predicate(measurement):
        key = json.dumps(measurement, sort_keys=True)
        if key not in cache:
            calls.append(dict(measurement))
            cache[key] = state["value"] >= state["target"]
        return cache[key]

    predicate.forget = lambda m: cache.pop(json.dumps(m, sort_keys=True), None)
    predicate.calls = calls
    return predicate


class OpaqueTool:
    """The black box: mutates state the KS never inspects, logs the
    contexts it was handed (to prove each attempt saw a fresh verdict)."""

    def __init__(self, state, effective=True):
        self.state = state
        self.effective = effective
        self.contexts = []

    def __call__(self, ctx):
        self.contexts.append(ctx)
        if self.effective:
            self.state["value"] += 1
        return True


def _run(state, ks, **controller_kwargs):
    ctl = BlackboardController(**controller_kwargs)
    fn = make_stub_predicate(state)
    ctl.register_predicate("check", fn)
    ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="entry:x", predicate="check",
                               measurement={"protocol": "stub"})
    ctl.route("entry:x", on_fail=[ks])
    return ctl.run(), fn


def test_per_attempt_reappraisal_between_black_box_attempts():
    """Three attempts to converge: every attempt is followed by a fresh
    episode (the re-appraisal), and each attempt's context carries the
    CURRENT verdict — the tool always sees fresh failure state."""
    state = {"value": 0, "target": 3}
    tool = OpaqueTool(state)
    ks = BlackBoxRepairKS(tool=tool, restart_policy="per_attempt",
                          max_attempts=5)
    bb, fn = _run(state, ks)
    assert bb.entries["entry:x"].good_standing
    assert len(tool.contexts) == 3          # three repair attempts
    assert bb.restarts == {"entry:x": 3}    # each one re-appraised
    assert len(fn.calls) == 4               # fail,fail,fail,pass — all fresh
    # every attempt saw the then-current (failing) verdict, never a stale None
    assert all(c.verdict is False for c in tool.contexts)


def test_on_local_clean_spends_restarts_only_when_check_passes():
    """The tool acts every attempt, but the local check gates the
    restart: only the finally-clean state is re-appraised."""
    state = {"value": 0, "target": 3}
    tool = OpaqueTool(state)
    ks = BlackBoxRepairKS(tool=tool, restart_policy="on_local_clean",
                          local_check=lambda: state["value"] >= state["target"],
                          max_attempts=5)
    bb, fn = _run(state, ks)
    assert bb.entries["entry:x"].good_standing
    assert len(tool.contexts) == 3
    assert bb.restarts == {"entry:x": 1}    # ONE attestation for three attempts
    assert len(fn.calls) == 2


def test_ineffective_tool_escalates_within_caps():
    state = {"value": 0, "target": 10 ** 9}
    tool = OpaqueTool(state)  # acts, never helps
    ks = BlackBoxRepairKS(tool=tool, restart_policy="per_attempt",
                          max_attempts=2)
    bb, fn = _run(state, ks, max_restarts_per_key=3)
    assert "entry:x" in bb.escalate
    assert bb.restarts["entry:x"] <= 3


def test_tool_that_declines_leads_to_escalation_without_restarts():
    state = {"value": 0, "target": 1}

    def declines(ctx):
        return False  # nothing tried

    ks = BlackBoxRepairKS(tool=declines, restart_policy="per_attempt",
                          max_attempts=2)
    bb, fn = _run(state, ks)
    assert "entry:x" in bb.escalate
    assert bb.restarts == {}


# ── Lean layer ────────────────────────────────────────────────────────────────

LEAN_TEXT = """import TempControl.Impl

namespace TempControl

theorem alpha : alpha_prop computeFanCmd := by
  unfold alpha_prop
  simp

theorem two_line :
    beta_prop computeFanCmd := by
  sorry

end TempControl
"""


def test_splice_proof_preserves_statement_and_reverts():
    spliced = splice_proof(LEAN_TEXT, "alpha", "by\n  omega")
    assert "theorem alpha : alpha_prop computeFanCmd := by\n  omega" in spliced
    assert "unfold alpha_prop" not in spliced
    assert "two_line" in spliced and "sorry" in spliced  # neighbors untouched
    # multi-line statement kept intact
    spliced2 = splice_proof(LEAN_TEXT, "two_line", "by\n  trivial")
    assert "theorem two_line :\n    beta_prop computeFanCmd := by\n  trivial" \
        in spliced2
    with pytest.raises(KeyError):
        splice_proof(LEAN_TEXT, "no_such_decl", "by\n  trivial")


def test_tactic_portfolio_shapes():
    engine = TacticPortfolioEngine()
    prop_cands = list(engine(GoalContext(
        name="w", statement="theorem w : hot_prop f", prop="hot_prop",
        helpers=["SetPoint.valid"], impl_name="computeFanCmd")))
    assert any("unfold hot_prop computeFanCmd" in c for c in prop_cands)
    assert any("SetPoint.valid" in c for c in prop_cands)
    assert any("split at h" in c for c in prop_cands)
    assert prop_cands[-1] == "by\n  decide"

    binding = list(engine(GoalContext(
        name="spec_holds", statement="theorem spec_holds : Spec f",
        binding=True, witnesses=["a", "b"])))
    assert binding == ["by\n  unfold Spec\n  exact ⟨a, b⟩"]

    helper_cands = list(engine(GoalContext(
        name="lemma1", statement="theorem lemma1 : X",
        helpers=["SetPoint.valid"])))
    assert any("unfold SetPoint.valid at *" in c for c in helper_cands)


def test_llm_engine_prompt_and_stub_backend():
    ctx = GoalContext(name="w", statement="theorem w : hot_prop f",
                      blessed_statement="def hot_prop ...",
                      detail="declaration uses sorry", seed="by\n  sorry")
    silent = LlmEngine()  # no backend
    assert list(silent(ctx)) == []
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return "by\n  omega"

    armed = LlmEngine(complete=complete, attempts=2)
    assert list(armed(ctx)) == ["by\n  omega", "by\n  omega"]
    assert "theorem w : hot_prop f" in prompts[0]
    assert "def hot_prop ..." in prompts[0]
    assert "declaration uses sorry" in prompts[0]
    assert "Previous attempt" in prompts[0]
