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
    OutOfBandRepairKS,
    TacticPortfolioEngine,
    splice_proof,
)
from pybb.attestation.appraisal import ComponentResult
from pybb.attestation.knowledge_sources import Verdict
from pybb.attestation.synthesis import RepairContext


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


# ── the pause rung (out-of-band repair) ───────────────────────────────────────

def test_out_of_band_repair_judged_by_fresh_measurement():
    """The gate blocks, the 'operator' fixes the world out-of-band, and
    'r' buys exactly one restart — the fresh measurement is the judge,
    the operator's claim never counts by itself."""
    state = {"value": 0, "target": 1}
    orders = []

    def gate(order):
        orders.append(order)
        state["value"] += 1   # the out-of-band fix (editor, agent, ...)
        return True

    ks = OutOfBandRepairKS(gate=gate)
    bb, fn = _run(state, ks)
    assert bb.entries["entry:x"].good_standing
    assert bb.restarts == {"entry:x": 1}
    assert len(orders) == 1
    assert "paused for out-of-band repair (attempt 1/3)" in orders[0]
    assert "nothing done out-of-band counts" in orders[0]


def test_out_of_band_skip_falls_through_to_escalation():
    """'s' declines: nothing tried, no restart spent, and after
    max_attempts the key follows ordinary handoff/escalation."""
    state = {"value": 0, "target": 1}
    orders = []
    ks = OutOfBandRepairKS(gate=lambda o: orders.append(o) or False,
                           max_attempts=2)
    bb, fn = _run(state, ks)
    assert "entry:x" in bb.escalate
    assert bb.restarts == {}
    assert len(orders) == 2


def test_out_of_band_ineffective_claim_costs_a_restart_then_escalates():
    """A claimed repair that changed nothing: every claim is judged (and
    refuted) by a fresh measurement, and the controller's restart law is
    the bound — a fresh episode brings a fresh KS budget by design, so
    the law, not max_attempts, ends a gate that always claims success."""
    state = {"value": 0, "target": 10 ** 9}
    ks = OutOfBandRepairKS(gate=lambda o: True, max_attempts=2)
    bb, fn = _run(state, ks, max_restarts_per_key=3)
    assert "entry:x" in bb.escalate
    assert bb.restarts["entry:x"] <= 3


def test_out_of_band_work_order_renders_verdict_and_report():
    verdict = Verdict(protocol="p", passed=False, components=[
        ComponentResult(appr_asp="a", target_asp="t", targ_id="slice_targ",
                        passed=False, reason="hash mismatch",
                        args={"filepath": "/pkg/Props.v"}),
    ], error="")
    ks = OutOfBandRepairKS(gate=lambda o: False,
                           report=lambda: "still open:\n- goal_a")
    order = ks._work_order(RepairContext(key="k", verdict=verdict, attempt=2))
    assert "'k' paused for out-of-band repair (attempt 2/3)" in order
    assert "slice_targ [/pkg/Props.v]: hash mismatch" in order
    assert "still open:\n    - goal_a" in order


def test_black_box_also_siblings_revived_and_restarted():
    """`also` on a restart-requesting rung: staled siblings are
    restarted alongside, revived from escalate when needed."""
    from pybb.blackboard import Blackboard
    bb = Blackboard()
    bb.write_entry(key="a", predicate="check", measurement={})
    bb.write_entry(key="b", predicate="check", measurement={})
    bb.escalate["b"] = bb.entries.pop("b")   # b died on the stale tree
    ks = BlackBoxRepairKS(tool=lambda ctx: True, also=["b"])
    ks._request_restart(bb, "a", "repaired")
    assert set(bb.restart_requests) == {"a", "b"}
    assert "b" in bb.entries and "b" not in bb.escalate


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
    # a STUBBED seed is not guidance: _stub_proofs overwrote the body, so
    # forwarding `by sorry` as a "previous attempt" only wastes prompt
    # space telling the model what the failure detail already says
    assert "Previous attempt" not in prompts[0]
    # a real seed (the --break-proof arc, where the body is corrupted
    # rather than stubbed) still reaches the prompt as guidance
    seeded = ctx.model_copy(update={"seed": "by\n  intros\n  rfl"})
    assert list(LlmEngine(complete=complete, attempts=1)(seeded))
    assert "Previous attempt" in prompts[-1]
    assert "intros" in prompts[-1]
