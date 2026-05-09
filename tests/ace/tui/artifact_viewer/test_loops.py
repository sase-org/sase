from __future__ import annotations

import re
import subprocess
from pathlib import Path

from sase.ace.tui.graphics import _viewer_loop
from sase.ace.tui.graphics.viewer import (
    ArtifactImageArea,
    ArtifactRenderResult,
    ArtifactViewSpec,
    _print_page_prompt,
    page_index_after_key,
    page_loop_available_keys,
    run_artifact_page_loop,
    run_artifact_sequence_loop,
)

from ._helpers import _TEST_IMAGE_AREA, _test_icat_command


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value)


def test_artifact_page_index_state_machine() -> None:
    assert page_index_after_key(0, "j", 3) == 1
    assert page_index_after_key(2, "j", 3) == 0
    assert page_index_after_key(2, "k", 3) == 1
    assert page_index_after_key(0, "k", 3) == 2
    assert page_index_after_key(0, "n", 3) == 0
    assert page_index_after_key(2, "p", 3) == 2
    assert page_index_after_key(1, "r", 3) == 1
    assert page_index_after_key(1, "x", 3) == 1
    assert page_index_after_key(0, "q", 3) is None
    assert page_index_after_key(0, "j", 1) == 0
    assert page_index_after_key(0, "k", 1) == 0


def test_artifact_page_loop_available_keys_and_prompts(capsys) -> None:
    assert page_loop_available_keys(0, 1) == ("r", "q")
    assert page_loop_available_keys(0, 3) == ("j", "k", "r", "q")
    assert page_loop_available_keys(1, 3) == ("j", "k", "r", "q")
    assert page_loop_available_keys(2, 3) == ("j", "k", "r", "q")
    assert page_loop_available_keys(1, 3, artifact_index=1, artifact_count=3) == (
        "j",
        "k",
        "n",
        "p",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=0, artifact_count=3) == (
        "n",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=1, artifact_count=3) == (
        "n",
        "p",
        "r",
        "q",
    )
    assert page_loop_available_keys(0, 1, artifact_index=2, artifact_count=3) == (
        "p",
        "r",
        "q",
    )

    _print_page_prompt(index=0, page_count=1)
    output = capsys.readouterr().out
    assert _strip_ansi(output) == "\nPage 1/1  r: refresh  q: quit"
    assert _viewer_loop._FOOTER_COLOR in output
    assert output.startswith(_viewer_loop._FOOTER_RESET)
    assert output.endswith(_viewer_loop._FOOTER_RESET)

    _print_page_prompt(index=0, page_count=3)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 1/3  j: next page  k: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(index=1, page_count=3)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 2/3  j: next page  k: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(index=2, page_count=3)
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nPage 3/3  j: next page  k: previous page  r: refresh  q: quit"
    )

    _print_page_prompt(
        index=0,
        page_count=1,
        artifact_index=0,
        artifact_count=2,
    )
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nArtifact 1/2  Page 1/1  n: next artifact  r: refresh  q: quit"
    )

    _print_page_prompt(
        index=0,
        page_count=1,
        artifact_index=0,
        artifact_count=2,
        show_position=False,
    )
    assert (
        _strip_ansi(capsys.readouterr().out)
        == "\nn: next artifact  r: refresh  q: quit"
    )


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


def test_run_artifact_sequence_loop_navigates_pages_and_artifacts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    first_pages = [tmp_path / "first-1.png", tmp_path / "first-2.png"]
    second_pages = [tmp_path / "second-1.png"]
    for page in [*first_pages, *second_pages]:
        page.write_bytes(b"png")
    specs = (
        ArtifactViewSpec(tmp_path / "first.md", "markdown"),
        ArtifactViewSpec(tmp_path / "second.png", "image"),
    )
    render_calls: list[tuple[Path, str | None, Path, ArtifactImageArea | None]] = []

    def fake_render_result(path, *, kind=None, cache_dir=None, image_area=None):
        render_calls.append((Path(path), kind, Path(cache_dir), image_area))
        pages = tuple(first_pages if kind == "markdown" else second_pages)
        return ArtifactRenderResult(pages)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_pages",
        fake_render_result,
    )
    commands: list[list[str]] = []
    keys = iter(["k", "j", "n", "p", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
    )

    assert result.returncode == 0
    assert [call[:2] for call in render_calls] == [
        (tmp_path / "first.md", "markdown"),
        (tmp_path / "second.png", "image"),
    ]
    assert [call[3] for call in render_calls] == [_TEST_IMAGE_AREA, _TEST_IMAGE_AREA]
    assert commands == [
        ["clear"],
        _test_icat_command(first_pages[0]),
        ["clear"],
        _test_icat_command(first_pages[1]),
        ["clear"],
        _test_icat_command(first_pages[0]),
        ["clear"],
        _test_icat_command(second_pages[0]),
        ["clear"],
        _test_icat_command(first_pages[0]),
        ["clear"],
    ]
    output = capsys.readouterr().out
    cursor_escape = "\x1b[24;1H"
    assert output.count(cursor_escape) == 5
    stripped_output = _strip_ansi(output)
    assert output.index(cursor_escape) < output.index("j: next page")
    assert "\nj: next page  k: previous page  n: next artifact" in stripped_output
    assert "Artifact 1/2  Page 1/2  j: next page" not in stripped_output
    assert "Viewing artifact" in output
    assert "Artifact 1/2" in output
    assert "Artifact 2/2" in output
    assert "Page 2/2" in output
    assert "first.md" in output
    assert "second.png" in output
