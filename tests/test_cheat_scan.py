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
    assert len(targets) == 7  # the report-derived contract-bearing crates
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


def test_tamper_cheat_site_is_present_and_clean():
    src = example.MHS_API.read_text()
    assert src.count(example.CHEAT_MARKER) == 1  # unique injection point
    assert example.CHEAT_LINE not in src  # tree starts honest
    # the beat depends on the site being unmeasured by the hash tier
    l1a = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_l1a" / "asp_args.json").read_text())
    hashed = {a["filepath"] for a in l1a["hashfile"].values()}
    assert str(example.MHS_API) not in hashed
