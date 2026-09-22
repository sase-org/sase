"""Snapshot-fixture capture mode: what enters the inventory and what does not."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._visual_capture_helpers import (
    _fixture,
    _prepare_repo,
    _session,
    make_png,
)
from tests.ace.tui.visual._visual_capture import hash_file_tree
from tests.ace.tui.visual.png_diff import assert_png_matches


def test_fixture_capture_mode_continues_after_multiple_snapshots(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    fixture = _fixture(tmp_path, roots.ace, session)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    before = hash_file_tree(roots.ace)

    fixture.assert_png("first", red, source_svg="<svg>first</svg>")
    fixture.assert_png("second", blue, source_svg="<svg>second</svg>")

    assert [record.snapshot_name for record in session.captures] == [
        "first",
        "second",
    ]
    assert hash_file_tree(roots.ace) == before
    assert not (tmp_path / "artifacts").exists()


def test_temp_golden_root_does_not_enter_capture_inventory(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    temp_root = tmp_path / "snapshots" / "png"
    temp_root.mkdir(parents=True)
    png = make_png(1, 1)
    (temp_root / "temp.png").write_bytes(png)
    fixture = _fixture(tmp_path, temp_root, session)

    fixture.assert_png("temp", png)

    assert session.captures == ()
    assert list((tmp_path / "capture").glob("workers/*/captures/*.json")) == []


def test_direct_assert_png_matches_never_records_candidates(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    png = make_png(1, 1)
    (roots.ace / "direct.png").write_bytes(png)

    assert_png_matches(
        "direct",
        png,
        snapshot_root=roots.ace,
        artifact_root=tmp_path / "artifacts",
        update=False,
        node_id="tests/ace/tui/visual/test_a.py::test_a",
        repo_root=tmp_path,
    )

    assert session.captures == ()
    assert list((tmp_path / "capture").rglob("*.json")) == []


def test_ordinary_comparison_still_fails_without_capture_session(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    (roots.ace / "mismatch.png").write_bytes(make_png(1, 1, (255, 0, 0, 255)))
    fixture = _fixture(tmp_path, roots.ace, session=None)

    with pytest.raises(AssertionError, match="ACE PNG snapshot mismatch"):
        fixture.assert_png("mismatch", make_png(1, 1, (0, 0, 255, 255)))
