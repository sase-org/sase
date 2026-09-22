"""Tests for explicit-environment managed-temp root resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.paths import managed_tmpdir_root_for_env


def test_tmpdir_override_wins_over_home() -> None:
    root = managed_tmpdir_root_for_env(
        {"SASE_TMPDIR": "/cache/sase/tmp", "SASE_HOME": "/alt/.sase"}
    )

    assert root == Path("/cache/sase/tmp")


def test_home_fallback_without_tmpdir() -> None:
    root = managed_tmpdir_root_for_env({"SASE_HOME": "/alt/.sase"})

    assert root == Path("/alt/.sase/tmp")


def test_default_home_without_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SASE_TMPDIR", raising=False)
    monkeypatch.delenv("SASE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    assert managed_tmpdir_root_for_env({}) == tmp_path / ".sase" / "tmp"
