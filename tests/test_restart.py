"""
Restart-episode primitive, core semantics (stub predicates, no CVM).

What is pinned:

  - a restart yields a genuinely FRESH evaluation: the predicate's memo is
    forgotten for the entry's episode measurements, the entry is reseeded
    from its original measurement with a fresh KS budget, and the dispatch
    latch clears;
  - restarts are PULL-ONLY and free between requests: a knowledge source
    may perform any number of writes and bare-tool checks inside execute()
    with ZERO predicate evaluations happening until it asks;
  - request_restart works cross-entry (a KS repairing one entry's subject
    can stale-invalidate a sibling entry's verdict);
  - halting is law, not politeness: RestartEpisodeKS's budget is chain
    policy, and the controller's max_restarts_per_key caps every requester,
    with end-of-route escalation carrying the last failing state;
  - the step-4 synthesis loop shape works: one candidate per episode,
    re-judged each restart, converging within budget.
"""

import json

from pybb import BlackboardController
from pybb.attestation.knowledge_sources import RestartEpisodeKS
from pybb.knowledge_source import KnowledgeSource


def make_stub_predicate(state: dict):
    """Memoized predicate over external state (passes when value >= target),
    with the same memo/forget shape as make_attestation_predicate. `calls`
    records every REAL evaluation — the memo-bypass instrument."""
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


class BumpKS(KnowledgeSource):
    """The repair stand-in: one increment of external state per attempt."""

    name: str = "bump"
    partition: list[str] = []
    max_attempts: int = 1
    state: object  # typed loosely so pydantic passes the REFERENCE through uncopied

    def execute(self, blackboard, keys):
        for _ in keys:
            self.state["value"] += 1


class LocalIterateKS(KnowledgeSource):
    """The free-iteration stand-in: MANY candidate writes and bare-tool
    checks inside one execute; requests judgment only for the candidate
    that locally passes."""

    name: str = "iterate"
    partition: list[str] = []
    max_attempts: int = 1
    state: object  # typed loosely so pydantic passes the REFERENCE through uncopied
    iterations: int = 50

    def execute(self, blackboard, keys):
        for key in keys:
            for candidate in range(1, self.iterations + 1):
                self.state["value"] = candidate  # a "write"
                locally_ok = self.state["value"] >= self.state["target"]
                if locally_ok:  # the bare-tool check, untrusted
                    blackboard.request_restart(key, "candidate elaborates")
                    return


class GreedyRestartKS(KnowledgeSource):
    """Requests a restart every attempt without ever fixing anything —
    the impolite requester the controller cap exists for."""

    name: str = "greedy"
    partition: list[str] = []
    max_attempts: int = 2

    def execute(self, blackboard, keys):
        for key in keys:
            blackboard.request_restart(key, "because")


class CrossRestartKS(KnowledgeSource):
    """Fixes its own entry's subject and stale-invalidates a sibling."""

    name: str = "cross"
    partition: list[str] = []
    max_attempts: int = 1
    state: object  # typed loosely so pydantic passes the REFERENCE through uncopied
    sibling: str

    def execute(self, blackboard, keys):
        for key in keys:
            self.state["value"] += 10  # the "impl write"
            blackboard.request_restart(key, "re-judge me")
            blackboard.request_restart(self.sibling, "my write staled you")


def _controller(state, chain, key="entry:a", predicate=None, **kwargs):
    ctl = BlackboardController(**kwargs)
    fn = predicate if predicate is not None else make_stub_predicate(state)
    ctl.register_predicate("check", fn)
    for ks in chain:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key=key, predicate="check",
                               measurement={"protocol": "stub"})
    ctl.route(key, on_fail=chain)
    return ctl, fn


def test_restart_yields_fresh_evaluation():
    state = {"value": 0, "target": 1}
    chain = [BumpKS(state=state), RestartEpisodeKS(budget=1)]
    ctl, fn = _controller(state, chain)
    bb = ctl.run()
    entry = bb.entries["entry:a"]
    assert entry.good_standing
    assert not bb.escalate
    assert bb.restarts == {"entry:a": 1}
    # exactly two REAL evaluations: the failing episode 1, the fresh pass
    assert len(fn.calls) == 2
    # fresh episode: reseeded measurement, fresh KS budget
    assert entry.measurement == {"protocol": "stub"}
    assert entry.ks_history == {}


def test_iteration_between_restarts_is_free():
    """50 writes + local checks inside one execute; predicate evaluated
    exactly twice — attestation cost is O(1) per accepted candidate."""
    state = {"value": 0, "target": 37}
    chain = [LocalIterateKS(state=state, iterations=50)]
    ctl, fn = _controller(state, chain)
    bb = ctl.run()
    assert bb.entries["entry:a"].good_standing
    assert bb.restarts == {"entry:a": 1}
    assert len(fn.calls) == 2


def test_budget_exhaustion_escalates_with_bounded_loop():
    state = {"value": 0, "target": 10 ** 9}  # unreachable
    chain = [BumpKS(state=state), RestartEpisodeKS(budget=2)]
    ctl, fn = _controller(state, chain)
    bb = ctl.run()
    assert "entry:a" in bb.escalate
    assert bb.restarts == {"entry:a": 2}
    assert ctl.cycle_count < ctl.max_cycles  # halted by budget, not backstop
    assert len(fn.calls) == 3  # episodes 1..3 each measured once


def test_controller_cap_bounds_impolite_requesters():
    """Direct request_restart bypasses any chain budget; the controller's
    max_restarts_per_key is the law that still bounds it."""
    state = {"value": 0, "target": 10 ** 9}
    chain = [GreedyRestartKS()]
    ctl, fn = _controller(state, chain, max_restarts_per_key=2)
    bb = ctl.run()
    assert bb.restarts == {"entry:a": 2}
    assert "entry:a" in bb.escalate  # greedy exhausted after cap cut it off
    assert ctl.cycle_count < ctl.max_cycles


def test_stale_request_is_dropped():
    state = {"value": 1, "target": 1}
    ctl, fn = _controller(state, [])
    ctl.blackboard.request_restart("no:such:entry", "stale")
    bb = ctl.run()
    assert bb.restart_requests == {}
    assert bb.restarts == {}
    assert bb.entries["entry:a"].good_standing


def test_cross_entry_restart_re_measures_the_sibling():
    """entry:b passes and memoizes in episode 1; entry:a's KS write changes
    the shared state and requests b's restart — b is genuinely re-measured
    and now fails (dispatch routes it to escalation)."""
    state = {"value": 0, "target": 1}
    b_calls = []
    b_cache = {}

    def b_predicate(measurement):
        key = json.dumps(measurement, sort_keys=True)
        if key not in b_cache:
            b_calls.append(dict(measurement))
            b_cache[key] = state["value"] < 5  # true before the write
        return b_cache[key]

    b_predicate.forget = lambda m: b_cache.pop(
        json.dumps(m, sort_keys=True), None)

    chain = [CrossRestartKS(state=state, sibling="entry:b")]
    ctl, fn = _controller(state, chain)
    ctl.register_predicate("check_b", b_predicate)
    ctl.blackboard.write_entry(key="entry:b", predicate="check_b",
                               measurement={"protocol": "b"})
    ctl.route("entry:b", on_fail=[])
    bb = ctl.run()
    assert bb.entries["entry:a"].good_standing  # the write fixed a
    assert len(b_calls) == 2                    # b was re-measured...
    assert "entry:b" in bb.escalate             # ...and the fresh verdict rules
    assert bb.restarts == {"entry:a": 1, "entry:b": 1}


def test_synthesis_loop_shape_converges_within_budget():
    """The step-4 loop: one candidate per episode, judged fresh each
    restart, passing on the third candidate."""
    state = {"value": 0, "target": 3}
    chain = [BumpKS(state=state), RestartEpisodeKS(budget=5)]
    ctl, fn = _controller(state, chain)
    bb = ctl.run()
    assert bb.entries["entry:a"].good_standing
    assert not bb.escalate
    assert bb.restarts == {"entry:a": 3}
    assert len(fn.calls) == 4  # fail, fail, fail, pass — one per episode
