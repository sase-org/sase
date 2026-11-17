from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sase.ace.tui.graphics._viewer_loop_terminal import clear_terminal
from sase.ace.tui.graphics._viewer_trace import mark_child_ready, mark_first_visual
from sase.ace.tui.graphics.viewer import (
    ARTIFACT_VIEWER_VIDEO_CONFIG_ENV,
    ArtifactFileViewSpec,
    ArtifactRenderResult,
    ArtifactVideoPlaybackConfig,
    load_artifact_video_playback_config,
    parse_video_playback_config_env,
    run_artifact_sequence_loop,
    serialize_video_playback_config,
    view_artifact_files_in_tmux_pane,
)

from ._helpers import (
    _TEST_IMAGE_AREA,
    _patch_tmux_run,
    _patch_tmux_which,
    _test_icat_command,
    _tmux_split_env,
)


def test_video_config_snapshot_round_trip() -> None:
    config = ArtifactVideoPlaybackConfig(
        audio=True,
        loop=True,
        vo="tct",
        extra_mpv_args=("--profile=fast", "--keep-open=no"),
    )

    parsed = parse_video_playback_config_env(serialize_video_playback_config(config))

    assert parsed == config


def test_video_config_snapshot_ignores_unknown_fields() -> None:
    raw = json.dumps(
        {
            "version": 1,
            "audio": True,
            "loop": False,
            "vo": "kitty",
            "extra_mpv_args": [],
            "future_field": "ok",
        }
    )

    parsed = parse_video_playback_config_env(raw)

    assert parsed == ArtifactVideoPlaybackConfig(audio=True)


def test_parse_video_playback_config_env_falls_back(
    monkeypatch,
) -> None:
    monkeypatch.delenv(ARTIFACT_VIEWER_VIDEO_CONFIG_ENV, raising=False)
    assert parse_video_playback_config_env(None) is None
    assert parse_video_playback_config_env("") is None
    assert parse_video_playback_config_env("{") is None
    assert parse_video_playback_config_env("[]") is None
    assert parse_video_playback_config_env('{"version": 2, "vo": "tct"}') is None
    assert parse_video_playback_config_env('{"version": 1, "audio": "yes"}') is None


def test_load_artifact_video_playback_config_prefers_env(monkeypatch) -> None:
    snapshot = serialize_video_playback_config(
        ArtifactVideoPlaybackConfig(audio=True, vo="tct")
    )
    monkeypatch.setenv(ARTIFACT_VIEWER_VIDEO_CONFIG_ENV, snapshot)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_media.load_merged_artifact_video_playback_config",
        lambda: (_ for _ in ()).throw(AssertionError("merged config should not load")),
    )

    loaded = load_artifact_video_playback_config()

    assert loaded == ArtifactVideoPlaybackConfig(audio=True, vo="tct")


def test_load_artifact_video_playback_config_falls_back_to_merged(
    monkeypatch,
) -> None:
    monkeypatch.delenv(ARTIFACT_VIEWER_VIDEO_CONFIG_ENV, raising=False)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifact_file_viewer": {
                    "video": {
                        "audio": True,
                        "loop": True,
                        "vo": "tct",
                        "extra_mpv_args": ["--profile=fast"],
                    }
                }
            }
        },
    )

    loaded = load_artifact_video_playback_config()

    assert loaded == ArtifactVideoPlaybackConfig(
        audio=True,
        loop=True,
        vo="tct",
        extra_mpv_args=("--profile=fast",),
    )


def test_parent_split_ignores_stale_env_snapshot(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    stale = serialize_video_playback_config(
        ArtifactVideoPlaybackConfig(audio=True, vo="tct")
    )
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setenv(ARTIFACT_VIEWER_VIDEO_CONFIG_ENV, stale)
    _patch_tmux_which(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_media.load_merged_artifact_video_playback_config",
        lambda: ArtifactVideoPlaybackConfig(audio=False, vo="kitty"),
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    _patch_tmux_run(monkeypatch, fake_run)

    result = view_artifact_files_in_tmux_pane(
        (ArtifactFileViewSpec(artifact, "image"),)
    )

    assert result.ok is True
    env = _tmux_split_env(calls[0])
    parsed = parse_video_playback_config_env(env[ARTIFACT_VIEWER_VIDEO_CONFIG_ENV])
    assert parsed == ArtifactVideoPlaybackConfig(audio=False, vo="kitty")


def test_parent_split_passes_trace_env(tmp_path: Path, monkeypatch) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", "/tmp/tui_trace.jsonl")
    _patch_tmux_which(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_tmux.load_merged_artifact_video_playback_config",
        lambda: ArtifactVideoPlaybackConfig(),
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    _patch_tmux_run(monkeypatch, fake_run)

    result = view_artifact_files_in_tmux_pane(
        (ArtifactFileViewSpec(artifact, "image"),)
    )

    assert result.ok is True
    env = _tmux_split_env(calls[0])
    assert env["SASE_TUI_TRACE"] == "1"
    assert env["SASE_TUI_TRACE_PATH"] == "/tmp/tui_trace.jsonl"
    assert ARTIFACT_VIEWER_VIDEO_CONFIG_ENV in env


def test_importing_viewer_does_not_load_markdown_pdf() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sase.ace.tui.graphics.viewer, sys; "
            "loaded = [name for name in sys.modules "
            "if name == 'sase.attachments.markdown_pdf']; "
            "raise SystemExit(0 if not loaded else 1)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_clear_terminal_writes_ansi_and_spawns_no_subprocess(
    capsys,
    monkeypatch,
) -> None:
    calls: list[object] = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0] if args else [], 0)

    monkeypatch.setattr("subprocess.run", fake_run)
    clear_terminal()

    assert calls == []
    assert capsys.readouterr().out == "\x1b[H\x1b[2J\x1b[3J"


def test_child_trace_writes_nothing_when_disabled(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "tui_trace.jsonl"
    monkeypatch.delenv("SASE_TUI_TRACE", raising=False)
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_trace._first_visual_emitted",
        False,
    )

    mark_child_ready("image")
    mark_first_visual("image")

    assert not log.exists()


def test_child_trace_writes_well_formed_rows(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    monkeypatch.setenv("SASE_ARTIFACT_VIEWER_OPEN_ID", "open-1")
    monkeypatch.setenv("SASE_ARTIFACT_VIEWER_OPEN_T0", "1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_trace._first_visual_emitted",
        False,
    )

    mark_child_ready("video")
    mark_first_visual("video")
    mark_first_visual("video")

    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [row["span"] for row in rows] == [
        "artifact_viewer.child_ready",
        "artifact_viewer.first_visual",
    ]
    for row in rows:
        assert row["mode"] == "video"
        assert row["open_id"] == "open-1"
        assert isinstance(row["elapsed_ms"], float)
        assert isinstance(row["since_select_ms"], float)


def test_sequence_loop_streams_icat_inside_tmux(
    tmp_path: Path,
    monkeypatch,
) -> None:
    page = tmp_path / "page-1.png"
    page.write_bytes(b"png")
    specs = (ArtifactFileViewSpec(tmp_path / "first.png", "image"),)
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.render_artifact_file_pages",
        lambda *args, **kwargs: ArtifactRenderResult((page,)),
    )
    commands: list[list[str]] = []
    keys = iter(["q"])

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
    streamed = kitten_stream_command(page)
    assert commands == [streamed]


def kitten_stream_command(page: Path) -> list[str]:
    command = _test_icat_command(page)
    place_index = command.index("--place")
    return [
        *command[: place_index + 2],
        "--transfer-mode",
        "stream",
        *command[place_index + 2 :],
    ]
