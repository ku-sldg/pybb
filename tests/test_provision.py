"""
Provisioning predicate behavior with a scripted fake client and extractor
(no CVM needed): term shaping, golden re-rooting, golden installation,
memoization, and the error paths.
"""

import json
from pathlib import Path

from pybb import BlackboardController
from pybb.attestation import (
    ProtocolDir,
    make_provision_predicate,
    provision_request,
    request_provision,
)
from pybb.attestation.client import AttestationClient
from pybb.attestation.copland import iter_aspc_bodies
from pybb.attestation.snapshot import mirror_path

_SIG = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "SIG"}}
_APPR = {"TERM_CONSTRUCTOR": "asp", "TERM_BODY": {"ASP_CONSTRUCTOR": "APPR"}}


def _aspc(asp_id: str, targ_id: str) -> dict:
    return {
        "TERM_CONSTRUCTOR": "asp",
        "TERM_BODY": {
            "ASP_CONSTRUCTOR": "ASPC",
            "ASP_BODY": {"ASP_ID": asp_id, "ASP_TARG_ID": targ_id},
        },
    }


_RESPONSE = {
    "TYPE": "RESPONSE", "ACTION": "RUN", "SUCCESS": True,
    "PAYLOAD": [{"RawEv": ["aGFzaA=="]}, {"EvidenceT_CONSTRUCTOR": "mt_evt"}],
}


class FakeClient(AttestationClient):
    def __init__(self, response=_RESPONSE):
        self.response = response
        self.requests: list[dict] = []

    def run_protocol(self, protocol: ProtocolDir) -> dict:
        self.requests.append(protocol.build_request())
        result = self.response
        if isinstance(result, Exception):
            raise result
        return result


def _protocol(tmp_path, live_file, appraiser="goldenbytes_appr") -> ProtocolDir:
    term = {"TERM_CONSTRUCTOR": "lseq", "TERM_BODY": [
        {"TERM_CONSTRUCTOR": "lseq",
         "TERM_BODY": [_aspc("hashfile", "t1"), _SIG]},
        _APPR,
    ]}
    session = {
        "Session_Plc": "P0",
        "Session_Context": {
            "ASP_Types": {"hashfile": {"FWD": {"FWD": "EXTEND", "_BODY": 1}, "ATTRS": []}},
            "ASP_Comps": {"hashfile": appraiser, "sig": "sig_appr"},
        },
    }
    asp_args = {"hashfile": {"t1": {
        "filepath": str(live_file), "env_var": "",
        "golden_b64": "OLD", "golden_ts": "2026-01-01 00:00:00",
    }}}
    proto_dir = tmp_path / "protos" / "p1"
    proto_dir.mkdir(parents=True)
    (proto_dir / "asp_args.json").write_text(json.dumps(asp_args))
    (proto_dir / "cvm_request.json").write_text("{}")  # stale prebuilt
    return ProtocolDir(protocol_id="p1", path=str(proto_dir), term=term,
                       session=session, manifest={"ASPS": []},
                       asp_args=asp_args, prebuilt_request={})


def _setup(tmp_path, with_golden=True, appraiser="goldenbytes_appr"):
    live = tmp_path / "live" / "target.txt"
    live.parent.mkdir(parents=True)
    live.write_text("content")
    golden_root = tmp_path / "golden"
    if with_golden:
        copy = mirror_path(golden_root, live)
        copy.parent.mkdir(parents=True)
        copy.write_text("content")
    protocol = _protocol(tmp_path, live, appraiser=appraiser)
    client = FakeClient()
    predicate = make_provision_predicate(
        client, {"p1": protocol}, golden_root,
        extract_fn=lambda d, a, t: "FRESH",
    )
    return predicate, client, protocol, golden_root, live


def test_success_installs_fresh_goldens_everywhere(tmp_path):
    predicate, client, protocol, golden_root, live = _setup(tmp_path)

    outcome = predicate(provision_request("p1"))

    assert outcome and outcome.provisioned == ["t1"]
    # in-memory protocol: fresh golden, stale prebuilt dropped
    args = protocol.asp_args["hashfile"]["t1"]
    assert args["golden_b64"] == "FRESH" and args["golden_ts"] != "2026-01-01 00:00:00"
    assert protocol.prebuilt_request is None
    # on disk: asp_args rewritten, stale cvm_request.json removed
    on_disk = json.loads((Path(protocol.path) / "asp_args.json").read_text())
    assert on_disk["hashfile"]["t1"]["golden_b64"] == "FRESH"
    assert not (Path(protocol.path) / "cvm_request.json").exists()
    # golden evidence bundle written under the golden root
    bundle_dir = golden_root / "_bundles" / "p1"
    bundle = json.loads((bundle_dir / "provision_bundle.json").read_text())
    assert bundle[0] == _RESPONSE["PAYLOAD"] and "ASP_Comps" in bundle[1]
    match_args = json.loads((bundle_dir / "asp_args.json").read_text())
    assert match_args["hashfile"]["t1"]["filepath"] == str(mirror_path(golden_root, live))
    assert "golden_b64" not in match_args["hashfile"]["t1"]


def test_provisioning_term_is_measurement_only_and_golden_rooted(tmp_path):
    predicate, client, protocol, golden_root, live = _setup(tmp_path)

    predicate(provision_request("p1"))

    request = client.requests[0]
    term_json = json.dumps(request["TERM"])
    assert '"APPR"' not in term_json  # appraisal stripped: run cannot fail on missing goldens
    bodies = list(iter_aspc_bodies(request["TERM"]))
    assert len(bodies) == 1
    args = bodies[0]["ASP_ARGS"]
    assert args["filepath"] == str(mirror_path(golden_root, live))  # measures golden copy
    assert args["asp_id_appr"] == "hashfile"
    assert "golden_b64" not in args and "golden_ts" not in args


def test_missing_golden_copy_fails_without_running(tmp_path):
    predicate, client, protocol, _, live = _setup(tmp_path, with_golden=False)

    outcome = predicate(provision_request("p1"))

    assert not outcome and str(live) in outcome.error
    assert client.requests == []  # never reached the CVM
    assert protocol.asp_args["hashfile"]["t1"]["golden_b64"] == "OLD"  # untouched


def test_non_goldenbytes_protocol_is_not_provisionable(tmp_path):
    predicate, client, *_ = _setup(tmp_path, appraiser="hashfile_appr")
    outcome = predicate(provision_request("p1"))
    assert not outcome and "no goldenbytes_appr" in outcome.error
    assert client.requests == []


def test_unknown_protocol_fails_cleanly(tmp_path):
    predicate, *_ = _setup(tmp_path)
    outcome = predicate(provision_request("nope"))
    assert not outcome and "unknown protocol" in outcome.error


def test_memoized_per_lifetime(tmp_path):
    predicate, client, *_ = _setup(tmp_path)
    first = predicate(provision_request("p1"))
    again = predicate(provision_request("p1"))
    assert first is again and len(client.requests) == 1


def test_full_blackboard_flow_success_and_failure(tmp_path):
    predicate, client, protocol, golden_root, live = _setup(tmp_path)
    ctl = BlackboardController()
    ctl.register_predicate("provision", predicate)
    request_provision(ctl.blackboard, "p1")
    request_provision(ctl.blackboard, "unknown_proto")

    bb = ctl.run()

    good = bb.provision["provision:p1"]
    assert good.good_standing and good.result.provisioned == ["t1"]
    bad = bb.escalate["provision:unknown_proto"]
    assert not bad.good_standing and "unknown protocol" in bad.result.error
