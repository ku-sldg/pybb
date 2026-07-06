"""Knowledge-source behavior with a scripted fake client (no CVM needed)."""

import base64

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    EscalationKS,
    ProtocolDir,
    TrustDecisionKS,
    component_key,
    evidence_key,
    request_key,
    verdict_key,
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

    def run_protocol(self, protocol: ProtocolDir, path_map=None) -> dict:
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


def _controller(client, protocols, with_escalation=True):
    ctl = BlackboardController()
    ctl.add_ks(AttestationKS(client=client, protocols=protocols))
    ctl.add_ks(AppraisalKS(protocols=protocols))
    if with_escalation:
        ctl.add_ks(EscalationKS(on_fail="l1", escalate_to="l2"))
    ctl.add_ks(TrustDecisionKS())
    return ctl


PROTOS = {"l1": _proto("l1"), "l2": _proto("l2")}


def _seed(ctl, pid="l1"):
    ctl.blackboard.write(
        key=request_key(pid), value={"protocol": pid}, source="seed",
        tags=["attestation", "request"],
    )


def test_pass_path_no_escalation():
    client = FakeClient({"l1": _appr_response({"a.aadl": True, "b.aadl": True})})
    ctl = _controller(client, PROTOS)
    _seed(ctl)
    bb = ctl.run()

    assert client.calls == ["l1"]
    assert bb.read(verdict_key("l1"))["passed"] is True
    assert not bb.has(request_key("l2"))
    assert bb.hypothesis.startswith("All attested components intact")
    assert bb.entries[verdict_key("l1")].confidence == 1.0


def test_fail_escalates_and_attributes():
    client = FakeClient({
        "l1": _appr_response({"a.aadl": False}),
        "l2": _appr_response({"a.aadl:1-3": True, "a.aadl:5-9": False}),
    })
    ctl = _controller(client, PROTOS)
    _seed(ctl)
    bb = ctl.run()

    assert client.calls == ["l1", "l2"]
    assert bb.read(verdict_key("l1"))["passed"] is False
    l2 = bb.read(verdict_key("l2"))
    assert l2["passed"] is False
    assert l2["components"] == {"a.aadl:1-3": True, "a.aadl:5-9": False}
    comp = bb.read(component_key("l2", "a.aadl:5-9"))
    assert comp["passed"] is False and comp["reason"] == "mismatch"
    assert "l2/a.aadl:5-9" in bb.hypothesis
    assert "l2/a.aadl:1-3" not in bb.hypothesis
    # escalation request carries provenance
    assert bb.read(request_key("l2"))["triggered_by"] == "l1"


def test_client_error_becomes_failed_verdict():
    client = FakeClient({"l1": RuntimeError("cvm exploded")})
    ctl = _controller(client, PROTOS, with_escalation=False)
    _seed(ctl)
    bb = ctl.run()

    ev = bb.read(evidence_key("l1"))
    assert ev["success"] is False and "cvm exploded" in ev["error"]
    assert "error" in bb.entries[evidence_key("l1")].tags
    assert bb.read(verdict_key("l1"))["passed"] is False
    assert "no appraisal evidence" in bb.hypothesis


def test_reposted_request_reruns_pipeline():
    client = FakeClient({"l1": _appr_response({"a.aadl": True})})
    ctl = _controller(client, PROTOS, with_escalation=False)
    _seed(ctl)
    ctl.run()
    assert client.calls == ["l1"]

    # re-post the same request id: timestamp guards must re-run attest+appraise
    _seed(ctl)
    ctl.max_cycles = 110
    ctl.run()
    assert client.calls == ["l1", "l1"]


def test_history_is_audit_trail():
    client = FakeClient({"l1": _appr_response({"a.aadl": True})})
    ctl = _controller(client, PROTOS, with_escalation=False)
    _seed(ctl)
    bb = ctl.run()
    keys = [e.key for e in bb.history]
    assert keys == [
        request_key("l1"),
        evidence_key("l1"),
        component_key("l1", "a.aadl"),
        verdict_key("l1"),
        "attestation.hypothesis",
    ]
    sources = [e.source for e in bb.history]
    assert sources == ["seed", "AttestationKS", "AppraisalKS", "AppraisalKS", "TrustDecisionKS"]
