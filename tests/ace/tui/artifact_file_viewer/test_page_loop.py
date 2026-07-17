from __future__ import annotations

import subprocess
from pathlib import Path

from sase.ace.tui.graphics.viewer import (
    ArtifactFileViewerResult,
    run_artifact_page_loop,
)

from ._helpers import _TEST_IMAGE_AREA, _test_icat_command


def test_run_artifact_page_loop_redraws_and_tracks_keys(
    tmp_path: Path,
    capsys,
) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    keys = iter(["j", "k", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_page_loop(
        pages,
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
        _test_icat_command(pages[1]),
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
    ]
    output = capsys.readouterr().out
    cursor_escape = "\x1b[24;1H"
    assert output.count(cursor_escape) == 3
    assert output.index(cursor_escape) < output.index("Page 1/2")


def test_run_artifact_page_loop_refreshes_current_page(tmp_path: Path) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    keys = iter(["r", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_page_loop(
        pages,
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
    ]


def test_run_artifact_page_loop_zoom_redraws_current_page(tmp_path: Path) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    zooms: list[bool] = []
    keys = iter(["j", "z", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_zoom() -> ArtifactFileViewerResult:
        zooms.append(True)
        return ArtifactFileViewerResult(True)

    result = run_artifact_page_loop(
        pages,
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        tmux_zoom_available=True,
        toggle_zoom=fake_zoom,
    )

    assert result.returncode == 0
    assert zooms == [True]
    assert commands == [
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
        _test_icat_command(pages[1]),
        ["clear"],
        _test_icat_command(pages[1]),
        ["clear"],
    ]


def test_run_artifact_page_loop_tab_focuses_return_pane_and_stays_open(
    tmp_path: Path,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_page_loop(
        [page],
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        return_pane_id="%1",
        select_pane=fake_select,
    )

    assert result.returncode == 0
    assert selected == ["%1"]
    assert commands == [
        ["clear"],
        _test_icat_command(page),
        ["clear"],
    ]


def test_run_artifact_page_loop_tab_then_navigation_renders_next_page(
    tmp_path: Path,
) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "j", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_page_loop(
        pages,
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        return_pane_id="%1",
        select_pane=fake_select,
    )

    assert result.returncode == 0
    assert selected == ["%1"]
    assert commands == [
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
        _test_icat_command(pages[1]),
        ["clear"],
    ]


def test_run_artifact_page_loop_tab_then_refresh_renders_same_page(
    tmp_path: Path,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "r", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_page_loop(
        [page],
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        return_pane_id="%1",
        select_pane=fake_select,
    )

    assert result.returncode == 0
    assert selected == ["%1"]
    assert commands == [
        ["clear"],
        _test_icat_command(page),
        ["clear"],
        _test_icat_command(page),
        ["clear"],
    ]


def test_run_artifact_page_loop_repeated_tab_does_not_re_render(
    tmp_path: Path,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "\t", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_page_loop(
        [page],
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        return_pane_id="%1",
        select_pane=fake_select,
    )

    assert result.returncode == 0
    assert selected == ["%1", "%1"]
    assert commands == [
        ["clear"],
        _test_icat_command(page),
        ["clear"],
    ]


def test_run_artifact_page_loop_wraps_boundary_keys(
    tmp_path: Path,
) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    commands: list[list[str]] = []
    keys = iter(["k", "j", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_page_loop(
        pages,
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
        _test_icat_command(pages[1]),
        ["clear"],
        _test_icat_command(pages[0]),
        ["clear"],
    ]
