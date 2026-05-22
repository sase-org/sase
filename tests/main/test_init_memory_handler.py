"""Tests for the ``sase init memory`` command skeleton."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from sase.main import init_memory_handler
from sase.main.init_memory_handler import handle_init_memory_command


def test_init_memory_handler_smoke_does_not_write_project_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(init_memory_handler, "CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: False)

    with pytest.raises(SystemExit) as exc:
        handle_init_memory_command(argparse.Namespace())

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "init memory: command registered" in out
    assert str(tmp_path / "memory" / "short" / "sase.md") in out
    assert str(tmp_path / "config" / "sase.yml") in out
    assert not (tmp_path / "memory").exists()


def test_init_memory_handler_reports_chezmoi_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    chezmoi_home = tmp_path / "chezmoi" / "home"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(init_memory_handler, "CHEZMOI_HOME", chezmoi_home)
    monkeypatch.setattr(init_memory_handler, "get_use_chezmoi", lambda: True)

    with pytest.raises(SystemExit) as exc:
        handle_init_memory_command(argparse.Namespace())

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert str(chezmoi_home / "memory" / "short" / "sase.md") in out
    assert str(chezmoi_home / "dot_config" / "sase" / "sase.yml") in out
    assert not chezmoi_home.exists()
