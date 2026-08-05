"""
The verified appraisal summary as pybb's response interpreter: parity
with the legacy parser on REPLACE shapes, retained-evidence lift on
EXTEND shapes, fail-closed refusal of non-evidence, and audit replay of
archived responses. Auto-skipped without the CVM stack or the
copland-evidence-tools binary.
"""

import gzip
import json
from pathlib import Path

import pytest

from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    attestation_request,
    make_attestation_predicate,
    parse_appraisal,
)
from pybb.attestation import summarizer
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
        reason="requires local CVM binary and asp-libs binaries",
    ),
    pytest.mark.skipif(not summarizer.available(),
                       reason="requires copland-evidence-tools binary"),
]


def _run(pid: str):
    proto = ProtocolDir.load(str(FIXTURES / pid))
    return proto, CvmSubprocessClient().run_protocol(proto)


def test_replace_shape_parity_with_legacy_parser():
    """On a plain REPLACE protocol the verified summary and the legacy
    walker must agree on every verdict and attribution."""
    proto, resp = _run("temp_control_lean_l1a")
    verified = summarizer.summarize_response(resp, proto.session)
    legacy = parse_appraisal(resp, proto.target_records())
    assert [(c.targ_id, c.passed) for c in verified] == \
        [(c.targ_id, c.passed) for c in legacy]
    assert len(verified) == 7  # 6 hash verdicts + sig


def test_extend_shape_lifts_retained_evidence():
    proto, resp = _run("temp_control_lean_exec")
    comps = summarizer.summarize_response(resp, proto.session)
    runs = {c.targ_id: c for c in comps
            if c.appr_asp == "run_command_lean_appr"}
    import base64
    assert base64.b64decode(runs["temp_control_lean_exec_hot_targ"].measured_b64) == \
        b"fanCmd=On\n"
    assert base64.b64decode(runs["temp_control_lean_exec_cold_targ"].measured_b64) == \
        b"fanCmd=Off\n"
    # every entry attributed or legitimately targless (sig)
    assert all(c.targ_id or c.appr_asp == "sig_appr" for c in comps)


def test_summarizer_refuses_fabricated_evidence():
    proto = ProtocolDir.load(str(FIXTURES / "temp_control_lean_l1a"))
    fake = {"SUCCESS": True, "PAYLOAD": [{"RawEv": ["", ""]},
            {"EvidenceT_CONSTRUCTOR": "mt_evt"}]}
    with pytest.raises(summarizer.SummaryError):
        summarizer.summarize_response(fake, proto.session)


def test_archived_response_replays_to_the_same_verdicts(tmp_path):
    """The episode archive is a durable evidence artifact: gunzip and
    re-summarize years later, get the same per-target verdicts."""
    proto = ProtocolDir.load(str(FIXTURES / "temp_control_lean_l1a"))
    predicate = make_attestation_predicate(
        CvmSubprocessClient(), {"temp_control_lean_l1a": proto}, archive_dir=tmp_path)
    verdict = predicate(attestation_request("temp_control_lean_l1a"))
    assert verdict.passed and verdict.evidence_ref
    with gzip.open(verdict.evidence_ref, "rt") as f:
        archived = json.load(f)
    replayed = summarizer.summarize_response(archived, proto.session)
    assert [(c.targ_id, c.passed) for c in replayed] == \
        [(c.targ_id, c.passed) for c in verdict.components]
