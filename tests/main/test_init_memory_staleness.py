"""Tests for the workspace-pinned ``sase`` build staleness warning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.init_memory.staleness import workspace_pinned_sase_mismatch_warning
from tests.main.init_memory_handler_helpers import (
    patch_standard_paths,
    plan_memory,
    run_memory,
    write,
)


def _write_pinned_venv(project_root: Path) -> tuple[Path, Path]:
    pinned_sase = project_root / ".venv" / "bin" / "sase"
    pinned_python = project_root / ".venv" / "bin" / "python"
    write(pinned_sase, "#!/usr/bin/env python\n")
    write(pinned_python, "")
    return pinned_sase, pinned_python


def test_warning_none_without_workspace_pinned_sase(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    assert workspace_pinned_sase_mismatch_warning(project_root) is None


def test_warning_none_when_running_the_pinned_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _pinned_sase, pinned_python = _write_pinned_venv(project_root)
    monkeypatch.setattr("sys.executable", str(pinned_python))

    assert workspace_pinned_sase_mismatch_warning(project_root) is None


def test_warning_names_the_foreign_build_and_the_pinned_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    pinned_sase, _pinned_python = _write_pinned_venv(project_root)
    foreign_python = tmp_path / "elsewhere" / "bin" / "python"
    write(foreign_python, "")
    monkeypatch.setattr("sys.executable", str(foreign_python))

    warning = workspace_pinned_sase_mismatch_warning(project_root)

    assert warning is not None
    assert str(foreign_python.resolve()) in warning
    assert str(pinned_sase) in warning
    assert "memory init --check" in warning


def test_memory_plan_surfaces_the_staleness_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    pinned_sase, _pinned_python = _write_pinned_venv(project_root)
    foreign_python = tmp_path / "elsewhere" / "bin" / "python"
    write(foreign_python, "")
    monkeypatch.setattr("sys.executable", str(foreign_python))

    plan = plan_memory()

    assert len(plan.warnings) == 1
    assert str(pinned_sase) in plan.warnings[0]


def test_memory_check_renders_the_staleness_warning_and_still_exits_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "project"
    home_root = tmp_path / "home"
    config_dir = tmp_path / "config"
    project_root.mkdir()
    home_root.mkdir()
    patch_standard_paths(
        monkeypatch,
        project_root=project_root,
        home_root=home_root,
        config_dir=config_dir,
    )
    assert run_memory() == 0
    capsys.readouterr()
    pinned_sase, _pinned_python = _write_pinned_venv(project_root)
    foreign_python = tmp_path / "elsewhere" / "bin" / "python"
    write(foreign_python, "")
    monkeypatch.setattr("sys.executable", str(foreign_python))

    assert run_memory(check=True) == 0

    out = capsys.readouterr().out
    assert "Warnings:" in out
    assert str(pinned_sase) in out
