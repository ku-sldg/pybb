"""Rodeo transport: appsumm parsing and dual-transport coexistence (no binaries)."""

from pybb import BlackboardController
from pybb.attestation import (
    AppraisalKS,
    AttestationKS,
    RodeoProtocol,
    TrustDecisionKS,
    parse_appsumm,
    request_key,
    verdict_key,
)

from test_knowledge_sources import FakeClient, _appr_response, _proto


def _appsumm(results: dict[str, bool], overall: bool | None = None) -> dict:
    payload = {
        "readfile_range_many_appr": {
            targ: {"meta": "" if ok else "slice mismatch", "result": ok}
            for targ, ok in results.items()
        }
    }
    return {
        "TYPE": "RESPONSE",
        "ACTION": "APPSUMM",
        "SUCCESS": True,
        "APPRAISAL_RESULT": all(results.values()) if overall is None else overall,
        "PAYLOAD": payload,
    }


def test_parse_appsumm_pass_and_fail():
    results = parse_appsumm(_appsumm({"contracts": True, "model": False}))
    by_id = {r.targ_id: r for r in results}
    assert by_id["contracts"].passed is True
    assert by_id["model"].passed is False
    assert by_id["model"].reason == "slice mismatch"
    assert by_id["model"].target_asp == "readfile_range_many"


def test_parse_appsumm_failed_run():
    assert parse_appsumm({"SUCCESS": False, "ACTION": "APPSUMM"}) == []


def _rodeo_proto(pid: str) -> RodeoProtocol:
    return RodeoProtocol(protocol_id=pid, attestation_root="/nowhere/attestation")


def test_dual_transport_coexistence():
    """Two AttestationKS instances (CVM + rodeo clients) share one blackboard."""
    cvm_client = FakeClient({"gumbo": _appr_response({"a.aadl": True})})
    rodeo_client = FakeClient({"isolette": _appsumm({"contracts": True})})

    ctl = BlackboardController()
    cvm_protos = {"gumbo": _proto("gumbo")}
    rodeo_protos = {"isolette": _rodeo_proto("isolette")}
    ctl.add_ks(AttestationKS(name="CvmAttestationKS", client=cvm_client, protocols=cvm_protos))
    ctl.add_ks(AttestationKS(name="RodeoAttestationKS", client=rodeo_client, protocols=rodeo_protos))
    ctl.add_ks(AppraisalKS(protocols={**cvm_protos, **rodeo_protos}))
    ctl.add_ks(TrustDecisionKS())

    for pid in ("gumbo", "isolette"):
        ctl.blackboard.write(
            key=request_key(pid), value={"protocol": pid}, source="seed",
            tags=["attestation", "request"],
        )
    bb = ctl.run()

    # each client served only its own protocol
    assert cvm_client.calls == ["gumbo"]
    assert rodeo_client.calls == ["isolette"]
    assert bb.read(verdict_key("gumbo"))["passed"] is True
    assert bb.read(verdict_key("isolette"))["passed"] is True
    assert bb.read(verdict_key("isolette"))["components"] == {"contracts": True}
    assert bb.hypothesis.startswith("All attested components intact")
    assert "gumbo" in bb.hypothesis and "isolette" in bb.hypothesis
