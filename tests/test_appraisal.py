"""Appraisal parsing over synthetic CVM responses."""

import base64

from pybb.attestation.appraisal import overall_verdict, parse_appraisal


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _asp_evt(asp_id: str, args: dict, sub=None):
    return {
        "EvidenceT_CONSTRUCTOR": "asp_evt",
        "EvidenceT_BODY": [
            "P0",
            {"ASP_ID": asp_id, "ASP_ARGS": args},
            sub or {"EvidenceT_CONSTRUCTOR": "mt_evt"},
        ],
    }


def _split(l, r):
    return {"EvidenceT_CONSTRUCTOR": "split_evt", "EvidenceT_BODY": [l, r]}


def _response(et, raw_ev, success=True):
    return {
        "TYPE": "RESPONSE",
        "ACTION": "RUN",
        "SUCCESS": success,
        "PAYLOAD": [{"RawEv": raw_ev}, et],
    }


ARGS_A = {"filepath": "/x/TempSensor.aadl"}
ARGS_B = {"filepath": "/x/TempControlSystem.aadl", "start_index": 305, "end_index": 308}


def test_single_pass():
    et = _asp_evt("hashfile_appr", ARGS_A, sub=_asp_evt("hashfile", ARGS_A))
    results = parse_appraisal(_response(et, [_b64("")]))
    assert len(results) == 1
    assert results[0].passed and results[0].appr_asp == "hashfile_appr"
    assert results[0].target_asp == "hashfile"
    assert results[0].description == "TempSensor.aadl"
    assert overall_verdict(results)


def test_fail_with_reason_and_dfs_order():
    et = _split(
        _asp_evt("hashfile_appr", ARGS_A, sub=_asp_evt("hashfile", ARGS_A)),
        _asp_evt("goldenbytes_appr", ARGS_B, sub=_asp_evt("readfile_range", ARGS_B)),
    )
    results = parse_appraisal(_response(et, [_b64(""), _b64("hash mismatch")]))
    assert [r.passed for r in results] == [True, False]
    assert results[1].reason == "hash mismatch"
    assert results[1].description == "TempControlSystem.aadl:305-308"
    assert not overall_verdict(results)


def test_targ_id_matching():
    records = [
        {"asp_id": "readfile_range", "targ_id": "tc_sys_aadl_305_308_targ", "args": ARGS_B}
    ]
    et = _asp_evt("goldenbytes_appr", ARGS_B, sub=_asp_evt("readfile_range", ARGS_B))
    results = parse_appraisal(_response(et, [_b64("")]), records)
    assert results[0].targ_id == "tc_sys_aadl_305_308_targ"


def test_failed_run_yields_no_components():
    assert parse_appraisal(_response({}, [], success=False)) == []
    assert not overall_verdict([])


def test_non_appraiser_nodes_recursed_not_counted():
    et = _asp_evt(
        "sig",
        {},
        sub=_asp_evt("hashfile_appr", ARGS_A, sub=_asp_evt("hashfile", ARGS_A)),
    )
    results = parse_appraisal(_response(et, [_b64("")]))
    assert len(results) == 1 and results[0].appr_asp == "hashfile_appr"
