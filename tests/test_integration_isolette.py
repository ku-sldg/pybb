"""
Isolette example end-to-end: the INSPECTA seL4/Microkit exemplar, vendored
at targets/isolette-microkit with its HAMR attestation report as the
authoritative source of targets and golden slices (isl_l1a/isl_l2/isl_verus
are generated from it, never hand-curated). Readiness verifies the SIGNED
golden baseline bundles before any attestation; a tampered Verus contract
slice is detected, attributed, whole-file repaired from golden, and
verified clean by the next episode.

Auto-skipped unless the CVM binary and asp-libs are present. The Verus
tier is gated behind RUN_VERUS=1 (multi-minute cold builds).
"""

import os
from pathlib import Path

import pytest

from pybb import BlackboardController
from pybb.attestation import (
    CvmSubprocessClient,
    ProtocolDir,
    TargetSnapshot,
    TierKS,
    WholeFileRestoreKS,
    attestation_request,
    make_attestation_predicate,
    make_readiness_predicate,
    readiness_request,
    trust_summary,
    verify_bundle,
)
from pybb.attestation.client import DEFAULT_ASP_BIN, DEFAULT_CVM_BINARY
from pybb.attestation.targetmap import derive_targets_from_report, report_slices

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_ROOT = REPO / "golden"
ISL_ROOT = REPO / "targets" / "isolette-microkit"
REPORT = ISL_ROOT / "hamr" / "microkit" / "attestation" / "aadl_attestation_report.json"
PROTOCOL_IDS = ("isl_l1a", "isl_l2")

pytestmark = [
    pytest.mark.cvm,
    pytest.mark.skipif(
        not (Path(DEFAULT_CVM_BINARY).is_file() and Path(DEFAULT_ASP_BIN).is_dir()),
        reason="requires local CVM binary and asp-libs binaries",
    ),
]

needs_verus = pytest.mark.skipif(
    os.environ.get("RUN_VERUS") != "1",
    reason="set RUN_VERUS=1 to run the multi-minute Verus tier")


def _protocols(*extra: str) -> dict:
    return {pid: ProtocolDir.load(str(FIXTURES / pid))
            for pid in (*PROTOCOL_IDS, *extra)}


def test_committed_fixtures_derive_from_the_report():
    """The report is the authority: committed target maps must equal it."""
    derived = derive_targets_from_report(REPORT, prefix="isl")
    for pid in PROTOCOL_IDS:
        committed = ProtocolDir.load(str(FIXTURES / pid)).asp_args
        for asp_id, targets in derived[pid].items():
            assert set(committed[asp_id]) == set(targets), pid
            for targ_id, args in targets.items():
                c = committed[asp_id][targ_id]
                for k, v in args.items():
                    assert c[k] == v, f"{pid}/{targ_id}/{k} diverged from report"
    # the Verus tier's crate list is report-derived too
    crates = {s["filepath"].split("/crates/")[1].split("/")[0]
              for s in report_slices(REPORT)
              if s["kind"] in ("Verus", "Rust") and "/crates/" in s["filepath"]}
    verus = ProtocolDir.load(str(FIXTURES / "isl_verus")).asp_args
    committed_crates = {Path(a["cwd"]).name
                        for a in verus["run_command_cargo_verus"].values()}
    assert committed_crates == crates


def test_report_covers_model_and_generated_artifacts():
    kinds = {s["kind"] for s in report_slices(REPORT)}
    assert "Model" in kinds and "Verus" in kinds
    for s in report_slices(REPORT):
        assert Path(s["filepath"]).is_file(), s["filepath"]


def test_signed_baselines_verify():
    client = CvmSubprocessClient()
    for pid, n in (("isl_l1a", 13), ("isl_l2", 67)):
        report = verify_bundle(client, ProtocolDir.load(str(FIXTURES / pid)),
                               GOLDEN_ROOT)
        assert report, report.problems
        assert len(report.anchored) == n


@pytest.fixture
def live_snapshot():
    snapshot = TargetSnapshot.load(_protocols(), GOLDEN_ROOT)
    try:
        yield snapshot
    finally:
        snapshot.restore()


def _episode(repair: bool = True, validate: bool = False):
    protocols = _protocols(*(["isl_verus"] if validate else []))
    ctl = BlackboardController()
    client = CvmSubprocessClient()
    ctl.register_predicate(
        "attestation", make_attestation_predicate(client, protocols))
    ctl.register_predicate("protocol_check", make_readiness_predicate(
        protocols, baseline_root=GOLDEN_ROOT, client=client))
    chain = [TierKS(protocol_id="isl_l2")]
    if repair:
        chain.append(WholeFileRestoreKS(golden_root=GOLDEN_ROOT,
                                        refined_by="isl_l2"))
    confirm = [TierKS(protocol_id="isl_verus")] if validate else []
    for ks in (*confirm, *chain):
        ctl.add_ks(ks)
    ctl.blackboard.write_entry(key="isl:files", predicate="attestation",
                               measurement=attestation_request("isl_l1a"))
    ctl.route("isl:files", on_pass=confirm, on_fail=chain)
    ctl.blackboard.write_entry(key="isl:ready", predicate="protocol_check",
                               measurement=readiness_request(list(protocols)))
    ctl.route("isl:ready", on_pass=[], on_fail=[])
    ctl.run()
    return ctl.blackboard


def test_clean_attestation_with_verified_baseline():
    bb = _episode()
    ready = bb.get_entry("isl:ready")
    assert ready.good_standing
    assert ready.result.baseline_verified == ["isl_l1a", "isl_l2"]
    entry = bb.get_entry("isl:files")
    assert entry.good_standing and entry.result.protocol == "isl_l1a"
    assert len(entry.result.components) == 14  # 13 hashfile + sig
    assert "signed baselines verified (isl_l1a, isl_l2)" in trust_summary(bb)


def test_verus_slice_tamper_attributed_repaired_verified(live_snapshot):
    l2 = _protocols()["isl_l2"].asp_args["readfile_range"]
    targ, args = next((t, a) for t, a in sorted(l2.items())
                      if "thermostat_rt_mhs" in a["filepath"]
                      and a["filepath"].endswith(".rs"))
    rs = Path(args["filepath"])
    lines = rs.read_text().splitlines(keepends=True)
    lines[args["start_index"] - 1] = "// TAMPERED: verus contract weakened\n"
    rs.write_text("".join(lines))

    bb1 = _episode()

    escalated = bb1.escalate["isl:files"]
    assert escalated.ks_history == {"tier:isl_l2": 1, "repair:whole-file": 1}
    l2v = next(e.result for k, e in bb1.get_history()
               if k == "isl:files" and e.result is not None
               and e.result.protocol == "isl_l2")
    assert targ in {c.targ_id for c in l2v.failing()}
    from pybb.attestation.snapshot import mirror_path
    assert rs.read_bytes() == mirror_path(GOLDEN_ROOT, rs).read_bytes()

    bb2 = _episode()
    assert bb2.entries["isl:files"].good_standing
    assert not bb2.escalate


@needs_verus
def test_isl_l1a_pass_confirmed_by_verus():
    bb = _episode(repair=False, validate=True)
    entry = bb.get_entry("isl:files")
    assert entry is not None and entry.good_standing, entry
    assert entry.result.protocol == "isl_verus"
    crates = {c.targ_id for c in entry.result.components
              if c.targ_id and c.targ_id.startswith("isl_")
              and c.targ_id.endswith("_verus_targ")}
    assert len(crates) == 7  # every contract-bearing crate
    # the verus toolchain was measured in the same term, before the uses
    tools = {c.targ_id for c in entry.result.components
             if (c.args.get("metadata") or "").startswith("tool::cargo-verus")}
    assert len(tools) == 4
    assert "isl_l1a passed; confirmed by isl_verus" in \
        trust_summary(bb, semantic=["isl_verus"])


# ── signed golden spec (props): the administrator-blessed model files ─────────

def test_props_covers_every_model_file_with_blessed_content():
    from pybb.attestation.props import model_files_from_report

    committed = ProtocolDir.load(str(FIXTURES / "isl_props")).asp_args["readfile"]
    assert sorted(a["filepath"] for a in committed.values()) == \
        model_files_from_report(REPORT)
    for args in committed.values():
        assert args.get("golden_b64")  # blessed file content installed


def test_props_baseline_anchors_hashes_and_slices_not_vacuously():
    from pybb.attestation.baseline import _build_anchors

    protocols = _protocols("isl_props")
    # every blessed model file has BOTH a hash golden and Model slices to
    # anchor — the appraisal below is not a vacuous signature check
    anchors = _build_anchors(protocols)
    for args in protocols["isl_props"].asp_args["readfile"].values():
        assert anchors[args["filepath"]].get("hash_golden_b64")
        assert anchors[args["filepath"]]["slices"]
    report = verify_bundle(CvmSubprocessClient(), protocols["isl_props"],
                           GOLDEN_ROOT, anchor_protocols=protocols)
    assert report, report.problems
    assert len(report.anchored) == 5


def test_laundered_measurement_baselines_refuted_by_blessing():
    """THE scenario props exists for: tamper the golden tree and re-provision
    the measurement protocols — their baselines become self-consistently
    signed and verify — but the administrator's whole-file blessing (not
    re-provisioned) refutes: the laundered hash and slice goldens are not
    derivable from blessed content."""
    from pybb import BlackboardController
    from pybb.attestation import (make_provision_predicate,
                                  make_readiness_predicate, readiness_request,
                                  request_provision)

    pids = ["isl_l1a", "isl_l2", "isl_props"]
    protocols = {p: ProtocolDir.load(str(FIXTURES / p)) for p in pids}
    client = CvmSubprocessClient()

    l2 = protocols["isl_l2"].asp_args["readfile_range"]
    targ, args = next((t, a) for t, a in sorted(l2.items())
                      if a["filepath"].endswith(".aadl") and a.get("metadata"))
    gold = Path("golden" + args["filepath"])
    orig = gold.read_bytes()

    def reprovision():
        ctl = BlackboardController()
        sub = {p: protocols[p] for p in ("isl_l1a", "isl_l2")}
        ctl.register_predicate("provision",
                               make_provision_predicate(client, sub, GOLDEN_ROOT))
        for p in sub:
            request_provision(ctl.blackboard, p)
        bb = ctl.run()
        assert not bb.get_escalate(), bb.get_escalate()

    lines = gold.read_text().splitlines(keepends=True)
    lines[args["start_index"] - 1] = "      -- LAUNDERED: clause weakened\n"
    gold.write_text("".join(lines))
    try:
        reprovision()
        report = make_readiness_predicate(
            protocols, baseline_root=GOLDEN_ROOT,
            client=CvmSubprocessClient())(readiness_request(pids))
        assert not report
        # the laundered baselines are self-consistent and verify...
        assert report.baseline_verified == ["isl_l1a", "isl_l2"]
        # ...but the blessing refutes them, naming the file and the cause
        assert any("isl_props" in p and "not derivable from blessed content" in p
                   for p in report.baseline_problems)
    finally:
        gold.write_bytes(orig)
        reprovision()
    report = make_readiness_predicate(
        protocols, baseline_root=GOLDEN_ROOT,
        client=CvmSubprocessClient())(readiness_request(pids))
    assert report, (report.problems, report.baseline_problems)
