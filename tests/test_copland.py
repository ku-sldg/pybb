"""Round-trip and term-utility tests against the real gumbo protocol files."""

import json

from pybb.attestation.copland import (
    ProtocolRunRequest,
    inject_asp_args,
    iter_aspc_bodies,
    normalize_term,
)
from pybb.attestation.client import ProtocolDir


def test_gumbo_l1a_request_round_trip(gumbo_l1a_request):
    model = ProtocolRunRequest.model_validate(gumbo_l1a_request)
    dumped = json.loads(model.model_dump_json(exclude_none=True))
    assert dumped == gumbo_l1a_request


def test_iter_aspc_bodies_counts(gumbo_l1a_dir, gumbo_l1b_dir, gumbo_l2_dir):
    l1a_term = json.loads((gumbo_l1a_dir / "term.json").read_text())
    l1b_term = json.loads((gumbo_l1b_dir / "term.json").read_text())
    l2_term = json.loads((gumbo_l2_dir / "term.json").read_text())
    assert len(list(iter_aspc_bodies(l1a_term))) == 4
    assert len(list(iter_aspc_bodies(l1b_term))) == 6
    assert len(list(iter_aspc_bodies(l2_term))) == 22


def test_inject_asp_args_by_targ_id(gumbo_l2_dir):
    term = json.loads((gumbo_l2_dir / "term.json").read_text())
    asp_args = json.loads((gumbo_l2_dir / "asp_args.json").read_text())
    injected = inject_asp_args(term, asp_args)
    bodies = list(iter_aspc_bodies(injected))
    assert all("golden_b64" in (b.get("ASP_ARGS") or {}) for b in bodies)
    # original untouched
    assert all("ASP_ARGS" not in b for b in iter_aspc_bodies(term))


def test_inject_asp_args_legacy_filepath_match(gumbo_l1a_dir):
    term = json.loads((gumbo_l1a_dir / "term.json").read_text())
    asp_args = json.loads((gumbo_l1a_dir / "asp_args.json").read_text())
    injected = inject_asp_args(term, asp_args)
    assert all(
        "golden_b64" in (b.get("ASP_ARGS") or {}) for b in iter_aspc_bodies(injected)
    )


def test_normalize_term_strips_targ_ids(gumbo_l2_dir):
    term = json.loads((gumbo_l2_dir / "term.json").read_text())
    asp_args = json.loads((gumbo_l2_dir / "asp_args.json").read_text())
    normalized = normalize_term(inject_asp_args(term, asp_args))
    for body in iter_aspc_bodies(normalized):
        assert set(body.keys()) <= {"ASP_ID", "ASP_ARGS"}


def test_protocol_dir_build_request_dynamic(gumbo_l2_dir):
    proto = ProtocolDir.load(str(gumbo_l2_dir))
    assert proto.prebuilt_request is None
    request = proto.build_request()
    assert request["TYPE"] == "REQUEST" and request["ACTION"] == "RUN"
    # a dynamic request must validate against the typed model
    ProtocolRunRequest.model_validate(request)
    bodies = list(iter_aspc_bodies(request["TERM"]))
    assert len(bodies) == 22
    assert all("golden_b64" in b["ASP_ARGS"] for b in bodies)


def test_protocol_dir_prebuilt_request_used_verbatim(gumbo_l1a_dir, gumbo_l1a_request):
    proto = ProtocolDir.load(str(gumbo_l1a_dir))
    assert proto.prebuilt_request is not None
    assert proto.build_request() == gumbo_l1a_request
