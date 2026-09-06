"""Tests for completion install stamps."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.completion.install_stamp import (
    InstallStamp,
    OWNER_CHEZMOI,
    _stamp_path,
    list_stamps,
    portable_stamp_target,
    read_stamp,
    resolve_stamp_target,
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
    assert loaded.owner == "local"
    assert list_stamps() == (stamp,)
    assert stamp_owns_path("zsh", target)
    assert not stamp_owns_path("zsh", tmp_path / "other")
    assert not stamp_owns_path("bash", target)


def test_stamp_owner_round_trip_and_legacy_default(tmp_path: Path) -> None:
    target = tmp_path / "_sase"
    stamp = InstallStamp(
        shell="zsh",
        version="0.16.0",
        digest="abc123",
        target=str(target),
        timestamp="2026-08-17T12:00:00Z",
        owner=OWNER_CHEZMOI,
    )

    write_stamp(stamp)
    assert read_stamp("zsh") == stamp

    path = _stamp_path("bash")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "{\n"
        '  "digest": "abc123",\n'
        '  "schema_version": 1,\n'
        '  "shell": "bash",\n'
        f'  "target": "{tmp_path / "sase"}",\n'
        '  "timestamp": "2026-08-17T12:00:00Z",\n'
        '  "version": "0.16.0"\n'
        "}\n",
        encoding="utf-8",
    )
    loaded = read_stamp("bash")
    assert loaded is not None
    assert loaded.owner == "local"


def test_portable_stamp_target_uses_tilde_prefix(tmp_path: Path) -> None:
    linux_home = tmp_path / "home" / "bryan"
    mac_home = tmp_path / "Users" / "bryan"
    linux_target = linux_home / ".zfunc" / "_sase"
    mac_target = mac_home / ".zfunc" / "_sase"

    assert portable_stamp_target(linux_target, home=linux_home) == "~/.zfunc/_sase"
    assert portable_stamp_target(mac_target, home=mac_home) == "~/.zfunc/_sase"
    outside = tmp_path / "opt" / "sase"
    assert portable_stamp_target(outside, home=linux_home) == str(outside)


def test_portable_stamp_owns_path_on_foreign_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mac_home = tmp_path / "Users" / "bryan"
    script = mac_home / ".zfunc" / "_sase"
    script.parent.mkdir(parents=True)
    script.write_text("# sase\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(mac_home))

    stamp = InstallStamp(
        shell="zsh",
        version="0.16.0",
        digest="abc123",
        target="~/.zfunc/_sase",
        timestamp="2026-08-17T12:00:00Z",
        owner=OWNER_CHEZMOI,
    )
    write_stamp(stamp)
    assert resolve_stamp_target(stamp.target) == Path("~/.zfunc/_sase").expanduser()
    assert stamp_owns_path("zsh", script)
    assert not stamp_owns_path("zsh", tmp_path / "other")


def test_missing_and_malformed_stamps_are_ignored(tmp_path: Path) -> None:
    assert read_stamp("fish") is None
    path = _stamp_path("bash")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_stamp("bash") is None
    assert list_stamps() == ()
