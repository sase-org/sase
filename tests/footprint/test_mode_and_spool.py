"""Tests for Footprint mode files and bounded spool writes."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.footprint import _spool
from sase.footprint._mode import current_mode, set_mode
from sase.footprint.paths import MODE_LOCAL, MODE_OFF, MODE_TEST, mode_path, spool_dir


def test_mode_file_is_atomic_and_private(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.delenv("SASE_FOOTPRINT", raising=False)

    set_mode(MODE_OFF)
    target = mode_path()
    assert target.read_text(encoding="ascii") == "off\n"
    assert current_mode() == MODE_OFF
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert not list(target.parent.glob(".mode-*"))


def test_mode_environment_and_pytest_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    mode_file = mode_path_for(tmp_path)
    mode_file.parent.mkdir(parents=True, exist_ok=True)
    mode_file.write_text("local\n", encoding="ascii")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.delenv("SASE_FOOTPRINT", raising=False)
    assert current_mode() == MODE_LOCAL

    mode_file.write_text("off\n", encoding="ascii")
    assert current_mode() == MODE_OFF
    monkeypatch.setenv("SASE_FOOTPRINT", "local")
    assert current_mode() == MODE_LOCAL
    monkeypatch.setenv("SASE_FOOTPRINT", "off")
    assert current_mode() == MODE_OFF
    monkeypatch.setenv("PYTEST_VERSION", "current")
    assert current_mode() == MODE_OFF
    monkeypatch.setenv("SASE_FOOTPRINT", "test")
    assert current_mode() == MODE_TEST


def test_mode_command_takes_effect_before_exit(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("PYTEST_") or key == "SASE_FOOTPRINT":
            env.pop(key, None)
    env["SASE_HOME"] = str(home)
    root = Path(__file__).resolve().parents[2]

    status = _run(root, env, "footprint", "mode")
    assert status.returncode == 0
    assert "recording mode: local" in status.stdout
    assert "never command arguments" in status.stdout
    initial_records = sum(
        len(path.read_text(encoding="ascii").splitlines())
        for path in spool_dir_for(home).glob("*.jsonl")
    )
    assert initial_records == 1

    off = _run(root, env, "footprint", "mode", "off")
    assert off.returncode == 0
    assert mode_path_for(home).read_text(encoding="ascii") == "off\n"
    assert (
        sum(
            len(path.read_text(encoding="ascii").splitlines())
            for path in spool_dir_for(home).glob("*.jsonl")
        )
        == initial_records
    )

    version = _run(root, env, "version")
    assert version.returncode == 0
    assert (
        sum(
            len(path.read_text(encoding="ascii").splitlines())
            for path in spool_dir_for(home).glob("*.jsonl")
        )
        == initial_records
    )

    local = _run(root, env, "footprint", "mode", "local")
    assert local.returncode == 0
    version = _run(root, env, "version")
    assert version.returncode == 0
    final_records = sum(
        len(path.read_text(encoding="ascii").splitlines())
        for path in spool_dir_for(home).glob("*.jsonl")
    )
    assert final_records == initial_records + 1


def test_spool_writes_private_bounded_lines_and_drop_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_FOOTPRINT", "test")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path))
    day = "2026-10-27"
    record = '{"s":1,"d":"2026-10-27","f":"cli:version"}'

    monkeypatch.setattr(_spool, "MAX_DAY_BYTES", len(record) + 1)
    _spool.append_lines((record,), mode=MODE_TEST, day=day)
    _spool.append_lines((record,), mode=MODE_TEST, day=day)

    path = spool_dir() / f"{day}.jsonl"
    lines = path.read_text(encoding="ascii").splitlines()
    assert json.loads(lines[0]) == {"s": 1, "d": day, "f": "cli:version"}
    assert json.loads(lines[1])["drop"] == 1
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert all(len(line.encode("ascii")) + 1 <= _spool.MAX_LINE_BYTES for line in lines)


def test_spool_skips_oversized_lines_and_swallows_os_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setenv("SASE_FOOTPRINT", "test")
    monkeypatch.setenv("SASE_PYTEST_SANDBOX_DIR", str(tmp_path))
    _spool.append_lines(
        (
            "x" * (_spool.MAX_LINE_BYTES - 1),
            "x" * (_spool.MAX_LINE_BYTES + 1),
        )
    )
    path = next(spool_dir().glob("*.jsonl"))
    assert path.stat().st_size == _spool.MAX_LINE_BYTES

    def fail_write(fd: int, payload: bytes) -> int:
        raise OSError("simulated full disk")

    monkeypatch.setattr(_spool.os, "write", fail_write)
    _spool.append_lines(("another line",), mode=MODE_TEST)


def _run(root: Path, env: dict[str, str], *args: str):
    import subprocess
    import sys

    return subprocess.run(
        [sys.executable, "-m", "sase", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def mode_path_for(home: Path) -> Path:
    return home / "footprint" / "mode"


def spool_dir_for(home: Path) -> Path:
    return home / "footprint" / "spool"
