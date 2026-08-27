from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sase.ace.tui.graphics.viewer import (
    ArtifactFileImageArea,
    ArtifactRenderResult,
    ArtifactFileViewerResult,
    ArtifactFileViewSpec,
    ArtifactVideoPlaybackConfig,
    artifact_video_player_command,
    run_artifact_sequence_loop,
)

from ._helpers import _TEST_IMAGE_AREA, _strip_ansi, _test_icat_command


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
        ArtifactFileViewSpec(tmp_path / "first.md", "markdown"),
        ArtifactFileViewSpec(tmp_path / "second.png", "image"),
    )
    render_calls: list[tuple[Path, str | None, Path, ArtifactFileImageArea | None]] = []

    def fake_render_result(path, *, kind=None, cache_dir=None, image_area=None):
        render_calls.append((Path(path), kind, Path(cache_dir), image_area))
        pages = tuple(first_pages if kind == "markdown" else second_pages)
        return ArtifactRenderResult(pages)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
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


def test_run_artifact_sequence_loop_tab_focuses_return_pane_and_stays_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    specs = (ArtifactFileViewSpec(tmp_path / "first.png", "image"),)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        lambda *args, **kwargs: ArtifactRenderResult((page,)),
    )
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
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


def test_run_artifact_sequence_loop_routes_raw_file_through_text_viewer(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw = tmp_path / "data.json"
    raw.write_text("{}", encoding="utf-8")
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    specs = (
        ArtifactFileViewSpec(raw, "file"),
        ArtifactFileViewSpec(image, "image"),
    )
    render_calls: list[Path] = []

    def fake_render_result(path, *, kind=None, cache_dir=None, image_area=None):
        del kind, cache_dir, image_area
        render_calls.append(Path(path))
        return ArtifactRenderResult((page,))

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        fake_render_result,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)
    commands: list[list[str]] = []
    keys = iter(["n", "q"])

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
    assert render_calls == [image]
    assert commands == [
        ["clear"],
        [
            sys.executable,
            "-m",
            "sase",
            "pager",
            "--",
            str(raw.resolve(strict=False)),
        ],
        ["clear"],
        _test_icat_command(page),
        ["clear"],
    ]


def test_run_artifact_sequence_loop_tab_then_navigation_renders_next_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pages = [tmp_path / "page-1.png", tmp_path / "page-2.png"]
    for page in pages:
        page.write_bytes(b"png")
    specs = (ArtifactFileViewSpec(tmp_path / "first.pdf", "pdf"),)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        lambda *args, **kwargs: ArtifactRenderResult(tuple(pages)),
    )
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "j", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
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


def test_run_artifact_sequence_loop_tab_then_refresh_renders_same_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    specs = (ArtifactFileViewSpec(tmp_path / "first.png", "image"),)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        lambda *args, **kwargs: ArtifactRenderResult((page,)),
    )
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "r", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
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


def test_run_artifact_sequence_loop_zoom_redraws_current_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_page = tmp_path / "first-1.png"
    second_page = tmp_path / "second-1.png"
    for page in (first_page, second_page):
        page.write_bytes(b"png")
    specs = (
        ArtifactFileViewSpec(tmp_path / "first.md", "markdown"),
        ArtifactFileViewSpec(tmp_path / "second.png", "image"),
    )
    render_calls: list[tuple[Path, str | None]] = []

    def fake_render_result(path, *, kind=None, cache_dir=None, image_area=None):
        render_calls.append((Path(path), kind))
        pages = (first_page,) if kind == "markdown" else (second_page,)
        return ArtifactRenderResult(pages)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        fake_render_result,
    )
    commands: list[list[str]] = []
    zooms: list[bool] = []
    keys = iter(["n", "z", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_zoom() -> ArtifactFileViewerResult:
        zooms.append(True)
        return ArtifactFileViewerResult(True)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        tmux_zoom_available=True,
        toggle_zoom=fake_zoom,
    )

    assert result.returncode == 0
    assert zooms == [True]
    assert render_calls == [
        (tmp_path / "first.md", "markdown"),
        (tmp_path / "second.png", "image"),
    ]
    assert commands == [
        ["clear"],
        _test_icat_command(first_page),
        ["clear"],
        _test_icat_command(second_page),
        ["clear"],
        _test_icat_command(second_page),
        ["clear"],
    ]


def test_run_artifact_sequence_loop_repeated_tab_does_not_re_render(
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    specs = (ArtifactFileViewSpec(tmp_path / "first.png", "image"),)

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        lambda *args, **kwargs: ArtifactRenderResult((page,)),
    )
    commands: list[list[str]] = []
    selected: list[str] = []
    keys = iter(["\t", "\t", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
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


def test_run_artifact_sequence_loop_plays_video_artifact(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    specs = (ArtifactFileViewSpec(video, "file"),)
    commands: list[list[str]] = []
    keys = iter(["q"])
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_render.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "mpv" else None,
    )

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        artifact_video_player_command(video, _TEST_IMAGE_AREA),
        ["clear"],
    ]
    output = capsys.readouterr().out
    assert "Viewing artifact" in output
    assert "▶ Video" in output
    assert "r: refresh" in _strip_ansi(output)


def test_run_artifact_sequence_loop_replays_video_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = tmp_path / "clip.webm"
    video.write_bytes(b"video")
    specs = (ArtifactFileViewSpec(video, "file"),)
    commands: list[list[str]] = []
    keys = iter(["r", "q"])
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_render.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "mpv" else None,
    )

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        artifact_video_player_command(video, _TEST_IMAGE_AREA),
        ["clear"],
        artifact_video_player_command(video, _TEST_IMAGE_AREA),
        ["clear"],
    ]


def test_run_artifact_sequence_loop_navigates_video_to_image(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = tmp_path / "clip.mov"
    video.write_bytes(b"video")
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    specs = (
        ArtifactFileViewSpec(video, "file"),
        ArtifactFileViewSpec(image, "image"),
    )

    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        lambda *args, **kwargs: ArtifactRenderResult((page,)),
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_render.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "mpv" else None,
    )
    commands: list[list[str]] = []
    keys = iter(["n", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        artifact_video_player_command(video, _TEST_IMAGE_AREA),
        ["clear"],
        _test_icat_command(page),
        ["clear"],
    ]


def test_run_artifact_sequence_loop_keeps_prompt_after_mpv_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    video = tmp_path / "clip.m4v"
    video.write_bytes(b"video")
    specs = (ArtifactFileViewSpec(video, "file"),)
    commands: list[list[str]] = []
    keys = iter(["q"])
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_render.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "mpv" else None,
    )

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 2 if cmd[0] == "mpv" else 0)

    result = run_artifact_sequence_loop(
        specs,
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert commands == [
        ["clear"],
        artifact_video_player_command(video, _TEST_IMAGE_AREA),
        ["clear"],
    ]
    output = capsys.readouterr().out
    assert "mpv failed with exit code 2" in output
    assert "q: quit" in _strip_ansi(output)
