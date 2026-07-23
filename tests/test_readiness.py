"""
Protocol readiness: the first verdict of an attestation episode. Predicate
checks (no CVM needed) and the two-entry flow — readiness pass starts the
attestation entry via StartAttestationKS; readiness failure escalates as a
configuration failure and attestation never begins.
"""

import base64

from pybb import BlackboardController
from pybb.attestation import (
    ProtocolDir,
    StartAttestationKS,
    TierKS,
    make_readiness_predicate,
    readiness_request,
    trust_summary,
)
from pybb.attestation.client import CvmConfig


def _config(tmp_path, asps=("hashfile", "sig")) -> CvmConfig:
    cvm = tmp_path / "cvm"
    cvm.write_text("#!/bin/sh\n")
    asp_bin = tmp_path / "asps"
    asp_bin.mkdir()
    for asp in asps:
        exe = asp_bin / asp
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
    return CvmConfig(cvm_binary=str(cvm), asp_bin=str(asp_bin))


def _protocol(pid="l1", golden="GOLD") -> ProtocolDir:
    return ProtocolDir(
        protocol_id=pid, path="/nowhere",
        term={"TERM_CONSTRUCTOR": "asp"},
        session={"Session_Plc": "P0", "Session_Context": {
            "ASP_Comps": {"hashfile": "goldenbytes_appr", "sig": "sig_appr"}}},
        manifest={"ASPS": ["hashfile", "sig"]},
        asp_args={"hashfile": {"t1": {"filepath": "/f", "golden_b64": golden}}},
    )


def test_ready_when_everything_present(tmp_path):
    predicate = make_readiness_predicate({"l1": _protocol()}, _config(tmp_path))
    report = predicate(readiness_request(["l1"]))
    assert report and report.checked == ["l1"] and report.problems == []


def test_unknown_protocol_is_a_problem(tmp_path):
    predicate = make_readiness_predicate({"l1": _protocol()}, _config(tmp_path))
    report = predicate(readiness_request(["l1", "l9"]))
    assert not report and "l9: unknown protocol" in report.problems


def test_unprovisioned_golden_target_is_a_problem(tmp_path):
    predicate = make_readiness_predicate(
        {"l1": _protocol(golden="")}, _config(tmp_path))
    report = predicate(readiness_request(["l1"]))
    assert not report
    assert any("no provisioned golden" in p for p in report.problems)


def test_missing_asp_executable_is_a_problem(tmp_path):
    predicate = make_readiness_predicate(
        {"l1": _protocol()}, _config(tmp_path, asps=("hashfile",)))  # no sig
    report = predicate(readiness_request(["l1"]))
    assert not report
    assert any("ASP executable not found: sig" in p for p in report.problems)


def test_missing_cvm_binary_is_a_problem(tmp_path):
    config = _config(tmp_path)
    config.cvm_binary = str(tmp_path / "nope")
    predicate = make_readiness_predicate({"l1": _protocol()}, config)
    report = predicate(readiness_request(["l1"]))
    assert not report and any("CVM binary" in p for p in report.problems)


def test_memoized_per_lifetime(tmp_path):
    predicate = make_readiness_predicate({"l1": _protocol()}, _config(tmp_path))
    first = predicate(readiness_request(["l1"]))
    assert predicate(readiness_request(["l1"])) is first


# ── the two-entry flow ────────────────────────────────────────────────────────

def _appr_response(ok: bool) -> dict:
    et = {
        "EvidenceT_CONSTRUCTOR": "asp_evt",
        "EvidenceT_BODY": [
            "P0",
            {"ASP_ID": "hashfile_appr", "ASP_ARGS": {"filepath": "/f"}},
            {"EvidenceT_CONSTRUCTOR": "mt_evt"},
        ],
    }
    raw = [base64.b64encode(b"" if ok else b"mismatch").decode()]
    return {"TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True,
            "PAYLOAD": [{"RawEv": raw}, et]}


def _flow_controller(tmp_path, checked, l1_ok=True):
    from pybb.attestation import make_attestation_predicate
    from pybb.attestation.client import AttestationClient

    protocols = {"l1": _protocol("l1"), "l2": _protocol("l2")}

    class Client(AttestationClient):
        def run_protocol(self, protocol):
            return _appr_response(l1_ok if protocol.protocol_id == "l1" else True)

    ctl = BlackboardController()
    ctl.register_predicate("protocol_check",
                           make_readiness_predicate(protocols, _config(tmp_path)))
    ctl.register_predicate("attestation",
                           make_attestation_predicate(Client(), protocols))
    starter = StartAttestationKS(episodes={"sys": "l1"})
    attribute = TierKS(protocol_id="l2")
    for ks in (starter, attribute):
        ctl.add_ks(ks)
    ctl.route("sys", on_fail=[attribute])
    ctl.route("sys:ready", on_pass=[starter], on_fail=[])
    ctl.blackboard.write_entry(key="sys:ready", predicate="protocol_check",
                               measurement=readiness_request(checked))
    return ctl


def test_readiness_pass_starts_attestation_with_full_tree(tmp_path):
    ctl = _flow_controller(tmp_path, ["l1", "l2"], l1_ok=True)
    bb = ctl.run()

    ready = bb.entries["sys:ready"]
    assert ready.good_standing and ready.ks_history == {"start:sys": 1}
    sys_entry = bb.entries["sys"]
    assert sys_entry.good_standing and sys_entry.result.protocol == "l1"
    assert "sys:ready: protocols validated (l1, l2)" in trust_summary(bb)


def test_readiness_pass_then_l1_fail_walks_the_fail_chain(tmp_path):
    ctl = _flow_controller(tmp_path, ["l1", "l2"], l1_ok=False)
    bb = ctl.run()

    # the attestation entry keeps its own branch point: l1 fail -> l2
    sys_entry = bb.entries["sys"]
    assert sys_entry.good_standing and sys_entry.result.protocol == "l2"
    assert sys_entry.ks_history == {"tier:l2": 1}


def test_readiness_failure_escalates_and_never_starts_attestation(tmp_path):
    ctl = _flow_controller(tmp_path, ["l1", "l2", "l9"])
    bb = ctl.run()

    assert "sys:ready" in bb.escalate and "sys:ready" not in bb.entries
    assert "l9: unknown protocol" in bb.escalate["sys:ready"].result.problems
    assert "sys" not in bb.entries  # attestation never began
    summary = trust_summary(bb)
    assert "protocol readiness failed" in summary and "l9" in summary
    assert "attestation never started" in summary


def test_starter_never_clobbers_live_episode(tmp_path):
    ctl = _flow_controller(tmp_path, ["l1", "l2"])
    ctl.blackboard.write_entry(key="sys", predicate="attestation",
                               measurement={"protocol": "l2"})
    ctl.run()
    # pre-existing entry untouched by the starter
    assert ctl.blackboard.entries["sys"].measurement == {"protocol": "l2"}
