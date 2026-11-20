"""
Protocol readiness: the first verdict of an attestation episode. Predicate
checks (no CVM needed) and the two-entry flow — readiness pass starts the
attestation entry via StartAttestationKS; readiness failure escalates as a
configuration failure and attestation never begins.
"""

import pytest

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

@pytest.fixture(autouse=True)
def _legacy_interpreter(monkeypatch):
    """These tests drive the predicate with FABRICATED responses via stub
    clients; the verified summarizer rightly refuses non-evidence, so the
    legacy parser is pinned explicitly here."""
    from pybb.attestation import summarizer
    monkeypatch.setattr(summarizer, "EVIDENCE_TOOLS_BIN", "/nonexistent")




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


# ── ledger readiness (docs/ledger_plan.md B.7 / B.8) ─────────────────────────


def _ledger_cfg(tmp_path, **kw):
    from pybb.attestation.ledger import LedgerConfig
    base = dict(state_dir=str(tmp_path / "state"), appraiser_id="ap-r", evidence_repo="",
                golden_root=str(tmp_path / "golden"))
    base.update(kw)
    return LedgerConfig(**base)


LEDGER_ASPS = ("hashfile", "sig", "generate_nonce", "nonce_appr", "hashevidence", "magic_appr")


def _sig_protocol(pid="l1"):
    p = _protocol(pid)
    p.term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "ASPC",
                                                 "ASP_BODY": {"ASP_ID": "hashfile", "ASP_TARG_ID": "t1"}}},
        {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}]}
    return p


def test_ledger_readiness_reports_reachable_assurance(tmp_path):
    predicate = make_readiness_predicate({"l1": _sig_protocol()}, _config(tmp_path, LEDGER_ASPS),
                                         ledger_config=_ledger_cfg(tmp_path))
    r = predicate(readiness_request(["l1"]))
    assert r and r.assurance == {"l1": "signed+nonce"} and r.assurance_excepted == {}


def test_ledger_readiness_flags_protocols_below_minimum_unless_excepted(tmp_path):
    unsigned = _protocol("plain")  # no SIG in the term
    cvm = _config(tmp_path, LEDGER_ASPS)
    cfg = _ledger_cfg(tmp_path)
    r = make_readiness_predicate({"plain": unsigned}, cvm, ledger_config=cfg)(readiness_request(["plain"]))
    assert not r and r.assurance == {"plain": "nonce"}
    assert any("below the ledger minimum 'signed+nonce'" in p for p in r.problems)
    cfg2 = _ledger_cfg(tmp_path, assurance_exceptions={"plain": "readiness probe"})
    r2 = make_readiness_predicate({"plain": unsigned}, cvm, ledger_config=cfg2)(readiness_request(["plain"]))
    assert r2 and r2.assurance_excepted == {"plain": "readiness probe"}


def test_ledger_readiness_requires_the_ledger_asps(tmp_path):
    r = make_readiness_predicate({"l1": _sig_protocol()}, _config(tmp_path, ("hashfile", "sig")),
                                 ledger_config=_ledger_cfg(tmp_path))(readiness_request(["l1"]))
    assert not r
    missing = {p.split(": ")[1] for p in r.problems if p.startswith("ledger ASP executable not found")}
    assert missing == {"generate_nonce", "nonce_appr", "hashevidence", "magic_appr"}


def test_ledger_readiness_reports_this_writers_stack_evidence(tmp_path):
    """Plan O.10: with a ledger, readiness needs a stack bundle and a blessing
    from this writer (problems), and reports the latest stack bundle's
    blessing and audit state (information)."""
    from pybb.attestation import FileLedger
    from pybb.attestation.ledger_context import bless, measure_stack
    from test_ledger_context import ContextClient

    cfg = _ledger_cfg(tmp_path)
    protos = {"l1": _sig_protocol()}
    cvm = _config(tmp_path, LEDGER_ASPS)
    ledger = FileLedger(tmp_path / "ledger.jsonl")
    r = make_readiness_predicate(protos, cvm, ledger_config=cfg, ledger=ledger)(readiness_request(["l1"]))
    assert not r and any("no stack bundle for this writer" in p for p in r.problems)

    fake = type("Cvm", (), {})()
    fake.cvm_binary, fake.asp_bin, fake.log_level, fake.timeout_s, fake.path_prepend = \
        str(cvm.cvm_binary), str(cvm.asp_bin), "Info", 10, []
    m = measure_stack(ContextClient(), ledger, cfg, cvm_config=fake, summarizer_bin=str(cvm.cvm_binary))
    assert m, m.error
    r = make_readiness_predicate(protos, cvm, ledger_config=cfg, ledger=ledger)(readiness_request(["l1"]))
    assert not r and any("no blessing for this writer" in p for p in r.problems)
    assert r.context["stack_bid"] == m.bid

    bless(ledger, cfg, m.bid)
    r = make_readiness_predicate(protos, cvm, ledger_config=cfg, ledger=ledger)(readiness_request(["l1"]))
    assert r, r.problems
    assert r.context == {"stack_bid": m.bid, "blessing_key": f"blessing/{m.bid}",
                         "latest_stack_blessed": "true", "stack_audit": "none"}
    # without a ledger handle nothing about the stack is checked
    assert make_readiness_predicate(protos, cvm, ledger_config=cfg)(readiness_request(["l1"]))
