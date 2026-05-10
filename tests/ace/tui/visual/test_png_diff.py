"""Unit tests for the ACE PNG snapshot helper."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from tests.ace.tui.visual import png_diff
from tests.ace.tui.visual.png_diff import (
    AcePngSnapshotFixture,
    diff_pngs,
    render_svg_to_png,
)

pytestmark = pytest.mark.visual


@dataclass
class _Page:
    svg: str
    title: str | None = None
    simplify: bool | None = None

    def export_svg(
        self,
        title: str | None = None,
        simplify: bool = True,
    ) -> str:
        self.title = title
        self.simplify = simplify
        return self.svg


def _png(*pixels: tuple[int, int, int, int], size: tuple[int, int]) -> bytes:
    image = Image.new("RGBA", size)
    image.putdata(list(pixels))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _fixture(
    tmp_path: Path,
    *,
    update: bool = False,
) -> AcePngSnapshotFixture:
    return AcePngSnapshotFixture(
        snapshot_root=tmp_path / "snapshots" / "png",
        artifact_root=tmp_path / "artifacts",
        update=update,
        node_id="tests/ace/tui/visual/test_png_diff.py::test_case",
    )


def test_update_mode_writes_png_golden(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path, update=True)
    png = _png((255, 0, 0, 255), size=(1, 1))

    ace_visual.assert_png("accepted", png)

    assert (tmp_path / "snapshots" / "png" / "accepted.png").read_bytes() == png


def test_matching_png_passes(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)
    png = _png((255, 0, 0, 255), size=(1, 1))
    golden = tmp_path / "snapshots" / "png" / "matching.png"
    golden.parent.mkdir(parents=True)
    golden.write_bytes(png)

    ace_visual.assert_png("matching", png)


def test_mismatched_png_writes_failure_artifacts(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)
    expected = _png((255, 0, 0, 255), (0, 255, 0, 255), size=(2, 1))
    actual = _png((255, 0, 0, 255), (0, 0, 255, 255), size=(2, 1))
    golden = tmp_path / "snapshots" / "png" / "mismatch.png"
    golden.parent.mkdir(parents=True)
    golden.write_bytes(expected)

    with pytest.raises(AssertionError, match="Changed pixels: 1/2"):
        ace_visual.assert_png("mismatch.png", actual, source_svg="<svg />")

    failure_dir = (
        tmp_path
        / "artifacts"
        / "tests_ace_tui_visual_test_png_diff.py__test_case"
        / "mismatch.png"
    )
    assert (failure_dir / "expected.png").read_bytes() == expected
    assert (failure_dir / "actual.png").read_bytes() == actual
    assert (failure_dir / "diff.png").exists()
    assert (failure_dir / "actual.svg").read_text() == "<svg />"
    summary = (failure_dir / "summary.txt").read_text()
    assert "changed_pixels: 1" in summary
    assert "changed_ratio: 0.500000000000" in summary


def test_missing_png_golden_writes_actual_artifacts(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)
    actual = _png((0, 0, 255, 255), size=(1, 1))

    with pytest.raises(AssertionError, match="Missing ACE PNG snapshot golden"):
        ace_visual.assert_png("missing", actual, source_svg="<svg>actual</svg>")

    failure_dir = (
        tmp_path
        / "artifacts"
        / "tests_ace_tui_visual_test_png_diff.py__test_case"
        / "missing"
    )
    assert (failure_dir / "actual.png").read_bytes() == actual
    assert (failure_dir / "actual.svg").read_text() == "<svg>actual</svg>"
    assert "missing" in (failure_dir / "summary.txt").read_text()
    assert not (failure_dir / "expected.png").exists()


def test_png_names_must_stay_under_snapshot_root(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)

    with pytest.raises(ValueError, match="invalid snapshot name"):
        ace_visual.assert_png("../escape", _png((0, 0, 0, 0), size=(1, 1)))


def test_diff_pngs_handles_dimension_changes() -> None:
    expected = _png((255, 0, 0, 255), size=(1, 1))
    actual = _png((255, 0, 0, 255), (0, 0, 255, 255), size=(2, 1))

    summary, diff = diff_pngs(expected, actual)

    assert summary.expected_size == (1, 1)
    assert summary.actual_size == (2, 1)
    assert summary.changed_pixels == 1
    assert summary.total_pixels == 2
    assert diff.startswith(b"\x89PNG")


def test_assert_svg_png_rasterizes_page_svg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ace_visual = _fixture(tmp_path, update=True)
    actual = _png((0, 255, 0, 255), size=(1, 1))
    page = _Page("<svg>source</svg>")

    monkeypatch.setattr(png_diff, "render_svg_to_png", lambda svg: actual)

    ace_visual.assert_svg_png(page, "from_svg", title="ACE", simplify=False)

    assert (tmp_path / "snapshots" / "png" / "from_svg.png").read_bytes() == actual
    assert page.title == "ACE"
    assert page.simplify is False


def test_render_svg_to_png_uses_visual_renderer() -> None:
    pytest.importorskip("cairosvg")

    png = render_svg_to_png(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
        '<rect width="1" height="1" fill="red"/>'
        "</svg>"
    )

    assert png.startswith(b"\x89PNG")
