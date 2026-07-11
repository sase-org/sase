"""Unit tests for the ACE PNG snapshot helper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from tests.ace.tui.visual import png_diff
from tests.ace.tui.visual.conftest import _visual_artifact_root
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
    node_id: str = "tests/ace/tui/visual/test_png_diff.py::test_case",
    test_file: str | None = "tests/ace/tui/visual/test_png_diff.py",
    test_line: int | None = 42,
) -> AcePngSnapshotFixture:
    return AcePngSnapshotFixture(
        snapshot_root=tmp_path / "snapshots" / "png",
        artifact_root=tmp_path / "artifacts",
        update=update,
        node_id=node_id,
        test_file=test_file,
        test_line=test_line,
        repo_root=tmp_path,
    )


def _write_golden(tmp_path: Path, name: str, png: bytes) -> None:
    golden = tmp_path / "snapshots" / "png" / name
    golden.parent.mkdir(parents=True, exist_ok=True)
    golden.write_bytes(png)


def _clear_png_tolerance_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_VISUAL_PNG_MAX_DIFF_RATIO", raising=False)


def test_relative_artifact_root_is_anchored_after_chdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    config = MagicMock(spec=pytest.Config)
    config.getoption.return_value = ".pytest_cache/sase-visual"
    config.rootpath = repo_root
    monkeypatch.chdir(tmp_path)

    assert _visual_artifact_root(config) == repo_root / ".pytest_cache" / "sase-visual"


def test_update_mode_writes_png_golden(tmp_path: Path) -> None:
    ace_png_visual = _fixture(tmp_path, update=True)
    png = _png((255, 0, 0, 255), size=(1, 1))

    ace_png_visual.assert_png("accepted", png)

    assert (tmp_path / "snapshots" / "png" / "accepted.png").read_bytes() == png


def test_matching_png_passes(tmp_path: Path) -> None:
    ace_png_visual = _fixture(tmp_path)
    png = _png((255, 0, 0, 255), size=(1, 1))
    _write_golden(tmp_path, "matching.png", png)

    ace_png_visual.assert_png("matching", png)


def test_default_fails_on_one_pixel_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_png_tolerance_env(monkeypatch)
    ace_png_visual = _fixture(tmp_path)
    expected_pixels = [(255, 0, 0, 255)] * 100
    actual_pixels = expected_pixels.copy()
    actual_pixels[0] = (0, 0, 255, 255)
    _write_golden(tmp_path, "strict.png", _png(*expected_pixels, size=(10, 10)))

    with pytest.raises(AssertionError, match="default"):
        ace_png_visual.assert_png("strict", _png(*actual_pixels, size=(10, 10)))


def test_github_actions_env_does_not_relax_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The renderer is hermetic, so CI no longer earns a drift tolerance: a
    # GitHub Actions environment must still enforce exact pixel equality.
    _clear_png_tolerance_env(monkeypatch)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_WORKFLOW", "visual-test")
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    ace_png_visual = _fixture(tmp_path)
    expected_pixels = [(255, 0, 0, 255)] * 100
    actual_pixels = expected_pixels.copy()
    actual_pixels[0] = (0, 0, 255, 255)
    _write_golden(tmp_path, "ci_strict.png", _png(*expected_pixels, size=(10, 10)))

    with pytest.raises(AssertionError, match="default"):
        ace_png_visual.assert_png("ci_strict", _png(*actual_pixels, size=(10, 10)))


def test_env_tolerance_allows_renderer_drift_without_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_png_tolerance_env(monkeypatch)
    monkeypatch.setenv("SASE_VISUAL_PNG_MAX_DIFF_RATIO", "0.02")
    ace_png_visual = _fixture(tmp_path)
    expected_pixels = [(255, 0, 0, 255)] * 100
    actual_pixels = expected_pixels.copy()
    actual_pixels[0] = (0, 0, 255, 255)
    _write_golden(tmp_path, "env_tolerated.png", _png(*expected_pixels, size=(10, 10)))

    ace_png_visual.assert_png("env_tolerated", _png(*actual_pixels, size=(10, 10)))

    assert not (tmp_path / "artifacts").exists()


def test_explicit_strict_tolerance_overrides_env_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_png_tolerance_env(monkeypatch)
    monkeypatch.setenv("SASE_VISUAL_PNG_MAX_DIFF_RATIO", "0.02")
    ace_png_visual = _fixture(tmp_path)
    expected_pixels = [(255, 0, 0, 255)] * 100
    actual_pixels = expected_pixels.copy()
    actual_pixels[0] = (0, 0, 255, 255)
    _write_golden(
        tmp_path,
        "env_explicit_strict.png",
        _png(*expected_pixels, size=(10, 10)),
    )

    with pytest.raises(AssertionError, match="explicit"):
        ace_png_visual.assert_png(
            "env_explicit_strict",
            _png(*actual_pixels, size=(10, 10)),
            max_diff_pixels=0,
            max_diff_ratio=0.0,
        )


def test_mismatched_png_writes_failure_artifacts(tmp_path: Path) -> None:
    ace_png_visual = _fixture(tmp_path)
    expected = _png((255, 0, 0, 255), (0, 255, 0, 255), size=(2, 1))
    actual = _png((255, 0, 0, 255), (0, 0, 255, 255), size=(2, 1))
    _write_golden(tmp_path, "mismatch.png", expected)

    with pytest.raises(AssertionError, match="Changed pixels: 1/2"):
        ace_png_visual.assert_png("mismatch.png", actual, source_svg="<svg />")

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

    record = json.loads((failure_dir / "failure.json").read_text())
    assert record["kind"] == "mismatch"
    assert record["node_id"] == "tests/ace/tui/visual/test_png_diff.py::test_case"
    assert record["snapshot"] == "mismatch.png"
    assert record["expected_repo_path"] == "snapshots/png/mismatch.png"
    assert record["actual_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/"
        "mismatch.png/actual.png"
    )
    assert record["expected_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/"
        "mismatch.png/expected.png"
    )
    assert record["diff_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/"
        "mismatch.png/diff.png"
    )
    assert record["source_svg_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/"
        "mismatch.png/actual.svg"
    )
    assert record["summary_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/"
        "mismatch.png/summary.txt"
    )
    assert record["test_file"] == "tests/ace/tui/visual/test_png_diff.py"
    assert record["test_line"] == 42
    assert record["expected_size"] == [2, 1]
    assert record["actual_size"] == [2, 1]
    assert record["changed_pixels"] == 1
    assert record["total_pixels"] == 2
    assert record["changed_ratio"] == 0.5


def test_missing_png_golden_writes_actual_artifacts(tmp_path: Path) -> None:
    ace_png_visual = _fixture(tmp_path)
    actual = _png((0, 0, 255, 255), size=(1, 1))

    with pytest.raises(AssertionError, match="Missing ACE PNG snapshot golden"):
        ace_png_visual.assert_png("missing", actual, source_svg="<svg>actual</svg>")

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

    record = json.loads((failure_dir / "failure.json").read_text())
    assert record["kind"] == "missing_golden"
    assert record["node_id"] == "tests/ace/tui/visual/test_png_diff.py::test_case"
    assert record["snapshot"] == "missing"
    assert record["expected_repo_path"] == "snapshots/png/missing.png"
    assert record["actual_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/missing/actual.png"
    )
    assert record["source_svg_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/missing/actual.svg"
    )
    assert record["summary_path"] == (
        "artifacts/tests_ace_tui_visual_test_png_diff.py__test_case/missing/summary.txt"
    )
    assert record["test_file"] == "tests/ace/tui/visual/test_png_diff.py"
    assert record["test_line"] == 42
    assert "expected_path" not in record
    assert "diff_path" not in record
    assert "expected_size" not in record


def test_failure_artifacts_use_stable_directory_for_node_and_snapshot(
    tmp_path: Path,
) -> None:
    actual = _png((0, 0, 255, 255), size=(1, 1))

    first = _fixture(
        tmp_path,
        node_id="tests/ace/tui/visual/test_png_diff.py::test_one",
    )
    second = _fixture(
        tmp_path,
        node_id="tests/ace/tui/visual/test_png_diff.py::test_two",
    )

    with pytest.raises(AssertionError):
        first.assert_png("widget_a", actual)
    with pytest.raises(AssertionError):
        second.assert_png("widget_a", actual)
    with pytest.raises(AssertionError):
        first.assert_png("widget_b", actual)

    artifacts = tmp_path / "artifacts"
    assert (
        artifacts
        / "tests_ace_tui_visual_test_png_diff.py__test_one"
        / "widget_a"
        / "failure.json"
    ).exists()
    assert (
        artifacts
        / "tests_ace_tui_visual_test_png_diff.py__test_two"
        / "widget_a"
        / "failure.json"
    ).exists()
    assert (
        artifacts
        / "tests_ace_tui_visual_test_png_diff.py__test_one"
        / "widget_b"
        / "failure.json"
    ).exists()


def test_png_names_must_stay_under_snapshot_root(tmp_path: Path) -> None:
    ace_png_visual = _fixture(tmp_path)

    with pytest.raises(ValueError, match="invalid snapshot name"):
        ace_png_visual.assert_png("../escape", _png((0, 0, 0, 0), size=(1, 1)))


def test_diff_pngs_handles_dimension_changes() -> None:
    expected = _png((255, 0, 0, 255), size=(1, 1))
    actual = _png((255, 0, 0, 255), (0, 0, 255, 255), size=(2, 1))

    summary, diff = diff_pngs(expected, actual)

    assert summary.expected_size == (1, 1)
    assert summary.actual_size == (2, 1)
    assert summary.changed_pixels == 1
    assert summary.total_pixels == 2
    assert diff.startswith(b"\x89PNG")


def test_assert_page_png_rasterizes_page_svg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ace_png_visual = _fixture(tmp_path, update=True)
    actual = _png((0, 255, 0, 255), size=(1, 1))
    page = _Page("<svg>source</svg>")

    monkeypatch.setattr(png_diff, "render_svg_to_png", lambda svg: actual)

    ace_png_visual.assert_page_png(page, "from_svg", title="ACE", simplify=False)

    assert (tmp_path / "snapshots" / "png" / "from_svg.png").read_bytes() == actual
    assert page.title == "ACE"
    assert page.simplify is False


def test_render_svg_to_png_uses_visual_renderer() -> None:
    pytest.importorskip("resvg_py")

    png = render_svg_to_png(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
        '<rect width="1" height="1" fill="red"/>'
        "</svg>"
    )

    assert png.startswith(b"\x89PNG")
