"""
The gensrc tier (scenes 9/11/12): fixture shape, the byte-coverage
completeness invariant, the l1a-exclusion discipline, and the tamper
site the demo's --tamper-ffi arc depends on. No CVM needed.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
GENSRC_DIR = FIXTURES / "isolette_sysmlv2_rust_gensrc"

sys.path.insert(0, str(REPO / "examples"))
import isolette_rust as example  # noqa: E402

FE = example.FRONTENDS["sysml"]


def test_gensrc_protocol_fixture_shape():
    asp_args = json.loads((GENSRC_DIR / "asp_args.json").read_text())
    targets = asp_args["hashfile_many"]
    # 7 report-derived component crates + the 2 foundation dep crates
    assert len(targets) == 9
    crates = {Path(a["root"]).name for a in targets.values()}
    assert set(example.DEP_CRATES) <= crates
    assert example.SYS_PROOF_CRATE not in crates  # sysproof owns it
    for targ, args in targets.items():
        assert Path(args["root"]).name in targ
        assert args["walk_dirs"] == ["src"]
        assert "filepath" not in args  # measure-in-place: never re-rooted

    session = json.loads((GENSRC_DIR / "session.json").read_text())
    comps = session["Session_Context"]["ASP_Comps"]
    assert comps["hashfile_many"] == "hashfile_many_appr"
    assert comps["sig"] == "sig_appr"  # bundle evidence must be signed


def test_gensrc_exclusions_match_l1a_exactly():
    """The exclusion lists must be precisely the l1a-covered files in
    each crate — no more (a file no tier measures) and no less (a
    developer-owned file double-covered by a no-benign-drift tier,
    which would break the scene 4/5 slice-rescue semantics)."""
    asp_args = json.loads((GENSRC_DIR / "asp_args.json").read_text())
    excluded = {Path(a["root"]).name: sorted(a.get("exclude", []))
                for a in asp_args["hashfile_many"].values()}
    l1a = example._l1a_files_by_crate(FE)
    for crate, rels in excluded.items():
        assert rels == l1a.get(crate, []), crate
    # every l1a crate-file is excluded somewhere
    assert set(l1a) <= set(excluded)


def test_coverage_invariant_passes_on_clean_tree():
    example.check_gensrc_coverage(FE)  # raises SystemExit on a hole


def test_executable_class_matches_reality():
    """The named executable-class crates are exactly the crates the
    verus tier does not verify and no byte tier covers."""
    crates_root = example.ISL_ROOT / "hamr" / "microkit" / "crates"
    all_crates = {p.name for p in crates_root.iterdir() if p.is_dir()}
    covered = (set(example._gensrc_crates(FE))
               | {example.SYS_PROOF_CRATE})
    assert all_crates - covered == set(example.GENSRC_EXECUTABLE_CLASS)


def test_tamper_ffi_site_is_present_and_clean():
    src = example.MHS_EXTERN.read_text()
    assert src.count(example.FFI_MARKER) == 1  # unique injection point
    assert "TAMPERED" not in src  # tree starts honest
    # the beat depends on the glue being covered by gensrc but by no
    # report-derived tier
    l1a = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_l1a" / "asp_args.json").read_text())
    assert not any(a["filepath"].endswith("extern_c_api.rs")
                   for a in l1a["hashfile"].values())
    mhs = next(a for a in json.loads(
        (GENSRC_DIR / "asp_args.json").read_text())["hashfile_many"].values()
        if Path(a["root"]).name == "thermostat_rt_mhs_mhs")
    assert "src/bridge/extern_c_api.rs" not in mhs.get("exclude", [])
