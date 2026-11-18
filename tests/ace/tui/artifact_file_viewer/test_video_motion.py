from __future__ import annotations

import subprocess
from pathlib import Path

from sase.ace.tui.graphics._viewer_loop_media import (
    ArtifactVideoPlaybackConfig,
    artifact_video_player_command,
    load_merged_artifact_video_playback_config,
)
from sase.ace.tui.graphics._viewer_video_motion import (
    _kitty_shm_available as kitty_shm_available,
    artifact_video_motion_command,
    build_native_open_command,
    motion_playback_block_reason,
)
from sase.ace.tui.graphics._viewer_loop_video import run_video_inspect
from sase.ace.tui.graphics.viewer import ArtifactFileViewSpec

from ._helpers import _TEST_IMAGE_AREA, _strip_ansi, stub_video_inspect_service


def _write_clip(tmp_path: Path) -> Path:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    return video


def test_motion_command_golden_silent_no_shm(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    config = ArtifactVideoPlaybackConfig()
    command = artifact_video_motion_command(
        video,
        _TEST_IMAGE_AREA,
        config,
        at_seconds=2.5,
        shm_available=False,
    )
    assert command[0] == "mpv"
    assert "--no-config" in command
    assert "--profile=sw-fast" in command
    assert "--vo=kitty" in command
    assert "--start=2.500" in command
    assert "--audio=no" in command
    assert "--vo-kitty-use-shm=yes" not in command
    assert "--mute=yes" not in command
    assert command[-2:] == ["--", str(video.resolve(strict=False))]


def test_motion_command_golden_audio_loop_shm_and_extra(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    config = ArtifactVideoPlaybackConfig(
        audio=True,
        loop=True,
        vo="kitty",
        extra_mpv_args=("--user-flag",),
    )
    command = artifact_video_motion_command(
        video, _TEST_IMAGE_AREA, config, at_seconds=0.0, shm_available=True
    )
    assert "--audio=no" not in command
    assert "--loop-file=inf" in command
    assert "--vo-kitty-use-shm=yes" in command
    assert command[-3:] == ["--user-flag", "--", str(video.resolve(strict=False))]


def test_motion_command_non_kitty_vo_has_no_kitty_flags(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    config = ArtifactVideoPlaybackConfig(vo="tct")
    command = artifact_video_motion_command(
        video, _TEST_IMAGE_AREA, config, at_seconds=1.0, shm_available=True
    )
    assert "--vo=tct" in command
    assert not any(part.startswith("--vo-kitty-") for part in command)
    assert "--start=1.000" in command


def test_player_command_unchanged_for_same_inputs(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    config = ArtifactVideoPlaybackConfig()
    command = artifact_video_player_command(video, _TEST_IMAGE_AREA, config)
    assert "--profile=sw-fast" not in command
    assert "--keep-open=yes" in command
    assert "--mute=yes" in command
    assert "--audio=no" not in command


def test_motion_block_reason_matrix(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_motion.shutil.which",
        lambda tool: f"/usr/bin/{tool}",
    )
    assert motion_playback_block_reason(ArtifactVideoPlaybackConfig()) is None
    assert "poster" in (
        motion_playback_block_reason(ArtifactVideoPlaybackConfig(backend="poster"))
        or ""
    )
    assert "tct" not in (
        motion_playback_block_reason(ArtifactVideoPlaybackConfig(vo="tct"))
        or "forbidden"
    )
    assert (
        motion_playback_block_reason(
            ArtifactVideoPlaybackConfig(vo="tct"), mpv_available=True
        )
        is None
    )


def test_motion_block_forbidden_topology_and_missing_mpv(monkeypatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_motion.shutil.which",
        lambda tool: f"/usr/bin/{tool}",
    )
    reason = motion_playback_block_reason(ArtifactVideoPlaybackConfig())
    assert reason is not None and "unavailable here" in reason

    # Non-kitty vo inside tmux is allowed when mpv exists.
    allowed = motion_playback_block_reason(
        ArtifactVideoPlaybackConfig(vo="tct"), mpv_available=True
    )
    assert allowed is None

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    missing = motion_playback_block_reason(
        ArtifactVideoPlaybackConfig(), mpv_available=False
    )
    assert missing is not None and "mpv" in missing
    explicit = motion_playback_block_reason(
        ArtifactVideoPlaybackConfig(backend="mpv"), mpv_available=False
    )
    assert explicit is not None and "mpv is not installed" in explicit


def test_open_command_template_and_append(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    configured = ArtifactVideoPlaybackConfig(
        open_command=("vlc", "{path}", "--fullscreen")
    )
    argv, notice = build_native_open_command(video, configured)
    assert notice is None
    assert argv == ["vlc", str(video.resolve(strict=False)), "--fullscreen"]

    appended = ArtifactVideoPlaybackConfig(open_command=("mpv",))
    argv, _ = build_native_open_command(video, appended)
    assert argv == ["mpv", str(video.resolve(strict=False))]


def test_open_command_platform_defaults_and_notice(tmp_path: Path) -> None:
    video = _write_clip(tmp_path)
    argv, _ = build_native_open_command(
        video, ArtifactVideoPlaybackConfig(), platform="darwin"
    )
    assert argv == ["open", str(video.resolve(strict=False))]

    argv, _ = build_native_open_command(
        video,
        ArtifactVideoPlaybackConfig(),
        platform="linux",
        display=":0",
        wayland_display=None,
        ssh_connection="",
    )
    assert argv == ["xdg-open", str(video.resolve(strict=False))]

    argv, notice = build_native_open_command(
        video,
        ArtifactVideoPlaybackConfig(),
        platform="linux",
        display=":0",
        wayland_display=None,
        ssh_connection="1.2.3.4 22 5.6.7.8 22",
    )
    assert argv is None
    assert notice is not None and "open_command" in notice

    argv, notice = build_native_open_command(
        video, ArtifactVideoPlaybackConfig(), platform="linux"
    )
    assert argv is None
    assert notice is not None and "open_command" in notice


def test_o_key_spawns_configured_player_detached(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    config = ArtifactVideoPlaybackConfig(open_command=("vlc", "{path}"))
    spawned: list[dict] = []

    class _FakePopen:
        def __init__(self, argv, **kwargs) -> None:
            spawned.append({"argv": list(argv), **kwargs})

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video_view.subprocess.Popen", _FakePopen
    )
    keys = iter(["o", "q"])
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=config,
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )
    assert result.action == "quit"
    assert len(spawned) == 1
    assert spawned[0]["argv"] == ["vlc", str(video.resolve(strict=False))]
    assert spawned[0]["start_new_session"] is True
    assert "native player" in capsys.readouterr().out


def test_o_key_without_player_names_open_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    config = ArtifactVideoPlaybackConfig()
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video_view.build_native_open_command",
        lambda *args, **kwargs: (
            None,
            "no native player available here — set open_command",
        ),
    )
    keys = iter(["o", "q"])
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=config,
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
    )
    assert result.action == "quit"
    assert "no native player" in _strip_ansi(capsys.readouterr().out)


def test_degraded_notice_names_missing_tool_and_keeps_keys(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    video = _write_clip(tmp_path)
    stub_video_inspect_service(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_loop_video_session.shutil.which",
        lambda tool: None if tool == "ffprobe" else f"/usr/bin/{tool}",
    )
    keys = iter(["n"])
    result = run_video_inspect(
        ArtifactFileViewSpec(video, "file"),
        cache_root=tmp_path / "cache",
        video_config=ArtifactVideoPlaybackConfig(),
        image_area=_TEST_IMAGE_AREA,
        read_key=lambda: next(keys),
        run_command=lambda cmd: subprocess.CompletedProcess(cmd, 0),
        artifact_index=0,
        artifact_count=2,
    )
    assert result.action == "next"
    assert "ffprobe" in _strip_ansi(capsys.readouterr().out)


def test_config_coercion_for_backend_and_open_command(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {
            "ace": {
                "artifact_file_viewer": {
                    "video": {
                        "backend": "mpv",
                        "open_command": "vlc {path} --fullscreen",
                        "extra_mpv_args": "--profile=fast",
                    }
                }
            }
        },
    )
    import os

    os.environ.pop("SASE_ARTIFACT_VIEWER_VIDEO_CONFIG_ENV", None)
    loaded = load_merged_artifact_video_playback_config()
    assert loaded.backend == "mpv"
    assert loaded.open_command == ("vlc", "{path}", "--fullscreen")
    assert loaded.extra_mpv_args == ("--profile=fast",)

    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"artifact_file_viewer": {"video": {"backend": "kitty"}}}},
    )
    assert load_merged_artifact_video_playback_config().backend == "auto"


def test_video_config_snapshot_carries_backend_and_open_command() -> None:
    from sase.ace.tui.graphics._viewer_loop_media import (
        parse_video_playback_config_env,
        serialize_video_playback_config,
    )

    config = ArtifactVideoPlaybackConfig(
        backend="mpv",
        open_command=("vlc", "{path}"),
        extra_mpv_args=("--profile=fast",),
    )
    parsed = parse_video_playback_config_env(serialize_video_playback_config(config))
    assert parsed == config

    import json

    bad = json.dumps({"version": 1, "backend": "kitty"})
    assert parse_video_playback_config_env(bad) is None


def _reset_shm_cache() -> None:
    from sase.ace.tui.graphics import _viewer_video_motion as media

    media._KITTY_SHM_CACHE = None


def test_kitty_shm_probe_gating_and_cache(monkeypatch) -> None:
    _reset_shm_cache()
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    assert kitty_shm_available("kitty") is False
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)
    assert kitty_shm_available("tct") is False

    calls = {"count": 0}

    def fake_probe() -> bool:
        calls["count"] += 1
        return True

    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_video_motion._probe_kitty_shm_once",
        fake_probe,
    )
    _reset_shm_cache()
    assert kitty_shm_available("kitty") is True
    assert kitty_shm_available("kitty") is True
    assert calls["count"] == 1
    assert kitty_shm_available("kitty", force=True) is True
    assert calls["count"] == 2
    _reset_shm_cache()


def test_kitty_shm_probe_ok_and_timeout_paths(monkeypatch) -> None:
    from sase.ace.tui.graphics import _viewer_video_motion as media

    media._KITTY_SHM_CACHE = None
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)

    class _FakeShm:
        name = "test-shm"
        closed = False
        unlinked = False

        def close(self) -> None:
            type(self).closed = True

        def unlink(self) -> None:
            type(self).unlinked = True

    created: list[_FakeShm] = []

    def fake_shared_memory(*, create: bool, size: int):
        del create, size
        shm = _FakeShm()
        created.append(shm)
        return shm

    import multiprocessing.shared_memory as shared_memory

    monkeypatch.setattr(shared_memory, "SharedMemory", fake_shared_memory)
    monkeypatch.setattr(media, "_kitty_shm_query_exchange", lambda query, timeout: "OK")
    assert media._probe_kitty_shm_once() is True
    assert created and created[-1].closed and created[-1].unlinked

    monkeypatch.setattr(media, "_kitty_shm_query_exchange", lambda query, timeout: None)
    assert media._probe_kitty_shm_once() is False
    media._KITTY_SHM_CACHE = None
