"""Tests for completion install stamps."""

from __future__ import annotations

from pathlib import Path

from sase.completion.install_stamp import (
    InstallStamp,
    _stamp_path,
    list_stamps,
    read_stamp,
    stamp_owns_path,
    write_stamp,
)


def test_stamp_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "_sase"
    stamp = InstallStamp(
        shell="zsh",
        version="0.16.0",
        digest="abc123",
        target=str(target),
        timestamp="2026-08-17T12:00:00Z",
    )

    path = write_stamp(stamp)
    assert path == _stamp_path("zsh")
    loaded = read_stamp("zsh")
    assert loaded == stamp
    assert list_stamps() == (stamp,)
    assert stamp_owns_path("zsh", target)
    assert not stamp_owns_path("zsh", tmp_path / "other")
    assert not stamp_owns_path("bash", target)


def test_missing_and_malformed_stamps_are_ignored(tmp_path: Path) -> None:
    assert read_stamp("fish") is None
    path = _stamp_path("bash")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_stamp("bash") is None
    assert list_stamps() == ()
