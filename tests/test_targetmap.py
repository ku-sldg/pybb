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

    l2 = json.loads((FIXTURES / "gumbo_l2" / "asp_args.json").read_text())
    derived_ranges = {
        (a["filepath"], a["start_index"], a["end_index"])
        for a in derived["gumbo_l2"]["readfile_range"].values()
    }
    for targ, args in l2["readfile_range"].items():
        key = (args["filepath"], args["start_index"], args["end_index"])
        assert key in derived_ranges, f"provisioned {targ} not derivable"

    l1b = json.loads((FIXTURES / "gumbo_l1b" / "asp_args.json").read_text())
    derived_blocks = derived["gumbo_l1b"]["readfile_marker_range"]
    for targ, args in l1b["readfile_marker_range"].items():
        assert targ in derived_blocks, f"provisioned {targ} not derived by name"
        assert derived_blocks[targ]["begin_marker"] == args["begin_marker"]
        assert derived_blocks[targ]["end_marker"] == args["end_marker"]

    l1a = json.loads((FIXTURES / "gumbo_l1a" / "asp_args.json").read_text())
    assert set(derived["gumbo_l1a"]["hashfile"]) == set(l1a["hashfile"])


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
    term = build_term(derived["gumbo_l2"])
    bodies = list(iter_aspc_bodies(term))
    assert len(bodies) == len(derived["gumbo_l2"]["readfile_range"])
    assert {b["ASP_ID"] for b in bodies} == {"readfile_range"}
    # structure: lseq(lseq(chain, SIG), APPR)
    assert term["TERM_CONSTRUCTOR"] == "lseq"
    assert term["TERM_BODY"][1]["TERM_BODY"]["ASP_CONSTRUCTOR"] == "APPR"


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
