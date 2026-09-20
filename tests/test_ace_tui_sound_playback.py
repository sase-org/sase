"""Tests for notification sound-file playback."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui import sound_playback


def _which_only(*available: str) -> Any:
    return lambda name: f"/usr/bin/{name}" if name in available else None


def test_macos_uses_afplay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sound_playback.sys, "platform", "darwin")
    monkeypatch.setattr(sound_playback.shutil, "which", _which_only("afplay", "paplay"))
    assert sound_playback.resolve_sound_player() == ("/usr/bin/afplay",)


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (("paplay", "aplay", "ffplay"), ("/usr/bin/paplay",)),
        (("aplay", "ffplay"), ("/usr/bin/aplay",)),
        (
            ("ffplay",),
            ("/usr/bin/ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"),
        ),
    ],
)
def test_linux_player_preference(
    monkeypatch: pytest.MonkeyPatch,
    available: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    monkeypatch.setattr(sound_playback.sys, "platform", "linux")
    monkeypatch.setattr(sound_playback.shutil, "which", _which_only(*available))
    assert sound_playback.resolve_sound_player() == expected


def test_no_player_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sound_playback.sys, "platform", "linux")
    monkeypatch.setattr(sound_playback.shutil, "which", _which_only())
    assert sound_playback.resolve_sound_player() is None


def test_unsupported_platform_has_no_player(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sound_playback.sys, "platform", "win32")
    monkeypatch.setattr(sound_playback.shutil, "which", _which_only("afplay", "paplay"))
    assert sound_playback.resolve_sound_player() is None


def _patch_linux(monkeypatch: pytest.MonkeyPatch, *available: str) -> None:
    monkeypatch.setattr(sound_playback.sys, "platform", "linux")
    monkeypatch.setattr(sound_playback.shutil, "which", _which_only(*available))


def test_play_runs_player_with_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_linux(monkeypatch, "paplay")
    sound = tmp_path / "chime.wav"
    sound.write_bytes(b"x")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(sound_playback.subprocess, "run", fake_run)
    assert sound_playback.play_sound_file(sound) is True
    assert calls == [["/usr/bin/paplay", str(sound)]]


def test_play_expands_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_linux(monkeypatch, "aplay")
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "chime.wav").write_bytes(b"x")
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(sound_playback.subprocess, "run", fake_run)
    assert sound_playback.play_sound_file("~/chime.wav") is True
    assert calls[0][-1] == str(tmp_path / "chime.wav")


def test_play_missing_file_does_not_launch_player(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_linux(monkeypatch, "paplay")

    def boom(*_: Any, **__: Any) -> None:
        raise AssertionError("player must not run")

    monkeypatch.setattr(sound_playback.subprocess, "run", boom)
    assert sound_playback.play_sound_file(tmp_path / "nope.wav") is False


def test_play_without_player_returns_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_linux(monkeypatch)
    sound = tmp_path / "chime.wav"
    sound.write_bytes(b"x")
    assert sound_playback.play_sound_file(sound) is False


def test_play_nonzero_exit_returns_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_linux(monkeypatch, "paplay")
    sound = tmp_path / "chime.wav"
    sound.write_bytes(b"x")
    monkeypatch.setattr(
        sound_playback.subprocess,
        "run",
        lambda argv, **_: subprocess.CompletedProcess(argv, 1),
    )
    assert sound_playback.play_sound_file(sound) is False


@pytest.mark.parametrize(
    "error",
    [
        OSError("exec format error"),
        FileNotFoundError("player vanished"),
        subprocess.TimeoutExpired("paplay", 30),
    ],
)
def test_play_swallows_launch_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    _patch_linux(monkeypatch, "paplay")
    sound = tmp_path / "chime.wav"
    sound.write_bytes(b"x")

    def fake_run(*_: Any, **__: Any) -> None:
        raise error

    monkeypatch.setattr(sound_playback.subprocess, "run", fake_run)
    assert sound_playback.play_sound_file(sound) is False
