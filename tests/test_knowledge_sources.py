"""Attestation decision-tree behavior on the outcome-routed blackboard,
driven by a scripted fake client (no CVM needed).

The semantics under test:
    l1 pass -> confirm at l3 (when routed);  l3 pass = done, l3 fail = escalate
    l1 fail -> attribute at l2;              l2 pass = done, l2 fail = escalate
"""

import base64

from pybb import BlackboardController
from pybb.attestation import (
    ProtocolDir,
    TierKS,
    attestation_request,
    make_attestation_predicate,
    trust_summary,
)
from pybb.attestation.client import AttestationClient


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _appr_response(verdicts: dict[str, bool]) -> dict:
    """Build a minimal passing/failing response with one appraiser per target."""
    et = {"EvidenceT_CONSTRUCTOR": "mt_evt"}
    raw = []
    for name, ok in reversed(list(verdicts.items())):
        et = {
            "EvidenceT_CONSTRUCTOR": "split_evt",
            "EvidenceT_BODY": [
                {
                    "EvidenceT_CONSTRUCTOR": "asp_evt",
                    "EvidenceT_BODY": [
                        "P0",
                        {"ASP_ID": "hashfile_appr", "ASP_ARGS": {"filepath": f"/t/{name}"}},
                        {"EvidenceT_CONSTRUCTOR": "mt_evt"},
                    ],
                },
                et,
            ],
        }
        raw.insert(0, _b64("" if ok else "mismatch"))
    return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True, "PAYLOAD": [{"RawEv": raw}, et]}


class FakeClient(AttestationClient):
    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def run_protocol(self, protocol: ProtocolDir) -> dict:
        self.calls.append(protocol.protocol_id)
        result = self.responses[protocol.protocol_id]
        if isinstance(result, Exception):
            raise result
        return result


def _proto(pid: str) -> ProtocolDir:
    return ProtocolDir(
        protocol_id=pid, path="/nowhere", term={}, session={"Session_Plc": "P0"},
        manifest={"ASPS": []},
    )


PROTOS = {"l1": _proto("l1"), "l2": _proto("l2"), "l3": _proto("l3")}


def _controller(client, on_pass=(), on_fail=(), key="sys"):
    """Entry attested at l1, with confirmation/attribution tiers per outcome chain."""
    ctl = BlackboardController()
    ctl.register_predicate(
        "attestation", make_attestation_predicate(client, PROTOS)
    )
    pass_rungs = [TierKS(protocol_id=p) for p in on_pass]
    fail_rungs = [TierKS(protocol_id=p) for p in on_fail]
    for ks in [*pass_rungs, *fail_rungs]:
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(
        key=key, predicate="attestation",
        measurement=attestation_request("l1"),
    )
    ctl.route(key, on_pass=pass_rungs, on_fail=fail_rungs)
    return ctl


# ── l1 pass branch ────────────────────────────────────────────────────────────

def test_l1_pass_without_confirmation_chain_is_done():
    client = FakeClient({"l1": _appr_response({"a.aadl": True, "b.aadl": True})})
    ctl = _controller(client, on_fail=("l2",))
    bb = ctl.run()

    assert client.calls == ["l1"]
    entry = bb.get_entry("sys")
    assert entry.good_standing and entry.result.protocol == "l1"
    assert entry.ks_history == {}  # no rung ever fired
    assert "all attested components intact (l1 passed)" in trust_summary(bb)


def test_l1_pass_confirmed_by_l3():
    client = FakeClient({
        "l1": _appr_response({"a.aadl": True}),
        "l3": _appr_response({"tipe": True, "logika": True}),
    })
    ctl = _controller(client, on_pass=("l3",), on_fail=("l2",))
    bb = ctl.run()

    assert client.calls == ["l1", "l3"]  # l2 never ran
    entry = bb.get_entry("sys")
    assert entry.good_standing and entry.result.protocol == "l3"
    assert entry.ks_history == {"tier:l3": 1}
    assert "l1 passed; confirmed by l3" in trust_summary(bb)


def test_l1_pass_l3_refutes_escalates_with_l3_report():
    client = FakeClient({
        "l1": _appr_response({"a.aadl": True}),
        "l3": _appr_response({"tipe": True, "logika": False}),
    })
    ctl = _controller(client, on_pass=("l3",), on_fail=("l2",))
    bb = ctl.run()

    assert client.calls == ["l1", "l3"]
    assert "sys" in bb.escalate and "sys" not in bb.entries
    escalated = bb.escalate["sys"]
    assert escalated.result.protocol == "l3" and not escalated.result.passed
    summary = trust_summary(bb)
    assert "l1 passed but confirmation failed (l3)" in summary
    assert "logika" in summary and "user intervention required" in summary


# ── l1 fail branch ────────────────────────────────────────────────────────────

def test_l1_fail_l2_pass_is_done():
    client = FakeClient({
        "l1": _appr_response({"a.aadl": False}),
        "l2": _appr_response({"a.aadl:1-3": True, "a.aadl:5-9": True}),
    })
    ctl = _controller(client, on_pass=("l3",), on_fail=("l2",))
    bb = ctl.run()

    assert client.calls == ["l1", "l2"]  # l3 never ran
    entry = bb.get_entry("sys")
    assert entry.good_standing and entry.result.protocol == "l2"
    assert entry.ks_history == {"tier:l2": 1}
    assert "l2 passed after l1 failed" in trust_summary(bb)


def test_l1_fail_l2_fail_escalates_with_l2_report():
    client = FakeClient({
        "l1": _appr_response({"a.aadl": False}),
        "l2": _appr_response({"a.aadl:1-3": True, "a.aadl:5-9": False}),
        "l3": _appr_response({"logika": True}),
    })
    ctl = _controller(client, on_pass=("l3",), on_fail=("l2",))
    bb = ctl.run()

    # escalates directly off the l2 failure: l3 is NOT tried on this branch
    assert client.calls == ["l1", "l2"]
    assert "sys" in bb.escalate and "sys" not in bb.entries
    escalated = bb.escalate["sys"]
    assert escalated.ks_history == {"tier:l2": 1}
    assert escalated.result.protocol == "l2" and not escalated.result.passed
    summary = trust_summary(bb)
    assert "ladder exhausted (l1, l2 failed)" in summary
    assert "a.aadl:5-9" in summary and "a.aadl:1-3" not in summary
    assert "user intervention required" in summary


def test_l1_fail_with_empty_on_fail_chain_escalates_immediately():
    client = FakeClient({"l1": RuntimeError("cvm exploded")})
    ctl = _controller(client)  # no chains at all
    bb = ctl.run()

    assert "sys" in bb.escalate and "sys" not in bb.entries
    assert "cvm exploded" in bb.escalate["sys"].result.error
    assert "cvm exploded" in trust_summary(bb)


# ── plumbing ──────────────────────────────────────────────────────────────────

def test_predicate_memoizes_per_lifetime():
    client = FakeClient({"l1": _appr_response({"a.aadl": True})})
    predicate = make_attestation_predicate(client, PROTOS)

    first = predicate(attestation_request("l1"))
    again = predicate(attestation_request("l1"))
    assert first is again and client.calls == ["l1"]

    # a fresh predicate (fresh workflow run) re-attests
    fresh = make_attestation_predicate(client, PROTOS)
    fresh(attestation_request("l1"))
    assert client.calls == ["l1", "l1"]


def test_history_is_audit_trail():
    client = FakeClient({
        "l1": _appr_response({"a.aadl": False}),
        "l2": _appr_response({"a.aadl:1-3": True}),
    })
    ctl = _controller(client, on_fail=("l2",))
    bb = ctl.run()

    verdicts = [
        (entry.result.protocol, entry.result.passed)
        for key, entry in bb.get_history()
        if key == "sys" and entry.result is not None
    ]
    # l1 failure recorded first, l2 pass last (bookkeeping may repeat states)
    assert verdicts[0] == ("l1", False)
    assert verdicts[-1] == ("l2", True)
