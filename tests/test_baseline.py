"""
Signed golden-baseline verification: provisioning already stores a SIGNED
Copland evidence bundle per protocol (measurement term + SIG, APPR
stripped); verify_bundle closes the loop by re-appraising the stored
bundle through the CVM itself — TERM = APPR over the bundle's evidence,
with each installed golden_b64 injected so the goldenbytes companions
anchor the signed bytes against the installed values, while the sig event
dispatches sig_appr over the signature.

Runs against the committed temp_control_lean_l1a/temp_control_lean_l2 bundles; auto-skipped unless
the CVM binary and asp-libs are present.
"""

import json
from pathlib import Path

import pytest

from pybb.attestation import CvmSubprocessClient, ProtocolDir, verify_bundle
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
        reason="requires local CVM binary and asp-libs binaries",
    ),
]


def _client():
    return CvmSubprocessClient()


def _load(pid: str) -> ProtocolDir:
    return ProtocolDir.load(str(FIXTURES / pid))


def test_clean_bundles_verify_and_anchor_every_golden():
    for pid, n_targets in (("temp_control_lean_l1a", 6), ("temp_control_lean_l2", 15)):
        report = verify_bundle(_client(), _load(pid), GOLDEN_ROOT)
        assert report, report.problems
        assert report.signature_ok
        assert len(report.anchored) == n_targets
        # the signature component came from the CVM's own appraisal walk
        assert any(c.appr_asp == "sig_appr" and c.passed for c in report.components)


def test_hand_edited_golden_detected_and_attributed():
    """Laundering without re-provisioning: golden_b64 edited in asp_args.
    The bundle is intact (signature OK) but the anchor check names the
    edited target."""
    proto = _load("temp_control_lean_l2")
    targ = "temp_control_lean_spec_fanOn_when_hot_targ"
    proto.asp_args["readfile_range"][targ]["golden_b64"] = \
        "dGFtcGVyZWQgdGhlb3JlbSBzdGF0ZW1lbnQ="
    report = verify_bundle(_client(), proto, GOLDEN_ROOT)
    assert not report
    assert report.signature_ok  # the bundle itself is untouched
    assert any(targ in p and "does not match signed evidence" in p
               for p in report.problems)
    # every other golden still anchors
    assert len(report.anchored) == 14


def test_tampered_bundle_fails_signature():
    """A flipped evidence byte in the stored bundle breaks the RSA
    signature over the flattened evidence."""
    bundle = GOLDEN_ROOT / "_bundles" / "temp_control_lean_l1a" / "provision_bundle.json"
    orig = bundle.read_text()
    payload, ctx = json.loads(orig)
    ev = payload[0]["RawEv"]
    ev[2] = ("A" if ev[2][0] != "A" else "B") + ev[2][1:]  # not the signature slot
    bundle.write_text(json.dumps([payload, ctx]))
    try:
        report = verify_bundle(_client(), _load("temp_control_lean_l1a"), GOLDEN_ROOT)
        assert not report
        assert not report.signature_ok
        assert any("signature verification FAILED" in p for p in report.problems)
    finally:
        bundle.write_text(orig)
    assert verify_bundle(_client(), _load("temp_control_lean_l1a"), GOLDEN_ROOT)


def test_missing_bundle_is_a_problem():
    proto = _load("temp_control_lean_l1a").model_copy(update={"protocol_id": "no_such_protocol"})
    report = verify_bundle(_client(), proto, GOLDEN_ROOT)
    assert not report
    assert any("no provision bundle" in p for p in report.problems)


def test_target_map_drift_requires_reprovisioning():
    """A target added since the bundle was signed is not covered by the
    signed evidence — verification demands re-provisioning rather than
    silently attesting an unanchored golden."""
    proto = _load("temp_control_lean_l1a")
    proto.asp_args["hashfile"]["lean_new_file_targ"] = {
        "filepath": str(REPO / "targets/temp-control-lean/lakefile.toml"),
        "env_var": "", "golden_b64": "AAAA"}
    report = verify_bundle(_client(), proto, GOLDEN_ROOT)
    assert not report
    assert any("lean_new_file_targ" in p and "not covered" in p
               for p in report.problems)


# ── readiness integration ─────────────────────────────────────────────────────

def test_readiness_verifies_signed_baselines():
    from pybb.attestation import make_readiness_predicate, readiness_request

    protocols = {pid: _load(pid)
                 for pid in ("temp_control_lean_l1a", "temp_control_lean_l2", "temp_control_lean_check", "temp_control_lean_exec")}
    predicate = make_readiness_predicate(protocols, baseline_root=GOLDEN_ROOT,
                                         client=_client())
    report = predicate(readiness_request(list(protocols)))
    assert report, (report.problems, report.baseline_problems)
    # every golden-bearing protocol verified — including the tiers, whose
    # woven tool measurements carry measure-in-place hash goldens
    assert report.baseline_verified == ["temp_control_lean_l1a", "temp_control_lean_l2",
                                        "temp_control_lean_check", "temp_control_lean_exec"]


def test_readiness_reports_baseline_integrity_as_distinct_category():
    from pybb.attestation import make_readiness_predicate, readiness_request

    protocols = {"temp_control_lean_l2": _load("temp_control_lean_l2")}
    protocols["temp_control_lean_l2"].asp_args["readfile_range"][
        "temp_control_lean_spec_fanOn_when_hot_targ"]["golden_b64"] = "Zm9yZ2Vk"
    predicate = make_readiness_predicate(protocols, baseline_root=GOLDEN_ROOT,
                                         client=_client())
    report = predicate(readiness_request(["temp_control_lean_l2"]))
    assert not report
    assert not report.problems  # config is fine — this is a BASELINE failure
    assert any("temp_control_lean_spec_fanOn_when_hot_targ" in p
               for p in report.baseline_problems)


def test_readiness_without_baseline_root_unchanged():
    from pybb.attestation import make_readiness_predicate, readiness_request

    protocols = {"temp_control_lean_l1a": _load("temp_control_lean_l1a")}
    report = make_readiness_predicate(protocols)(readiness_request(["temp_control_lean_l1a"]))
    assert report
    assert report.baseline_verified == []
