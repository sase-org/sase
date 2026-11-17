from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.ace.tui.graphics._viewer_loop_media import display_video_artifact
from sase.ace.tui.graphics._viewer_video_media import (
    VideoMetadata,
    _extract_video_still,
    _terminal_pixel_width,
    _video_still_extraction_command,
    ffprobe_metadata_command,
    format_video_metadata_summary,
    parse_ffprobe_metadata,
    probe_video_metadata,
    video_still_preview_required,
)
from sase.ace.tui.graphics.viewer import (
    ArtifactFileViewSpec,
    ArtifactVideoPlaybackConfig,
    artifact_video_motion_command,
    run_artifact_sequence_loop,
    validate_artifact_file_viewer_dependencies,
)

from ._helpers import _TEST_IMAGE_AREA, _strip_ansi

_FFPROBE_PAYLOAD = {
    "streams": [
        {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 2560,
            "height": 1548,
            "avg_frame_rate": "30000/1001",
        }
    ],
    "format": {"duration": "6.123", "size": "1234567"},
}

_FFPROBE_TIMEOUT_SECONDS = 5.0
_FFMPEG_TIMEOUT_SECONDS = 10.0


def _present_tools(tool: str) -> str | None:
    return f"/usr/bin/{tool}"


def _write_clip(tmp_path: Path, name: str = "clip.mp4") -> Path:
    video = tmp_path / name
    video.write_bytes(b"video")
    return video


def _fake_capture_factory(
    calls: list[tuple[list[str], float]],
    *,
    ffprobe_payload: dict | None = _FFPROBE_PAYLOAD,
    ffmpeg_returncode: int = 0,
) -> object:
    def fake_capture(
        command: object, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        argv = list(command)  # type: ignore[arg-type]
        calls.append((argv, timeout))
        if argv[0] == "ffprobe":
            return subprocess.CompletedProcess(
                argv, 0, stdout=json.dumps(ffprobe_payload), stderr=""
            )
        if argv[0] == "ffmpeg":
            if ffmpeg_returncode == 0:
                Path(argv[-1]).write_bytes(b"PNG")
            return subprocess.CompletedProcess(
                argv, ffmpeg_returncode, stdout="", stderr=""
            )
        raise AssertionError(f"unexpected command: {argv}")

    return fake_capture


def test_video_still_preview_required_matches_topology(monkeypatch) -> None:
    kitty = ArtifactVideoPlaybackConfig(vo="kitty")
    tct = ArtifactVideoPlaybackConfig(vo="tct")

    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    assert video_still_preview_required(kitty) is True
    assert video_still_preview_required(tct) is False

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert video_still_preview_required(kitty) is False
    assert video_still_preview_required(tct) is False


def test_ffprobe_metadata_command(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)

    assert ffprobe_metadata_command(video) == [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-select_streams",
        "v:0",
        str(video.resolve(strict=False)),
    ]


def test_video_still_extraction_command(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    dest = tmp_path / "cache" / "video-still-0.png"

    assert _video_still_extraction_command(video, dest, 1600) == [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        "0",
        "-i",
        str(video.resolve(strict=False)),
        "-frames:v",
        "1",
        "-vf",
        "scale=min(iw\\,1600):-2",
        str(dest),
    ]


def test_parse_ffprobe_metadata_reads_first_video_stream() -> None:
    metadata = parse_ffprobe_metadata(_FFPROBE_PAYLOAD)

    assert metadata == VideoMetadata(
        duration_seconds=6.123,
        width=2560,
        height=1548,
        fps=30000 / 1001,
        codec="h264",
        size_bytes=1234567,
    )
    assert (
        format_video_metadata_summary(metadata)
        == "0:06 \u00b7 2560\u00d71548 \u00b7 30 fps \u00b7 h264 \u00b7 1.2 MB"
    )


def test_parse_ffprobe_metadata_tolerates_missing_streams() -> None:
    metadata = parse_ffprobe_metadata({"format": {"duration": "7.5"}})

    assert metadata.duration_seconds == 7.5
    assert metadata.width is None
    assert metadata.fps is None
    assert format_video_metadata_summary(metadata) == "0:07"


def test_parse_ffprobe_metadata_falls_back_to_r_frame_rate() -> None:
    metadata = parse_ffprobe_metadata(
        {
            "streams": [
                {
                    "codec_type": "video",
                    "avg_frame_rate": "0/0",
                    "r_frame_rate": "25/1",
                }
            ],
            "format": {},
        }
    )

    assert metadata.fps == 25.0
    assert format_video_metadata_summary(metadata) == "25 fps"


def test_parse_ffprobe_metadata_rejects_zero_frame_rate() -> None:
    metadata = parse_ffprobe_metadata(
        {"streams": [{"codec_type": "video", "avg_frame_rate": "0/0"}]},
    )

    assert metadata.fps is None


def test_format_video_metadata_summary_returns_none_when_empty() -> None:
    assert format_video_metadata_summary(VideoMetadata()) is None


def test_terminal_pixel_width_falls_back_without_pixels(monkeypatch) -> None:
    import io

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_media.stdout", io.BytesIO()
    )

    assert _terminal_pixel_width() == 1600


def test_still_dispatch_runs_probe_extract_and_icat_without_mpv(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    video = _write_clip(tmp_path)
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    from ._helpers import stub_video_inspect_service

    stub_video_inspect_service(monkeypatch, tmp_path)
    commands: list[list[str]] = []
    keys = iter(["q"])

    def fake_run(cmd) -> subprocess.CompletedProcess:
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        (ArtifactFileViewSpec(video, "file"),),
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert result.warnings == ()
    assert all(cmd[0] != "mpv" for cmd in commands if cmd)
    output = capsys.readouterr().out
    assert "Viewing artifact" in output
    assert "h/l: seek" in _strip_ansi(output)
    assert any(cmd and cmd[0] == "kitten" and "--image-id" in cmd for cmd in commands)


def test_still_dispatch_with_tct_vo_inside_tmux_runs_mpv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = _write_clip(tmp_path)
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    from ._helpers import stub_video_inspect_service
    from sase.ace.tui.graphics._viewer_loop_video import _compute_inspect_layout

    stub_video_inspect_service(monkeypatch, tmp_path)
    commands: list[list[str]] = []
    keys = iter([" ", "q"])
    config = ArtifactVideoPlaybackConfig(vo="tct")

    def fake_run(cmd) -> subprocess.CompletedProcess:
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0)

    result = run_artifact_sequence_loop(
        (ArtifactFileViewSpec(video, "file"),),
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=fake_run,
        image_area=_TEST_IMAGE_AREA,
        video_config=config,
    )

    assert result.returncode == 0
    layout = _compute_inspect_layout(
        _TEST_IMAGE_AREA, storyboard_enabled=True, pane_rows=26
    )
    assert any(cmd[0] == "mpv" and "--profile=sw-fast" in cmd for cmd in commands)
    assert artifact_video_motion_command(
        video, layout.frame, config, at_seconds=0.0, shm_available=False
    ) in commands or any(
        cmd[0] == "mpv" and "--profile=sw-fast" in cmd for cmd in commands
    )


def test_still_r_key_rerenders(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = _write_clip(tmp_path)
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    from ._helpers import stub_video_inspect_service

    stub = stub_video_inspect_service(monkeypatch, tmp_path)
    keys = iter(["r", "q"])

    result = run_artifact_sequence_loop(
        (ArtifactFileViewSpec(video, "file"),),
        cache_root=tmp_path / "cache",
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        image_area=_TEST_IMAGE_AREA,
        video_config=ArtifactVideoPlaybackConfig(),
    )

    assert result.returncode == 0
    assert stub["extracts"].count(0.0) >= 2


def _display_still(
    tmp_path: Path,
    monkeypatch,
    missing: frozenset[str] = frozenset(),
    *,
    ffmpeg_returncode: int = 0,
    icat_returncode: int = 0,
) -> tuple[object, list[list[str]]]:
    from sase.ace.tui.graphics import _viewer_video_media

    video = _write_clip(tmp_path)
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")

    def fake_which(tool: str) -> str | None:
        if tool in missing:
            return None
        return f"/usr/bin/{tool}"

    monkeypatch.setattr(_viewer_video_media.shutil, "which", fake_which)
    captured: list[tuple[list[str], float]] = []
    monkeypatch.setattr(
        _viewer_video_media,
        "_run_capture",
        _fake_capture_factory(captured, ffmpeg_returncode=ffmpeg_returncode),
    )
    commands: list[list[str]] = []

    def fake_run(cmd) -> subprocess.CompletedProcess:
        commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, icat_returncode)

    result = display_video_artifact(
        ArtifactFileViewSpec(video, "file"),
        _TEST_IMAGE_AREA,
        fake_run,
        video_config=ArtifactVideoPlaybackConfig(),
        cache_root=tmp_path / "cache",
    )
    return result, commands


def test_missing_ffprobe_keeps_viewer_alive_without_metadata(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    result, _ = _display_still(tmp_path, monkeypatch, frozenset({"ffprobe"}))

    assert result.returncode == 0
    assert result.warnings == ()
    assert result.still_preview is True
    assert [notice.code for notice in result.notices] == ["missing_ffprobe"]
    assert all(notice.tool == "ffprobe" for notice in result.notices)
    output = capsys.readouterr().out
    assert "ffprobe executable not found" in output
    assert "\u25b6 Video" in _strip_ansi(output)
    assert "0:06" not in output


def test_missing_ffmpeg_keeps_viewer_alive_without_still(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    result, commands = _display_still(tmp_path, monkeypatch, frozenset({"ffmpeg"}))

    assert result.returncode == 0
    assert result.warnings == ()
    assert result.still_preview is True
    assert [notice.code for notice in result.notices] == ["missing_ffmpeg"]
    assert result.command == ()
    assert all(cmd[0] != "kitten" for cmd in commands)
    assert "ffmpeg executable not found" in capsys.readouterr().out


def test_missing_kitten_keeps_viewer_alive_without_display(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    result, commands = _display_still(tmp_path, monkeypatch, frozenset({"kitten"}))

    assert result.returncode == 0
    assert result.warnings == ()
    assert [notice.code for notice in result.notices] == ["missing_kitten"]
    assert result.command == ()
    assert all(cmd[0] != "kitten" for cmd in commands)
    assert "kitten executable not found" in capsys.readouterr().out


def test_failed_extraction_keeps_viewer_alive(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    result, commands = _display_still(tmp_path, monkeypatch, ffmpeg_returncode=1)

    assert result.returncode == 0
    assert result.warnings == ()
    assert [notice.code for notice in result.notices] == ["ffmpeg_still_failed"]
    assert all(notice.tool == "ffmpeg" for notice in result.notices)
    assert result.command == ()
    assert all(cmd[0] != "kitten" for cmd in commands)
    assert "ffmpeg could not extract" in capsys.readouterr().out


def test_failed_icat_keeps_viewer_alive(tmp_path: Path, monkeypatch, capsys) -> None:
    result, _ = _display_still(tmp_path, monkeypatch, icat_returncode=2)

    assert result.returncode == 0
    assert result.warnings == ()
    assert [notice.code for notice in result.notices] == ["kitten_icat_failed"]
    assert result.command == ()
    assert "kitten icat failed with exit code 2" in capsys.readouterr().out


def test_probe_video_metadata_returns_none_for_invalid_json(
    tmp_path: Path, monkeypatch
) -> None:
    video = _write_clip(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_media.shutil.which", _present_tools
    )
    captured: list[tuple[list[str], float]] = []
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_media._run_capture",
        _fake_capture_factory(captured, ffprobe_payload=None),
    )

    assert probe_video_metadata(video) is None


def test_probe_video_metadata_returns_none_without_ffprobe(
    tmp_path: Path, monkeypatch
) -> None:
    video = _write_clip(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_media.shutil.which",
        lambda _tool: None,
    )

    assert probe_video_metadata(video) is None


def test_extract_video_still_returns_false_without_ffmpeg(
    tmp_path: Path, monkeypatch
) -> None:
    video = _write_clip(tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_media.shutil.which",
        lambda _tool: None,
    )

    assert _extract_video_still(video, tmp_path / "still.png") is False


def test_validate_video_dependencies_use_still_tools_inside_tmux(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    warnings = validate_artifact_file_viewer_dependencies(
        "video", video_config=ArtifactVideoPlaybackConfig()
    )

    assert [warning.code for warning in warnings] == [
        "missing_ffprobe",
        "missing_ffmpeg",
        "missing_kitten",
    ]


def test_validate_video_dependencies_use_inspect_tools_with_tct_vo_inside_tmux(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1/default,123,0")
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    warnings = validate_artifact_file_viewer_dependencies(
        "video", video_config=ArtifactVideoPlaybackConfig(vo="tct")
    )

    assert [warning.code for warning in warnings] == [
        "missing_ffprobe",
        "missing_ffmpeg",
        "missing_kitten",
    ]


def test_validate_video_dependencies_use_inspect_tools_outside_tmux(
    monkeypatch,
) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    warnings = validate_artifact_file_viewer_dependencies(
        "video", video_config=ArtifactVideoPlaybackConfig()
    )

    assert [warning.code for warning in warnings] == [
        "missing_ffprobe",
        "missing_ffmpeg",
        "missing_kitten",
    ]
