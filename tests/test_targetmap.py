"""
Target-map derivation: the syntax scan must cover every historically
provisioned target (derived maps may be supersets — the provisioned map
was hand-curated), reproduce the provisioned naming, and track content
shifts. Runs against the live temp-control tree when present.
"""

import json
from pathlib import Path

import pytest

from pybb.attestation.copland import iter_aspc_bodies
from pybb.attestation.targetmap import (
    TEMP_CONTROL_SPEC,
    aadl_contract_spans,
    build_term,
    derive_targets,
    gumbox_spans,
    install_targets,
    marker_blocks,
)

FIXTURES = Path(__file__).parent / "fixtures"
TC_ROOT = Path("/Users/adampetz/Claude_workspace/temp-control-jvm")

needs_tree = pytest.mark.skipif(not TC_ROOT.is_dir(),
                                reason="requires temp-control-jvm tree")


@needs_tree
def test_derived_map_covers_every_provisioned_target():
    derived = derive_targets(TEMP_CONTROL_SPEC)

    l2 = json.loads((FIXTURES / "temp_control_aadl_slang_l2" / "asp_args.json").read_text())
    derived_ranges = {
        (a["filepath"], a["start_index"], a["end_index"])
        for a in derived["temp_control_aadl_slang_l2"]["readfile_range"].values()
    }
    for targ, args in l2["readfile_range"].items():
        key = (args["filepath"], args["start_index"], args["end_index"])
        assert key in derived_ranges, f"provisioned {targ} not derivable"

    l1b = json.loads((FIXTURES / "temp_control_aadl_slang_l1b" / "asp_args.json").read_text())
    derived_blocks = derived["temp_control_aadl_slang_l1b"]["readfile_marker_range"]
    for targ, args in l1b["readfile_marker_range"].items():
        assert targ in derived_blocks, f"provisioned {targ} not derived by name"
        assert derived_blocks[targ]["begin_marker"] == args["begin_marker"]
        assert derived_blocks[targ]["end_marker"] == args["end_marker"]

    l1a = json.loads((FIXTURES / "temp_control_aadl_slang_l1a" / "asp_args.json").read_text())
    assert set(derived["temp_control_aadl_slang_l1a"]["hashfile"]) == set(l1a["hashfile"])


def test_spans_shift_with_content():
    aadl = (
        "package P\n"
        "annex GUMBO {**\n"
        "  inv Inv1:\n"
        "    x > 0;\n"
        "**};\n"
    )
    assert aadl_contract_spans(aadl) == [(3, 4)]
    shifted = "-- a new comment line\n" + aadl
    assert aadl_contract_spans(shifted) == [(4, 5)]


def test_aadl_scanner_ignores_comments_and_outside_annex():
    text = (
        "guarantee outside_annex: x;\n"
        "annex GUMBO {**\n"
        "  -- guarantee commented: y;\n"
        "  assume A1:\n"
        "    y > 0;\n"
        "**};\n"
    )
    assert aadl_contract_spans(text) == [(4, 5)]


def test_gumbox_span_extends_through_contiguous_block():
    text = (
        "object X {\n"
        "  @strictpure def p(\n"
        "      a: B): B =\n"
        "    a\n"
        "\n"
        "  @strictpure def q(a: B): B = a\n"
        "}\n"
    )
    assert gumbox_spans(text) == [(2, 4), (6, 7)]


def test_marker_blocks_and_slugs():
    text = (
        "// BEGIN STATE VARS\n"
        "var x = 0\n"
        "// END STATE VARS\n"
        "// BEGIN COMPUTE ENSURES timeTriggered\n"
        "// END COMPUTE ENSURES timeTriggered\n"
    )
    assert marker_blocks(text) == [
        ("BEGIN STATE VARS", "END STATE VARS"),
        ("BEGIN COMPUTE ENSURES timeTriggered", "END COMPUTE ENSURES timeTriggered"),
    ]


@needs_tree
def test_built_term_matches_target_count_and_structure():
    derived = derive_targets(TEMP_CONTROL_SPEC)
    term = build_term(derived["temp_control_aadl_slang_l2"])
    bodies = list(iter_aspc_bodies(term))
    assert len(bodies) == len(derived["temp_control_aadl_slang_l2"]["readfile_range"])
    assert {b["ASP_ID"] for b in bodies} == {"readfile_range"}
    # structure: lseq(lseq(chain, SIG), APPR)
    assert term["TERM_CONSTRUCTOR"] == "lseq"
    assert term["TERM_BODY"][1]["TERM_BODY"]["ASP_CONSTRUCTOR"] == "APPR"


# ── report-driven backend, validated against the real isolette report ────────

ISOLETTE_REPORT = Path(
    "/Users/adampetz/Claude_workspace/INSPECTA-models/isolette/hamr/microkit"
    "/attestation/aadl_attestation_report.json")
CVM_MCP_ISOLETTE = Path("/Users/adampetz/Claude_workspace/cvm-mcp/protocol_dirs")

needs_isolette = pytest.mark.skipif(not ISOLETTE_REPORT.is_file(),
                                    reason="requires isolette attestation report")


@needs_isolette
def test_report_backend_matches_reference_generation():
    from pybb.attestation.targetmap import derive_targets_from_report

    derived = derive_targets_from_report(ISOLETTE_REPORT, prefix="isolette")

    # cross-validate against cvm-mcp's hamr_report_protocols output, the
    # reference consumer of the same report
    ref_l2 = json.loads(
        (CVM_MCP_ISOLETTE / "isolette_l2" / "asp_args.json").read_text())
    ref_ranges = {
        (a["filepath"], a["start_index"], a["end_index"])
        for a in ref_l2["readfile_range"].values()
    }
    our_ranges = {
        (a["filepath"], a["start_index"], a["end_index"])
        for a in derived["isolette_l2"]["readfile_range"].values()
    }
    assert our_ranges == ref_ranges

    ref_l1 = json.loads(
        (CVM_MCP_ISOLETTE / "isolette_l1" / "asp_args.json").read_text())
    ref_files = {a["filepath"] for a in ref_l1["hashfile"].values()}
    our_files = {a["filepath"] for a in derived["isolette_l1a"]["hashfile"].values()}
    assert our_files == ref_files


@needs_isolette
def test_report_slices_resolve_to_real_files_of_both_kinds():
    from pybb.attestation.targetmap import report_slices

    slices = report_slices(ISOLETTE_REPORT)
    # 67 unique (file, begin, end) — the reference's 85 targets include
    # ranges cited by multiple contracts; report_slices dedupes them
    assert len(slices) >= 60
    kinds = {s["kind"] for s in slices}
    assert "Model" in kinds and "Verus" in kinds  # model AND generated artifacts
    for s in slices:
        assert Path(s["filepath"]).is_file(), s["filepath"]
        assert 0 < s["begin"] <= s["end"]
        assert "::" in s["metadata"]


def test_install_targets_writes_through_and_drops_prebuilt(tmp_path):
    from pybb.attestation import ProtocolDir

    proto_dir = tmp_path / "p1"
    proto_dir.mkdir()
    (proto_dir / "cvm_request.json").write_text("{}")
    protocol = ProtocolDir(protocol_id="p1", path=str(proto_dir), term={},
                           session={}, manifest={}, prebuilt_request={})
    asp_args = {"readfile_range": {"t1": {"filepath": "/f", "start_index": 1,
                                          "end_index": 2}}}

    count = install_targets(protocol, asp_args)

    assert count == 1
    assert protocol.prebuilt_request is None
    assert protocol.asp_args == asp_args
    on_disk = json.loads((proto_dir / "asp_args.json").read_text())
    assert on_disk == asp_args
    assert not (proto_dir / "cvm_request.json").exists()
    term = json.loads((proto_dir / "term.json").read_text())
    assert len(list(iter_aspc_bodies(term))) == 1


# ── lean-package backend ──────────────────────────────────────────────────────

LEAN_ROOT = Path(__file__).parent.parent / "targets" / "temp-control-lean"


def test_lean_decl_spans_shapes():
    from pybb.attestation.targetmap import lean_decl_spans

    text = (
        "/-\n"
        "A block comment whose lines start at column 0: a\n"
        "theorem mentioned here must not become a target,\n"
        "def or otherwise.\n"
        "-/\n"
        "import Foo\n"
        "\n"
        "namespace N\n"
        "\n"
        "inductive Cmd where\n"
        "  | a\n"
        "deriving Repr\n"
        "\n"
        "/-- doc comment stays outside the span -/\n"
        "theorem t1 (x : Int) :\n"
        "    x = x := by\n"
        "  rfl\n"
        "\n"
        "instance : ToString Cmd where\n"
        "  toString _ := \"a\"\n"
        "\n"
        "example : 1 = 1 := by decide\n"
        "example : 2 = 2 := by decide\n"
        "\n"
        "def Cmd.flip : Cmd -> Cmd\n"
        "  | a => a\n"
        "\n"
        "end N\n"
    )
    spans = lean_decl_spans(text)
    assert spans == [
        ("inductive", "Cmd", 10, 12),    # deriving line inside the span
        ("theorem", "t1", 15, 17),       # doc comment excluded
        ("instance", None, 19, 20),      # anonymous
        ("example", None, 22, 22),       # consecutive decls split correctly
        ("example", None, 23, 23),
        ("def", "Cmd.flip", 25, 26),     # dotted name captured whole
    ]


def test_lean_spans_shift_with_content():
    from pybb.attestation.targetmap import lean_decl_spans

    base = "theorem t1 : 1 = 1 := by\n  decide\n"
    before = lean_decl_spans(base)
    shifted = lean_decl_spans("-- a new header line\n\n" + base)
    assert before == [("theorem", "t1", 1, 2)]
    assert shifted == [("theorem", "t1", 3, 4)]


def test_lean_derived_targets_live_tree():
    from pybb.attestation.targetmap import derive_targets_from_lean

    from pybb.attestation.targetmap import lean_package_files

    derived = derive_targets_from_lean(LEAN_ROOT, prefix="temp_control_lean")
    assert set(derived) == {"temp_control_lean_contracts"}

    # the executable class's build-input set: sources AND build
    # configuration (lakefile + toolchain pin)
    inputs = lean_package_files(LEAN_ROOT)
    names = {Path(p).name for p in inputs}
    assert {"Impl.lean", "Spec.lean", "Main.lean", "TempControl.lean",
            "lakefile.toml", "lean-toolchain"} <= names
    for p in inputs:
        assert Path(p).is_file()
        assert ".lake" not in Path(p).parts

    l2 = derived["temp_control_lean_contracts"]["readfile_range"]
    # every contract slice lives inside a package file
    sources = set(inputs)
    for targ, args in l2.items():
        assert args["filepath"] in sources, targ
        assert 0 < args["start_index"] <= args["end_index"]
        assert "::" in args["metadata"]

    # declaration-named attribution: the implementation function and the
    # GUMBO-mirror theorems are targets, in their split-out modules
    named = {"temp_control_lean_impl_computeFanCmd_targ": ("computeFanCmd", "TempControl.Impl"),
             **{f"temp_control_lean_spec_{n}_targ": (n, "TempControl.Spec")
                for n in ("fanOn_when_hot", "fanOff_when_cold",
                          "fanHold_in_band", "fanOn_only_if_hot_or_held")}}
    for targ, (name, module) in named.items():
        assert targ in l2, targ
        first = Path(l2[targ]["filepath"]).read_text().splitlines()[
            l2[targ]["start_index"] - 1]
        assert name in first  # the span starts at the declaration line
        assert l2[targ]["metadata"] == f"{module}::{name}"
    # the Impl block comment mentions "theorem ..." at column 0 — the
    # scanner must not have minted a target from it
    assert not any("cannot" in t for t in l2)

    # the executable's entry point is attributable too
    assert "temp_control_lean_main_main_targ" in l2

    # derived maps feed straight into term construction
    term = build_term(derived["temp_control_lean_contracts"])
    assert len(list(iter_aspc_bodies(term))) == len(l2)


# ── asp_targid: self-describing targets ───────────────────────────────────────

def test_every_fixture_target_is_self_identifying():
    """Derivation-time injection: every committed target's args carry
    asp_targid equal to its key (temp_control_aadl_slang_validation predates the target
    convention and has no targets to stamp)."""
    for proto_dir in sorted(FIXTURES.iterdir()):
        aa = proto_dir / "asp_args.json"
        if not aa.is_file():
            continue
        asp_args = json.loads(aa.read_text())
        for asp_id, targets in asp_args.items():
            for targ_id, args in targets.items():
                assert args.get("asp_targid") == targ_id, \
                    f"{proto_dir.name}/{asp_id}/{targ_id} not self-identifying"


def test_load_rejects_asp_targid_drift(tmp_path):
    from pybb.attestation import ProtocolDir

    d = tmp_path / "p"
    d.mkdir()
    (d / "term.json").write_text("{}")
    (d / "session.json").write_text("{}")
    (d / "manifest.json").write_text("{}")
    (d / "asp_args.json").write_text(json.dumps({"hashfile": {
        "t1": {"filepath": "/f", "asp_targid": "OTHER"}}}))
    import pytest as _pytest
    with _pytest.raises(ValueError, match="asp_targid"):
        ProtocolDir.load(str(d))


def test_with_asp_targids_stamps_and_preserves():
    from pybb.attestation.copland import with_asp_targids

    out = with_asp_targids({"a_targ": {"filepath": "/x"}, "b_targ": {}})
    assert out["a_targ"] == {"filepath": "/x", "asp_targid": "a_targ"}
    assert out["b_targ"]["asp_targid"] == "b_targ"
