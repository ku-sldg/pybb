"""
The cheat tier (scene 9): protocol shape of the checked-in
isolette_sysmlv2_rust_cheat fixture, and the tamper site the demo's
--tamper-cheat arc depends on. No CVM needed.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
CHEAT_DIR = FIXTURES / "isolette_sysmlv2_rust_cheat"

sys.path.insert(0, str(REPO / "examples"))
import isolette_rust as example  # noqa: E402


def test_cheat_protocol_fixture_shape():
    asp_args = json.loads((CHEAT_DIR / "asp_args.json").read_text())
    targets = asp_args["cheat_scan_verus"]
    # 7 report-derived contract-bearing crates + the report-invisible
    # extras (system proof crate, shared foundation crates)
    assert len(targets) == 10
    crates = {Path(a["crate_dir"]).name for a in targets.values()}
    assert {"sys_nominal_proof", "data", "GUMBO_Library"} <= crates
    for targ, args in targets.items():
        assert Path(args["crate_dir"]).name in targ
        assert "filepath" not in args  # measure-in-place: never re-rooted

    session = json.loads((CHEAT_DIR / "session.json").read_text())
    comps = session["Session_Context"]["ASP_Comps"]
    assert comps["cheat_scan_verus"] == "goldenbytes_appr"  # exact golden bytes
    assert comps["sig"] == "sig_appr"  # bundle evidence must be signed

    term_json = json.dumps(json.loads((CHEAT_DIR / "term.json").read_text()))
    assert '"SIG"' in term_json and '"APPR"' in term_json

    manifest = json.loads((CHEAT_DIR / "manifest.json").read_text())
    assert set(manifest["ASPS"]) == {"cheat_scan_verus", "goldenbytes_appr",
                                     "sig", "sig_appr"}


def test_uninterp_is_a_scanned_category():
    asp_args = json.loads((CHEAT_DIR / "asp_args.json").read_text())
    import base64
    sys_t = next(t for t, a in asp_args["cheat_scan_verus"].items()
                 if "sys_nominal_proof" in a["crate_dir"])
    ev = json.loads(base64.b64decode(
        asp_args["cheat_scan_verus"][sys_t]["golden_b64"]))
    # the system proof crate's blessed baseline: 26 uninterp action fns,
    # every other escape class zero
    assert ev["uninterp"] == 26
    assert ev["assume"] == 0 and ev["admit"] == 0 and ev["axiom"] == 0


def test_sysproof_protocol_covers_the_proof_crate():
    import base64
    d = FIXTURES / "isolette_sysmlv2_rust_sysproof"
    asp_args = json.loads((d / "asp_args.json").read_text())
    # ONE batched target: 124 per-file hashfile nodes made a 123-deep
    # bseq chain with superlinear CVM cost (~30s/pass); hashfile_many
    # hashes the same files into a single canonical relpath->sha256 map
    targets = asp_args["hashfile_many"]
    assert len(targets) == 1
    args = next(iter(targets.values()))
    assert args["root"].endswith("crates/sys_nominal_proof")
    assert set(args["files"]) == {"Cargo.toml", "rust-toolchain.toml"}
    assert args["walk_dirs"] == ["src"]
    # the provisioned golden covers every proof source, keyed by relpath
    golden = json.loads(base64.b64decode(args["golden_b64"]))
    assert "src/lib.rs" in golden
    assert "src/actions.rs" in golden
    assert "src/normal_display_temp/vc_sequential.rs" in golden
    assert "Cargo.toml" in golden and len(golden) >= 120
    # goldened with per-file attribution, signed
    session = json.loads((d / "session.json").read_text())
    comps = session["Session_Context"]["ASP_Comps"]
    assert comps["hashfile_many"] == "hashfile_many_appr"
    assert comps["sig"] == "sig_appr"
    # single node, no bseq chain in the term
    term = (d / "term.json").read_text()
    assert "bseq" not in term and '"SIG"' in term and '"APPR"' in term
    # the report never names the proof crate: no overlap with l1a's files
    l1a = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_l1a" / "asp_args.json").read_text())
    assert not any("sys_nominal_proof" in a["filepath"]
                   for a in l1a["hashfile"].values())


def test_verus_tier_goldens_the_verified_count():
    v = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_verus" / "asp_args.json").read_text())
    import base64
    sys_t = next(t for t, a in v["run_command_cargo_verus"].items()
                 if "sys_nominal_proof" in a["cwd"])
    args = v["run_command_cargo_verus"][sys_t]
    assert "--time" not in args["exe_args"]  # timings dropped for determinism
    results = json.loads(base64.b64decode(args["golden_b64"]))["verification-results"]
    assert results["verified"] == 1862 and results["errors"] == 0
    # count is pinned by exact golden bytes, not just errors==0
    session = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_verus" / "session.json").read_text())
    assert session["Session_Context"]["ASP_Comps"]["run_command_cargo_verus"] \
        == "goldenbytes_appr"


def test_tamper_cheat_site_is_present_and_clean():
    src = example.MHS_API.read_text()
    assert src.count(example.CHEAT_MARKER) == 1  # unique injection point
    assert example.CHEAT_LINE not in src  # tree starts honest
    # the beat depends on the site being unmeasured by the hash tier
    l1a = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_l1a" / "asp_args.json").read_text())
    hashed = {a["filepath"] for a in l1a["hashfile"].values()}
    assert str(example.MHS_API) not in hashed
