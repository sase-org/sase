"""Tests for Phase 4 doctor memory checks."""

from __future__ import annotations

from pathlib import Path

from sase.doctor.checks_memory import _check_memory_episodes
from sase.doctor.runner import DoctorContext


def _context(tmp_path: Path, project: str | None = "alpha") -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=project,
        sase_home=tmp_path / ".sase",
    )


def test_memory_episodes_skips_when_no_project(tmp_path: Path) -> None:
    check = _check_memory_episodes(_context(tmp_path, project=None))

    assert check.status == "SKIP"
    assert "no current project" in check.summary


def test_memory_episodes_warns_for_temp_dirs_without_creating_lock(
    monkeypatch,
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    episodes_dir = projects_root / "alpha" / "episodes"
    temp_dir = episodes_dir / ".build.tmp.123"
    temp_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_memory.sase_projects_dir",
        lambda: projects_root,
    )

    check = _check_memory_episodes(_context(tmp_path))

    assert check.status == "WARN"
    assert "temp" in check.details[0]
    assert check.data["repairs"][0]["id"] == "remove_temp_dirs"
    assert not (episodes_dir / "index.lock").exists()
