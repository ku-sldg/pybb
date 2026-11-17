"""Slot layout over appraisal output with EXTEND companions, on the real
temp_control_rocq_verification packages (captured from the CVM on
2026-11-17 while running the Rocq scenario under the ledger).

The Rocq verification protocol appraises run_command_dune / run_command_rocq
with run_command_rocq_appr, an EXTEND companion that keeps the judged
event's bytes (its output and the tool hashes beneath it) under its verdict,
while the judged event's sub-evidence is appraised again as a sibling. The
first layout counted both and saw 52 slots in a 30-slot package."""

import json
from pathlib import Path

from pybb.attestation import ProtocolDir
from pybb.attestation.ledger import APPRAISER_NONCE_TARGID, describe_package, slot_layout
from pybb.attestation.ledger_runs import appraisal_branch, components_from_layout, ledger_protocol

FIXTURES = Path(__file__).parent / "fixtures"
RAW = json.loads((FIXTURES / "ledger/rocq_verification_measurement.response.json").read_text())["PAYLOAD"]
APPR = json.loads((FIXTURES / "ledger/rocq_verification_appraisal.response.json").read_text())["PAYLOAD"]
PROTO = ProtocolDir.load(str(FIXTURES / "temp_control_rocq_verification"))
SESSION = ledger_protocol(PROTO).session


def test_raw_package_with_tool_measurements_lays_out():
    d = describe_package(RAW, SESSION)
    assert d.rawev_count == 17 and d.assurance == "signed+nonce" and d.nonce.slot == 1
    asps = [s.asp for s in d.spans]
    assert asps[:2] == ["sig", "generate_nonce"]
    assert asps.count("hashfile") == 13 and "run_command_dune" in asps and "run_command_rocq" in asps


def test_extend_companions_keep_the_judged_bytes_once():
    d = describe_package(APPR, SESSION, nonce_targid=APPRAISER_NONCE_TARGID)
    assert d.rawev_count == 30 and sum(s.count for s in d.spans) == 30
    spans = slot_layout(APPR[1], SESSION)
    companions = [s for s in spans if s.companion]
    retained = [s for s in spans if s.retained]
    assert [s.asp for s in companions].count("run_command_rocq_appr") == 2
    assert [s.asp for s in companions].count("goldenbytes_appr") == 13  # audit file + 3x4 tool hashes
    assert [(s.asp, s.count) for s in retained] == [("run_command_dune", 5), ("run_command_rocq", 5)]
    # an EXTEND companion's verdict is followed by the judged event's bytes
    rca = [s for s in companions if s.asp == "run_command_rocq_appr"]
    for c, r in zip(rca, retained):
        assert r.start == c.start + c.count


def test_appraisal_branch_and_layout_reading_agree_on_the_rocq_shape():
    branch = appraisal_branch(APPR, SESSION)
    assert len(branch["PAYLOAD"][0]["RawEv"]) == 27  # 30 minus sig, appraiser nonce, binding
    comps = components_from_layout(branch["PAYLOAD"], SESSION)
    assert len(comps) == 17
    kinds = {}
    for c in comps:
        kinds[c.appr_asp] = kinds.get(c.appr_asp, 0) + 1
    assert kinds == {"sig_appr": 1, "nonce_appr": 1, "goldenbytes_appr": 13, "run_command_rocq_appr": 2}
    assert all(c.passed for c in comps)
    by_target = {c.targ_id: c.target_asp for c in comps if c.appr_asp == "run_command_rocq_appr"}
    assert by_target == {"temp_control_rocq_build_verification_targ": "run_command_dune",
                         "temp_control_rocq_assumptions_verification_targ": "run_command_rocq"}
