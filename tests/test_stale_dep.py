"""
The stale-dependency arc (scene 11): the tamper site and the coverage
premises the demo's --tamper-stale-dep / --fresh-deps beats depend on,
plus the freshness guard's seed/check cycle. No CVM needed, and nothing
here bumps a live mtime — the warm caches stay coherent.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

sys.path.insert(0, str(REPO / "examples"))
import isolette_rust as example  # noqa: E402


def test_stale_dep_site_is_present_and_clean():
    src = example.GUMBO_LIB.read_text()
    assert src.count(example.STALE_DEP_SPEC) == 1  # unique flip site
    # tree starts honest: the flipped form is nowhere in the file
    assert "!= Isolette_Data_Model::ValueStatus::Valid" not in src
    # the pure text transform flips exactly the spec fn, nothing else
    tampered = example.stale_dep_text(src)
    assert tampered.count("!= Isolette_Data_Model::ValueStatus::Valid") == 1
    assert len(tampered) == len(src)  # same byte length: == -> !=


def test_foundation_crates_are_dep_only():
    """The scene's premise: the guard's crates are consumed ONLY as
    cargo dependencies — never primary verus targets (which always
    re-verify), never l1a-hashed."""
    l1a = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_l1a" / "asp_args.json").read_text())
    v = json.loads(
        (FIXTURES / "isolette_sysmlv2_rust_verus" / "asp_args.json").read_text())
    for crate in example.DEP_CRATES:
        assert not any(f"crates/{crate}" in a["filepath"]
                       for a in l1a["hashfile"].values())
        assert not any(f"crates/{crate}" in a["cwd"]
                       for a in v["run_command_cargo_verus"].values())
    # the system proof crate needs no guard: it IS a primary target
    assert any("sys_nominal_proof" in a["cwd"]
               for a in v["run_command_cargo_verus"].values())


def test_fresh_deps_guard_seed_then_clean_check(tmp_path, monkeypatch, capsys):
    """Seed (trust-on-first-use), then a no-drift check — neither path
    may touch a live mtime."""
    sidecar = tmp_path / "dep_freshness.json"
    monkeypatch.setattr(example, "DEP_FRESHNESS_SIDECAR", sidecar)
    mtimes = {c: (example.ISL_ROOT / "hamr" / "microkit" / "crates" / c
                  / "src" / "lib.rs").stat().st_mtime_ns
              for c in example.DEP_CRATES}

    example.fresh_deps_guard()
    assert "seeded the freshness record" in capsys.readouterr().out
    recorded = json.loads(sidecar.read_text())
    assert set(recorded) == set(example.DEP_CRATES)

    example.fresh_deps_guard()
    assert "warm cache is honest" in capsys.readouterr().out
    assert json.loads(sidecar.read_text()) == recorded
    for c, before in mtimes.items():
        live = (example.ISL_ROOT / "hamr" / "microkit" / "crates" / c
                / "src" / "lib.rs").stat().st_mtime_ns
        assert live == before  # clean paths never invalidate the cache
