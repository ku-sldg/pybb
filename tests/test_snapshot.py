"""TargetSnapshot: clean copies of live targets, captured before attestation."""

from types import SimpleNamespace

import pytest

from pybb.attestation import TargetSnapshot, watched_files


def _protocols(*filepaths, extra_target=None):
    """Protocols stub exposing asp_args like ProtocolDir."""
    targets = {f"targ_{i}": {"filepath": str(fp)} for i, fp in enumerate(filepaths)}
    if extra_target is not None:
        targets["no_file_targ"] = extra_target
    return {"l1": SimpleNamespace(asp_args={"hashfile_id": targets})}


def _make_tree(root):
    a = root / "tree" / "a.txt"
    b = root / "tree" / "sub" / "b.txt"
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    a.write_text("clean a")
    b.write_text("clean b")
    return a, b


def test_watched_files_collects_filepaths_only(tmp_path):
    a, b = _make_tree(tmp_path)
    protocols = _protocols(a, b, extra_target={"env": "SOME_VAR"})
    assert watched_files(protocols) == {a, b}


def test_watched_files_dedups_across_protocols(tmp_path):
    a, _ = _make_tree(tmp_path)
    protocols = {**_protocols(a), "l2": _protocols(a)["l1"]}
    assert watched_files(protocols) == {a}


def test_capture_mirrors_live_tree(tmp_path):
    a, b = _make_tree(tmp_path)
    dest = tmp_path / "snap"

    snapshot = TargetSnapshot.capture(_protocols(a, b), dest=dest)

    assert snapshot.root == dest
    assert set(snapshot.files) == {a, b}
    for live, copy in snapshot.files.items():
        # absolute live path mirrored under the snapshot root
        assert copy == dest / live.relative_to(live.anchor)
        assert copy.read_text() == live.read_text()
    assert snapshot.dirty() == []


def test_capture_defaults_to_temp_root(tmp_path):
    a, _ = _make_tree(tmp_path)
    snapshot = TargetSnapshot.capture(_protocols(a))
    assert snapshot.root.is_dir() and snapshot.dirty() == []


def test_load_opens_existing_snapshot(tmp_path):
    a, b = _make_tree(tmp_path)
    protocols = _protocols(a, b)
    TargetSnapshot.capture(protocols, dest=tmp_path / "golden")

    golden = TargetSnapshot.load(protocols, tmp_path / "golden")

    assert set(golden.files) == {a, b}
    a.write_text("TAMPERED")
    assert golden.restore() == [a] and a.read_text() == "clean a"


def test_load_missing_copy_raises_with_paths(tmp_path):
    a, b = _make_tree(tmp_path)
    TargetSnapshot.capture(_protocols(a), dest=tmp_path / "golden")

    with pytest.raises(FileNotFoundError, match=str(b)):
        TargetSnapshot.load(_protocols(a, b), tmp_path / "golden")


def test_restore_reverts_tampered_and_deleted_targets(tmp_path):
    a, b = _make_tree(tmp_path)
    snapshot = TargetSnapshot.capture(_protocols(a, b), dest=tmp_path / "snap")

    a.write_text("TAMPERED")
    b.unlink()
    assert set(snapshot.dirty()) == {a, b}

    restored = snapshot.restore()

    assert set(restored) == {a, b}
    assert a.read_text() == "clean a" and b.read_text() == "clean b"
    assert snapshot.dirty() == [] and snapshot.restore() == []
