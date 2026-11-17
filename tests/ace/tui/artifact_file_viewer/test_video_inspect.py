from __future__ import annotations

import subprocess
from pathlib import Path

from sase.ace.tui.graphics._viewer_loop_terminal import kitten_icat_clear_command
from sase.ace.tui.graphics._viewer_loop_video import (
    _assemble_inspect_key,
    _clamp_timestamp,
    _compute_inspect_layout,
    _decode_inspect_key,
    _decile_timestamp,
    _format_inspect_status,
    _snap_timestamp,
    _step_timestamp,
    run_video_inspect,
)
from sase.ace.tui.graphics.viewer import (
    ArtifactFileImageArea,
    ArtifactFileViewerResult,
    ArtifactFileViewSpec,
    ArtifactRenderResult,
    ArtifactVideoPlaybackConfig,
    artifact_video_player_command,
    run_artifact_sequence_loop,
)

from ._helpers import _TEST_IMAGE_AREA, _strip_ansi, stub_video_inspect_service


class _FakeScrub:
    def __init__(
        self,
        *,
        done: bool = True,
        fps: float = 1.0,
        frames: tuple[Path, ...] = (),
        progress: float = 1.0,
    ) -> None:
        self.done = done
        self.fps = fps
        self.frame_paths = frames
        self.progress = progress
        self.cancelled = False

    def nearest(self, at_seconds: float) -> Path | None:
        if not self.frame_paths:
            return None
        index = int(round(float(at_seconds) * self.fps))
        index = max(0, min(index, len(self.frame_paths) - 1))
        return self.frame_paths[index]

    def cancel(self) -> None:
        self.cancelled = True


def _write_clip(tmp_path: Path, name: str = "clip.mp4") -> Path:
    video = tmp_path / name
    video.write_bytes(b"video")
    return video


def _inspect_layout(area: ArtifactFileImageArea = _TEST_IMAGE_AREA):
    return _compute_inspect_layout(
        area, storyboard_enabled=True, pane_rows=area.top + area.rows + 2
    )


def test_decode_inspect_key_maps_arrow_sequences() -> None:
    assert _decode_inspect_key("\x1b[C") == "right"
    assert _decode_inspect_key("\x1b[D") == "left"
    assert _decode_inspect_key("\x1bOC") == "right"
    assert _decode_inspect_key("\x1bOD") == "left"
    assert _decode_inspect_key("l") == "l"


def test_assemble_inspect_key_joins_arrow_bytes_split_across_reads() -> None:
    chunks = [b"\x1b", b"[", b"C"]

    def read_chunk(_timeout: float | None) -> bytes | None:
        return chunks.pop(0) if chunks else None

    assert _assemble_inspect_key(read_chunk, timeout=0.05) == "right"


def test_assemble_inspect_key_times_out_without_input() -> None:
    assert _assemble_inspect_key(lambda _timeout: None, timeout=0.0) is None


def test_assemble_inspect_key_lone_escape_does_not_steal_next_key() -> None:
    chunks = [b"\x1b"]

    def read_chunk(_timeout: float | None) -> bytes | None:
        return chunks.pop(0) if chunks else None

    assert _assemble_inspect_key(read_chunk, timeout=0.05, esc_timeout=0.0) == "\x1b"


def test_step_and_decile_math_clamps_at_both_ends() -> None:
    assert _clamp_timestamp(-1.0, 7.0) == 0.0
    assert _clamp_timestamp(9.0, 7.0) == 7.0
    assert _step_timestamp(0.0, 1.0, 7.0) == 1.0
    assert _step_timestamp(0.2, -1.0, 7.0) == 0.0
    assert _step_timestamp(6.5, 1.0, 7.0) == 7.0
    assert _decile_timestamp(0, 10.0) == 0.0
    assert _decile_timestamp(9, 10.0) == 9.0
    assert _decile_timestamp(3, None) == 0.0


def test_snap_timestamp_uses_completed_scrub_track(tmp_path: Path) -> None:
    frames = tuple(tmp_path / f"frame-{index:04d}.png" for index in range(8))
    for frame in frames:
        frame.write_bytes(b"PNG")
    scrub = _FakeScrub(done=True, fps=1.0, frames=frames)

    assert _snap_timestamp(2.4, scrub) == 2.0
    assert _step_timestamp(0.0, 2.4, 7.0, scrub=scrub, snap=True) == 2.0


def test_format_inspect_status_includes_bar_and_scrub_progress() -> None:
    line = _format_inspect_status(2.0, 7.0, scrub_progress=0.4)
    assert line.startswith("00:02.0 / 00:07.0")
    assert "scrub 40%" in line
    assert ">" in line


def test_storyboard_auto_hides_on_small_panes() -> None:
    small = ArtifactFileImageArea(columns=80, rows=10, top=0)
    hidden = _compute_inspect_layout(small, storyboard_enabled=True, pane_rows=12)
    shown = _compute_inspect_layout(
        _TEST_IMAGE_AREA, storyboard_enabled=True, pane_rows=26
    )

    assert hidden.show_storyboard is False
    assert hidden.storyboard is None
    assert shown.show_storyboard is True
    assert shown.storyboard is not None
    assert shown.storyboard.rows >= 5


def test_coalesced_l_presses_render_once_at_plus_five_seconds(
    tmp_path: Path, monkeypatch
) -> None:
    video = _write_clip(tmp_path)
    stub = stub_video_inspect_service(monkeypatch, tmp_path)
    keys = iter(["l", "l", "l", "l", "l", "q"])
    commands: list[list[str]] = []

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )

    assert result.action == "quit"
    assert stub["extracts"][0] == 0.0
    assert stub["extracts"][-1] == 5.0
    assert stub["extracts"].count(5.0) == 1
    frame_renders = [
        cmd
        for cmd in commands
        if cmd
        and cmd[0] == "kitten"
        and "--image-id" in cmd
        and cmd[cmd.index("--image-id") + 1] == "1"
    ]
    assert len(frame_renders) == 2
    assert commands[-1] == kitten_icat_clear_command()


def test_storyboard_toggle_hides_strip(tmp_path: Path, monkeypatch, capsys) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    keys = iter(["s", "q"])
    commands: list[list[str]] = []

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )

    assert result.action == "quit"
    output = _strip_ansi(capsys.readouterr().out)
    assert "h/l: seek" in output
    layout_after_toggle = _compute_inspect_layout(
        _TEST_IMAGE_AREA, storyboard_enabled=False, pane_rows=26
    )
    assert layout_after_toggle.show_storyboard is False


def test_space_dispatch_matrix(tmp_path: Path, monkeypatch, capsys) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    config = ArtifactVideoPlaybackConfig()
    keys = iter([" ", "q"])
    commands: list[list[str]] = []

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=config,
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )
    assert result.action == "quit"
    assert all(cmd[0] != "mpv" for cmd in commands)
    assert "in-pane playback is unavailable here" in capsys.readouterr().out

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    keys = iter([" ", "q"])
    commands.clear()
    layout = _inspect_layout()
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=config,
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )
    assert result.action == "quit"
    assert artifact_video_player_command(video, layout.frame, config) in commands

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video.shutil.which",
        lambda tool: None if tool == "mpv" else f"/usr/bin/{tool}",
    )
    keys = iter([" ", "q"])
    commands.clear()
    run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=config,
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=fake_run,
    )
    assert all(cmd[0] != "mpv" for cmd in commands)


def test_inspect_outcomes_for_n_p_and_q(tmp_path: Path, monkeypatch) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    spec = ArtifactFileViewSpec(video, "file")

    def _run(keys):
        iterator = iter(keys)
        return run_video_inspect(
            spec,
            cache_root=tmp_path / "cache",
            video_config=ArtifactVideoPlaybackConfig(),
            image_area=_TEST_IMAGE_AREA,
            read_key=lambda: next(iterator),
            run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
            artifact_index=1,
            artifact_count=3,
        )

    assert _run(["q"]).action == "quit"
    assert _run(["n"]).action == "next"
    assert _run(["p"]).action == "previous"


def test_resize_re_renders_when_terminal_size_changes(
    tmp_path: Path, monkeypatch
) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    sizes = [
        os_terminal_size(90, 30),
        os_terminal_size(90, 40),
        os_terminal_size(90, 40),
    ]

    def fake_size(**kwargs):
        del kwargs
        return sizes.pop(0) if len(sizes) > 1 else sizes[0]

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video.shutil.get_terminal_size", fake_size
    )
    keys = iter([None, "q"])
    renders = {"count": 0}

    def fake_run(cmd):
        if cmd and cmd[0] == "kitten" and "--image-id" in cmd:
            renders["count"] += 1
        return subprocess.CompletedProcess(cmd, 0)

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        read_key=lambda **_kwargs: next(keys),
        run_command=fake_run,
    )

    assert result.action == "quit"
    assert renders["count"] >= 2


def os_terminal_size(columns: int, lines: int):
    import os

    return os.terminal_size((columns, lines))


def test_background_scrub_is_cancelled_on_exit(tmp_path: Path, monkeypatch) -> None:
    video = _write_clip(tmp_path)
    scrub = _FakeScrub(done=False, progress=0.2)
    stub_video_inspect_service(monkeypatch, tmp_path, scrub=scrub)
    keys = iter(["q"])

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )

    assert result.action == "quit"
    assert scrub.cancelled is True


def test_sequence_loop_inspects_video_then_navigates_to_image(
    tmp_path: Path, monkeypatch
) -> None:
    video = _write_clip(tmp_path, "clip.mov")
    image = tmp_path / "image.png"
    image.write_bytes(b"png")
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    stub = stub_video_inspect_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        lambda *args, **kwargs: ArtifactRenderResult((page,)),
    )
    commands: list[list[str]] = []
    keys = iter(["n", "q"])

    def fake_run(cmd):
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        (
            ArtifactFileViewSpec(video, "file"),
            ArtifactFileViewSpec(image, "image"),
        ),
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert stub["extracts"][0] == 0.0
    assert any(cmd[0] == "kitten" and "--image-id" in cmd for cmd in commands)
    assert ["kitten", "icat", "--clear"] in commands
    from ._helpers import _test_icat_command

    assert _test_icat_command(page) in commands


def test_tab_returns_to_ace_pane(tmp_path: Path, monkeypatch) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    selected: list[str] = []
    keys = iter(["\t", "q"])

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_artifact_sequence_loop(
        (ArtifactFileViewSpec(video, "file"),),
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        image_area=_TEST_IMAGE_AREA,
        return_pane_id="%9",
        select_pane=fake_select,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert selected == ["%9"]


def test_zoom_re_renders(tmp_path: Path, monkeypatch) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    zoomed: list[int] = []
    keys = iter(["z", "q"])

    def fake_zoom() -> ArtifactFileViewerResult:
        zoomed.append(1)
        return ArtifactFileViewerResult(True)

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        tmux_zoom_available=True,
        toggle_zoom=fake_zoom,
    )

    assert result.action == "quit"
    assert zoomed == [1]


def test_tab_preserves_playhead(tmp_path: Path, monkeypatch) -> None:
    video = _write_clip(tmp_path)
    stub = stub_video_inspect_service(monkeypatch, tmp_path)
    selected: list[str] = []
    keys = iter(["l", "\t", "l", "q"])

    def fake_select(pane_id: str) -> ArtifactFileViewerResult:
        selected.append(pane_id)
        return ArtifactFileViewerResult(True)

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        return_pane_id="%9",
        select_pane=fake_select,
    )

    assert result.action == "quit"
    assert selected == ["%9"]
    assert stub["extracts"][0] == 0.0
    assert stub["extracts"][-1] == 2.0


def test_frame_step_uses_source_fps(tmp_path: Path, monkeypatch) -> None:
    video = _write_clip(tmp_path)
    stub = stub_video_inspect_service(monkeypatch, tmp_path, fps=10.0)
    keys = iter([".", "q"])

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )

    assert result.action == "quit"
    assert 0.1 in stub["extracts"]


def test_missing_kitten_keeps_inspect_alive(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video.shutil.which",
        lambda tool: None if tool == "kitten" else f"/usr/bin/{tool}",
    )
    keys = iter(["q"])

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )

    assert result.action == "quit"
    assert result.returncode == 0
    assert "kitten executable not found" in capsys.readouterr().out


def test_decile_jump_seeks_and_renders(tmp_path: Path, monkeypatch) -> None:
    video = _write_clip(tmp_path)
    stub = stub_video_inspect_service(monkeypatch, tmp_path, duration=10.0)
    keys = iter(["5", "q"])

    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )

    assert result.action == "quit"
    assert 5.0 in stub["extracts"]
