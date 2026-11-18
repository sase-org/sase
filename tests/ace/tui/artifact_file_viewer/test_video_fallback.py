from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.ace.tui.graphics._viewer_kitty_capability import (
    _tmux_client_termname_once,
    kitty_graphics_capable,
)
from sase.ace.tui.graphics._viewer_loop_video import run_video_inspect
from sase.ace.tui.graphics._viewer_loop_video_view import _CELL_FALLBACK_BANNER
from sase.ace.tui.graphics._viewer_video_frames import FrameExtractResult
from sase.ace.tui.graphics.cell import CellImageRenderable
from sase.ace.tui.graphics.viewer import (
    ArtifactFileImageArea,
    ArtifactFileViewSpec,
    ArtifactVideoPlaybackConfig,
)

from ._helpers import _TEST_IMAGE_AREA, _strip_ansi, stub_video_inspect_service

_VIDEO_TARGET = "sase.ace.tui.graphics._viewer_loop_video_session"
_TERMINAL_TARGET = "sase.ace.tui.graphics._viewer_kitty_capability"


@pytest.fixture(autouse=True)
def _reset_kitty_graphics_cache():
    from sase.ace.tui.graphics import _viewer_kitty_capability as capability

    capability._KITTY_GRAPHICS_CACHE = None
    yield
    capability._KITTY_GRAPHICS_CACHE = None


def _write_clip(tmp_path: Path, name: str = "clip.mp4") -> Path:
    video = tmp_path / name
    video.write_bytes(b"video")
    return video


def _write_png(path: Path, size: tuple[int, int] = (64, 36)) -> Path:
    from PIL import Image

    Image.new("RGB", size, (200, 30, 30)).save(path, format="PNG")
    return path


def _stub_cell_frames(monkeypatch, tmp_path: Path) -> dict:
    """Stub the inspect service with decodable PNG frames for cell rendering."""

    stub = stub_video_inspect_service(monkeypatch, tmp_path)
    cache = stub["cache"]
    extracts = stub["extracts"]

    def fake_extract(path: object, at_seconds: float, max_px: int, **kwargs: object):
        del path, max_px, kwargs
        dest = cache / f"cell-{float(at_seconds):.3f}.png"
        _write_png(dest)
        extracts.append(float(at_seconds))
        return FrameExtractResult(path=dest, cached=False, error=None)

    monkeypatch.setattr(f"{_VIDEO_TARGET}.extract_frame", fake_extract)
    return stub


def _no_tmux(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)


def test_capability_matches_kitty_family_terms_outside_tmux(monkeypatch) -> None:
    _no_tmux(monkeypatch)
    for term, expected in (
        ("xterm-kitty", True),
        ("kitty", True),
        ("xterm-ghostty", True),
        ("ghostty", True),
        ("xterm-256color", False),
        ("tmux-256color", False),
        ("screen", False),
    ):
        monkeypatch.setenv("TERM", term)
        assert kitty_graphics_capable(force=True) is expected


def test_capability_honors_kitty_window_id(monkeypatch) -> None:
    _no_tmux(monkeypatch)
    monkeypatch.setenv("TERM", "xterm-256color")
    assert kitty_graphics_capable(force=True) is False
    monkeypatch.setenv("KITTY_WINDOW_ID", "12345")
    assert kitty_graphics_capable(force=True) is True


def test_capability_inside_tmux_reads_client_termname(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    monkeypatch.setattr(
        f"{_TERMINAL_TARGET}._tmux_client_termname_once",
        lambda **_kwargs: "xterm-kitty",
    )
    assert kitty_graphics_capable(force=True) is True
    monkeypatch.setattr(
        f"{_TERMINAL_TARGET}._tmux_client_termname_once",
        lambda **_kwargs: "tmux-256color",
    )
    assert kitty_graphics_capable(force=True) is False
    monkeypatch.setattr(
        f"{_TERMINAL_TARGET}._tmux_client_termname_once",
        lambda **_kwargs: None,
    )
    assert kitty_graphics_capable(force=True) is False


def test_tmux_client_termname_query_bounds_failures(monkeypatch) -> None:
    import subprocess as stdlib_subprocess

    def fake_timeout(*args: object, **kwargs: object):
        del args, kwargs
        raise stdlib_subprocess.TimeoutExpired(cmd="tmux", timeout=1.0)

    monkeypatch.setattr(stdlib_subprocess, "run", fake_timeout)
    assert _tmux_client_termname_once() is None

    def fake_missing(*args: object, **kwargs: object):
        del args, kwargs
        raise FileNotFoundError("tmux")

    monkeypatch.setattr(stdlib_subprocess, "run", fake_missing)
    assert _tmux_client_termname_once() is None

    def fake_rc(*args: object, **kwargs: object):
        del args, kwargs
        return stdlib_subprocess.CompletedProcess(["tmux"], 1, "", "error")

    monkeypatch.setattr(stdlib_subprocess, "run", fake_rc)
    assert _tmux_client_termname_once() is None

    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    assert kitty_graphics_capable(force=True) is False


def test_capability_caches_result_for_viewer_process(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    calls: list[str] = []

    def fake_termname(**kwargs: object) -> str:
        del kwargs
        calls.append("query")
        return "xterm-kitty"

    monkeypatch.setattr(f"{_TERMINAL_TARGET}._tmux_client_termname_once", fake_termname)
    assert kitty_graphics_capable() is True
    assert kitty_graphics_capable() is True
    assert len(calls) == 1
    assert kitty_graphics_capable(force=True) is True
    assert len(calls) == 2


def test_fallback_renders_cells_without_icat(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    video = _write_clip(tmp_path)
    stub = _stub_cell_frames(monkeypatch, tmp_path)
    monkeypatch.setattr(
        f"{_VIDEO_TARGET}.kitty_graphics_capable", lambda **_kwargs: False
    )
    commands: list[list[str]] = []

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    keys = iter(["s", "l", "q"])
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )

    assert result.action == "quit"
    assert result.returncode == 0
    output = _strip_ansi(capsys.readouterr().out)
    assert _CELL_FALLBACK_BANNER in output
    assert "\u2588" in output
    placements = [
        cmd
        for cmd in commands
        if cmd[:2] == ["kitten", "icat"] and "--clear" not in cmd
    ]
    assert placements == []
    storyboard_placements = [
        cmd
        for cmd in commands
        if "--image-id" in cmd and cmd[cmd.index("--image-id") + 1] == "2"
    ]
    assert storyboard_placements == []
    assert stub["extracts"][0] == 0.0
    assert stub["extracts"][-1] == 1.0
    assert stub["storyboards"] == []


def test_icat_failure_falls_back_to_cells(tmp_path: Path, monkeypatch, capsys) -> None:
    video = _write_clip(tmp_path)
    stub = _stub_cell_frames(monkeypatch, tmp_path)
    wide_area = ArtifactFileImageArea(columns=130, rows=24)
    commands: list[list[str]] = []

    def fake_run(cmd):
        commands.append(list(cmd))
        if cmd[:2] == ["kitten", "icat"] and "--clear" not in cmd:
            return subprocess.CompletedProcess(cmd, 1)
        return subprocess.CompletedProcess(cmd, 0)

    keys = iter(["q"])
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=wide_area,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )

    assert result.action == "quit"
    assert result.returncode == 0
    output = _strip_ansi(capsys.readouterr().out)
    assert _CELL_FALLBACK_BANNER in output
    assert "kitten icat failed with exit code 1" in output
    assert "\u2588" in output
    assert stub["extracts"] == [0.0, 0.0]


def test_cell_render_fits_frame_region(tmp_path: Path) -> None:
    from rich.console import Console

    frame = _write_png(tmp_path / "frame.png", size=(80, 48))
    renderable = CellImageRenderable.from_path(
        str(frame), columns=40, rows=12, truecolor=False
    )
    console = Console(width=40, record=True)
    console.print(renderable, end="")
    lines = console.export_text().splitlines()

    assert len(lines) == 12
    assert all(len(line) == 40 for line in lines)
