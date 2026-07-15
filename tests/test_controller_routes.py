"""Outcome-routed dispatch in the core controller (no attestation involved).

route(key, chain) keeps its original meaning (an on_fail repair chain), so
existing number/pair examples behave as before; the new on_pass chain makes
a passing evaluation provisional until the chain's work re-evaluates.
"""

from pybb import (
    BlackboardController,
    ComponentAdder,
    ComponentSubtractor,
    NumberAdder,
    NumberNothinger,
    NumberSubtractor,
    is_positive,
    less_than_3,
)


def _controller():
    ctl = BlackboardController()
    ctl.register_predicate("less_than_3", less_than_3)
    ctl.register_predicate("is_positive", is_positive)
    return ctl


def test_positional_route_still_means_on_fail_chain():
    """Anakha's original example flow: failing entry repaired by the chain."""
    ctl = _controller()
    adder = NumberAdder()
    ctl.add_ks(adder)
    ctl.blackboard.write_entry(key="is_positive", predicate="is_positive", measurement=-2)
    ctl.route("is_positive", [adder])
    bb = ctl.run()

    entry = bb.get_entry("is_positive")
    assert entry.good_standing and entry.measurement == 1
    assert entry.ks_history == {"NumberAdder": 3}


def test_on_fail_exhaustion_still_escalates():
    ctl = _controller()
    nothinger = NumberNothinger()
    ctl.add_ks(nothinger)
    ctl.blackboard.write_entry(key="is_positive", predicate="is_positive", measurement=-1)
    ctl.route("is_positive", [nothinger])
    bb = ctl.run()

    assert "is_positive" in bb.escalate and "is_positive" not in bb.entries
    assert bb.escalate["is_positive"].ks_history == {"NumberNothinger": 3}


def test_component_pair_flow_unchanged():
    """anakha/c's pair example: component-scoped KSes with success handoff."""
    ctl = _controller()
    x_fixer = ComponentSubtractor(name="XSubtractor", component="x")
    y_fixer = ComponentAdder(name="YAdder", component="y")
    for ks in (x_fixer, y_fixer):
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(
        key="pair", measurement={"x": 5, "y": -2},
        conditions={"x": "less_than_3", "y": "is_positive"})
    ctl.route("pair", [x_fixer, y_fixer])
    bb = ctl.run()

    entry = bb.get_entry("pair")
    assert entry.good_standing
    assert entry.measurement == {"x": 2, "y": 1}


def test_on_pass_chain_confirms_a_provisional_pass():
    """A passing entry with an on_pass chain is not done until the chain runs."""
    ctl = _controller()
    subtractor = NumberSubtractor()
    ctl.add_ks(subtractor)
    ctl.blackboard.write_entry(key="lt3", predicate="less_than_3", measurement=2)
    ctl.route("lt3", on_pass=[subtractor])
    bb = ctl.run()

    entry = bb.get_entry("lt3")
    assert entry.good_standing
    assert entry.measurement == 1  # confirmation chain actually ran
    assert entry.ks_history == {"NumberSubtractor": 1}


def test_on_pass_chain_that_cannot_confirm_escalates():
    """Confirmation work drives the entry out of standing and exhausts: escalate."""
    ctl = _controller()
    subtractor = NumberSubtractor()  # each run pushes further below zero
    ctl.add_ks(subtractor)
    ctl.blackboard.write_entry(key="is_positive", predicate="is_positive", measurement=1)
    ctl.route("is_positive", on_pass=[subtractor])
    bb = ctl.run()

    assert "is_positive" in bb.escalate
    assert bb.escalate["is_positive"].ks_history == {"NumberSubtractor": 3}


def test_unrouted_failing_entry_just_halts():
    """No route: entry stays on the board out of good standing (pre-existing behavior)."""
    ctl = _controller()
    ctl.blackboard.write_entry(key="is_positive", predicate="is_positive", measurement=-5)
    bb = ctl.run()

    entry = bb.get_entry("is_positive")
    assert entry is not None and not entry.good_standing
    assert not bb.escalate
