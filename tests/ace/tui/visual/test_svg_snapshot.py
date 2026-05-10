"""Unit tests for the ACE SVG snapshot helper."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.ace.tui.visual.svg_snapshot import AceSvgSnapshotFixture

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


def _fixture(
    tmp_path: Path,
    *,
    update: bool = False,
) -> AceSvgSnapshotFixture:
    return AceSvgSnapshotFixture(
        snapshot_root=tmp_path / "snapshots" / "svg",
        artifact_root=tmp_path / "artifacts",
        update=update,
        node_id="tests/ace/tui/visual/test_svg_snapshot.py::test_case",
    )


def test_missing_golden_fails_without_update(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)

    with pytest.raises(AssertionError, match="Missing ACE SVG snapshot golden"):
        ace_visual.assert_svg(_Page("<svg>actual</svg>"), "missing")

    failure_dir = (
        tmp_path
        / "artifacts"
        / ("tests_ace_tui_visual_test_svg_snapshot.py__test_case")
        / "missing"
    )
    assert (failure_dir / "actual.svg").read_text() == "<svg>actual</svg>"
    assert (failure_dir / "report.html").exists()
    assert not (failure_dir / "expected.svg").exists()


def test_update_mode_writes_golden(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path, update=True)
    page = _Page("<svg>accepted</svg>")

    ace_visual.assert_svg(page, "accepted", title="ACE", simplify=False)

    assert (tmp_path / "snapshots" / "svg" / "accepted.svg").read_text() == (
        "<svg>accepted</svg>"
    )
    assert page.title == "ACE"
    assert page.simplify is False


def test_matching_svg_passes(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)
    golden = tmp_path / "snapshots" / "svg" / "matching.svg"
    golden.parent.mkdir(parents=True)
    golden.write_text("<svg>same</svg>")

    ace_visual.assert_svg(_Page("<svg>same</svg>"), "matching")


def test_terminal_svg_ids_are_normalized(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)
    golden = tmp_path / "snapshots" / "svg" / "matching.svg"
    golden.parent.mkdir(parents=True)
    golden.write_text(
        "<svg><style>.terminal-123-r1 { fill: red }</style>"
        '<clipPath id="terminal-123-line-0" /></svg>'
    )

    ace_visual.assert_svg(
        _Page(
            "<svg><style>.terminal-456-r1 { fill: red }</style>"
            '<clipPath id="terminal-456-line-0" /></svg>'
        ),
        "matching",
    )


def test_mismatched_svg_writes_failure_artifacts(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)
    golden = tmp_path / "snapshots" / "svg" / "mismatch.svg"
    golden.parent.mkdir(parents=True)
    golden.write_text("<svg>expected</svg>")

    with pytest.raises(AssertionError, match="ACE SVG snapshot mismatch"):
        ace_visual.assert_svg(_Page("<svg>actual</svg>"), "mismatch.svg")

    failure_dir = (
        tmp_path
        / "artifacts"
        / ("tests_ace_tui_visual_test_svg_snapshot.py__test_case")
        / "mismatch.svg"
    )
    assert (failure_dir / "expected.svg").read_text() == "<svg>expected</svg>"
    assert (failure_dir / "actual.svg").read_text() == "<svg>actual</svg>"
    report = (failure_dir / "report.html").read_text()
    assert "expected.svg" in report
    assert "actual.svg" in report


def test_snapshot_names_must_stay_under_snapshot_root(tmp_path: Path) -> None:
    ace_visual = _fixture(tmp_path)

    with pytest.raises(ValueError, match="invalid snapshot name"):
        ace_visual.assert_svg(_Page("<svg />"), "../escape")
