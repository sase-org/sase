"""Tests for Footprint paths and effective mode (``sase.footprint.paths``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.footprint import paths


def test_sase_home_matches_core_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.core.paths import sase_home as core_sase_home

    monkeypatch.setenv("SASE_HOME", "/tmp/footprint-home-check")
    assert paths.sase_home() == core_sase_home()
    monkeypatch.delenv("SASE_HOME")
    monkeypatch.setenv("HOME", "/tmp/footprint-fake-home")
    assert paths.sase_home() == core_sase_home()


def test_layout_under_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    root = paths.footprint_dir()
    assert root == tmp_path / "footprint"
    assert paths.spool_dir() == root / "spool"
    assert paths.ledger_path() == root / "footprint.sqlite"
    assert paths.mode_path() == root / "mode"
    assert paths.generation_path() == root / "generation"


def test_env_off_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_FOOTPRINT", "off")
    assert paths.effective_mode() == "off"


def test_pytest_defaults_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SASE_FOOTPRINT", raising=False)
    assert paths.effective_mode() == "off"


def test_pytest_test_mode_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_FOOTPRINT", "test")
    assert paths.effective_mode() == "test"


def test_mode_file_off_outside_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.delenv("SASE_FOOTPRINT", raising=False)
    mode_file = tmp_path / "mode"
    assert paths.effective_mode(mode_file=mode_file) == "local"
    mode_file.write_text("off", encoding="utf-8")
    assert paths.effective_mode(mode_file=mode_file) == "off"
    mode_file.write_text("local\n", encoding="utf-8")
    assert paths.effective_mode(mode_file=mode_file) == "local"
    mode_file.write_text("bogus", encoding="utf-8")
    assert paths.effective_mode(mode_file=mode_file) == "local"
