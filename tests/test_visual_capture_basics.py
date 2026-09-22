"""PNG parsing, artifact IDs, and snapshot-name validation for visual capture."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._visual_capture_helpers import _prepare_repo, make_png
from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    VisualCaptureError,
    canonical_golden_path,
    capture_artifact_id,
    png_dimensions,
)


def _lossy_slug(value: str) -> str:
    chars = [char if char.isalnum() or char in "._-" else "_" for char in value]
    return "".join(chars).strip("._-") or "snapshot"


def test_png_dimensions_read_ihdr_without_pixels() -> None:
    png = make_png(3, 2, (1, 2, 3, 4))
    assert png_dimensions(png) == (3, 2)


def test_png_dimensions_reject_non_png() -> None:
    with pytest.raises(VisualCaptureError, match="not a PNG"):
        png_dimensions(b"not-a-png")


def test_artifact_ids_remain_distinct_when_lossy_slugs_collide() -> None:
    left = "tests/foo.py::test_a"
    right = "tests_foo.py::test_a"
    assert _lossy_slug(left) == _lossy_slug(right)
    assert capture_artifact_id(
        node_id=left,
        canonical_golden_path=f"{DEFAULT_ACE_ROOT}/a.png",
        sequence=1,
        worker_id="gw0",
    ) != capture_artifact_id(
        node_id=right,
        canonical_golden_path=f"{DEFAULT_ACE_ROOT}/a.png",
        sequence=1,
        worker_id="gw0",
    )


def test_absolute_snapshot_name_is_rejected(tmp_path: Path) -> None:
    _, roots = _prepare_repo(tmp_path)
    with pytest.raises(VisualCaptureError, match="invalid snapshot name"):
        canonical_golden_path(
            snapshot_root=roots.ace,
            name=str(tmp_path / "escaped.png"),
            repo_root=tmp_path,
            roots=roots,
        )


def test_parent_traversal_snapshot_name_is_rejected(tmp_path: Path) -> None:
    _, roots = _prepare_repo(tmp_path)
    with pytest.raises(VisualCaptureError, match="invalid snapshot name"):
        canonical_golden_path(
            snapshot_root=roots.ace,
            name="../escape",
            repo_root=tmp_path,
            roots=roots,
        )


def test_symlink_escape_snapshot_name_is_rejected(tmp_path: Path) -> None:
    _, roots = _prepare_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (roots.ace / "link").symlink_to(outside)
    with pytest.raises(VisualCaptureError, match="escapes ace PNG root"):
        canonical_golden_path(
            snapshot_root=roots.ace,
            name="link/evil",
            repo_root=tmp_path,
            roots=roots,
        )
