"""The l1b contract-integrity grid: per-crate rows from the marker
fixture, judged downgrade-only from the tier's verdict."""

from pybb.attestation.appraisal import ComponentResult
from pybb.attestation.knowledge_sources import Verdict
from pybb.attestation.marker_status import marker_crate_checklist
from pybb.attestation.proof_status import FAILING, PROVED, UNKNOWN, render_checklist

CRATES = "/x/hamr/microkit/crates"
TARGETS = {
    "mhs_ensures": {"filepath": f"{CRATES}/thermostat_rt_mhs_mhs/src/component/a.rs",
                    "begin_marker": "BEGIN MARKER TIME TRIGGERED ENSURES"},
    "mhs_requires": {"filepath": f"{CRATES}/thermostat_rt_mhs_mhs/src/component/a.rs",
                     "begin_marker": "BEGIN MARKER TIME TRIGGERED REQUIRES"},
    "mri_ensures": {"filepath": f"{CRATES}/thermostat_rt_mri_mri/src/component/b.rs",
                    "begin_marker": "BEGIN MARKER TIME TRIGGERED ENSURES"},
}


def _comp(targ, passed):
    return ComponentResult(appr_asp="a", target_asp="t", targ_id=targ,
                           passed=passed)


def _verdict(*components, error=""):
    return Verdict(protocol="l1b", passed=all(c.passed for c in components),
                   components=list(components), error=error)


def _by_label(checklist):
    return {r.label: r.status for r in checklist.rows}


def test_all_blocks_intact_is_per_crate_check():
    v = _verdict(_comp("mhs_ensures", True), _comp("mhs_requires", True),
                 _comp("mri_ensures", True))
    st = _by_label(marker_crate_checklist(v, TARGETS))
    assert set(st) == {"thermostat_rt_mhs_mhs", "thermostat_rt_mri_mri"}
    assert st["thermostat_rt_mhs_mhs"].state == PROVED
    assert "2 contract block(s) intact" in st["thermostat_rt_mhs_mhs"].detail


def test_one_drifted_block_refutes_its_crate_and_names_the_block():
    v = _verdict(_comp("mhs_ensures", False), _comp("mhs_requires", True),
                 _comp("mri_ensures", True))
    st = _by_label(marker_crate_checklist(v, TARGETS))
    assert st["thermostat_rt_mhs_mhs"].state == FAILING
    assert st["thermostat_rt_mhs_mhs"].detail == \
        "TIME TRIGGERED ENSURES drifted from golden"
    assert st["thermostat_rt_mri_mri"].state == PROVED
    out = render_checklist(marker_crate_checklist(v, TARGETS),
                           subject="contract slice integrity")
    assert "thermostat_rt_mhs_mhs  ✗" in out
    assert "thermostat_rt_mri_mri  ✓" in out


def test_protocol_error_and_missing_component_downgrade_to_unknown():
    st = _by_label(marker_crate_checklist(_verdict(error="boom"), TARGETS))
    assert all(s.state == UNKNOWN for s in st.values())
    v = _verdict(_comp("mhs_ensures", True), _comp("mri_ensures", True))
    st = _by_label(marker_crate_checklist(v, TARGETS))
    assert st["thermostat_rt_mhs_mhs"].state == UNKNOWN
    assert "TIME TRIGGERED REQUIRES" in st["thermostat_rt_mhs_mhs"].detail
    assert st["thermostat_rt_mri_mri"].state == PROVED
