"""Round-trip and term-utility tests against the real gumbo protocol files."""

import json

from pybb.attestation.copland import (
    ProtocolRunRequest,
    inject_asp_args,
    iter_aspc_bodies,
    normalize_term,
)
from pybb.attestation.client import ProtocolDir


def test_temp_control_aadl_slang_l1a_request_round_trip(temp_control_aadl_slang_l1a_dir):
    request = ProtocolDir.load(str(temp_control_aadl_slang_l1a_dir)).build_request()
    model = ProtocolRunRequest.model_validate(request)
    dumped = json.loads(model.model_dump_json(exclude_none=True))
    assert dumped == request


def test_iter_aspc_bodies_counts(temp_control_aadl_slang_l1a_dir, temp_control_aadl_slang_l1b_dir, temp_control_aadl_slang_l2_dir):
    l1a_term = json.loads((temp_control_aadl_slang_l1a_dir / "term.json").read_text())
    l1b_term = json.loads((temp_control_aadl_slang_l1b_dir / "term.json").read_text())
    l2_term = json.loads((temp_control_aadl_slang_l2_dir / "term.json").read_text())
    assert len(list(iter_aspc_bodies(l1a_term))) == 4
    assert len(list(iter_aspc_bodies(l1b_term))) == 6
    assert len(list(iter_aspc_bodies(l2_term))) == 33


def test_inject_asp_args_by_targ_id(temp_control_aadl_slang_l2_dir):
    term = json.loads((temp_control_aadl_slang_l2_dir / "term.json").read_text())
    asp_args = json.loads((temp_control_aadl_slang_l2_dir / "asp_args.json").read_text())
    injected = inject_asp_args(term, asp_args)
    bodies = list(iter_aspc_bodies(injected))
    assert all("golden_b64" in (b.get("ASP_ARGS") or {}) for b in bodies)
    # original untouched
    assert all("ASP_ARGS" not in b for b in iter_aspc_bodies(term))


def test_inject_asp_args_legacy_filepath_match(temp_control_aadl_slang_l1a_dir):
    term = json.loads((temp_control_aadl_slang_l1a_dir / "term.json").read_text())
    asp_args = json.loads((temp_control_aadl_slang_l1a_dir / "asp_args.json").read_text())
    injected = inject_asp_args(term, asp_args)
    assert all(
        "golden_b64" in (b.get("ASP_ARGS") or {}) for b in iter_aspc_bodies(injected)
    )


def test_normalize_term_strips_targ_ids(temp_control_aadl_slang_l2_dir):
    term = json.loads((temp_control_aadl_slang_l2_dir / "term.json").read_text())
    asp_args = json.loads((temp_control_aadl_slang_l2_dir / "asp_args.json").read_text())
    normalized = normalize_term(inject_asp_args(term, asp_args))
    for body in iter_aspc_bodies(normalized):
        assert set(body.keys()) <= {"ASP_ID", "ASP_ARGS"}


def test_protocol_dir_build_request_dynamic(temp_control_aadl_slang_l2_dir):
    proto = ProtocolDir.load(str(temp_control_aadl_slang_l2_dir))
    assert proto.prebuilt_request is None
    request = proto.build_request()
    assert request["TYPE"] == "REQUEST" and request["ACTION"] == "RUN"
    # a dynamic request must validate against the typed model
    ProtocolRunRequest.model_validate(request)
    bodies = list(iter_aspc_bodies(request["TERM"]))
    assert len(bodies) == 33
    assert all("golden_b64" in b["ASP_ARGS"] for b in bodies)


def test_protocol_dir_prebuilt_request_used_verbatim(temp_control_aadl_slang_l1a_dir, tmp_path):
    import shutil
    copy = tmp_path / "p"
    shutil.copytree(temp_control_aadl_slang_l1a_dir, copy)
    prebuilt = {"TYPE": "REQUEST", "ACTION": "RUN", "MARKER": "prebuilt-wins"}
    (copy / "cvm_request.json").write_text(json.dumps(prebuilt))
    proto = ProtocolDir.load(str(copy))
    assert proto.prebuilt_request is not None
    assert proto.build_request() == prebuilt
