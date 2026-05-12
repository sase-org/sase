"""Tests for the .gp -> .sase project spec migration helper."""

from __future__ import annotations

import os
from pathlib import Path

from sase.ace.changespec.project_spec_migration import (
    migrate_all_projects,
    migrate_project_dir,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_migrate_project_dir_renames_active_and_archive(tmp_path: Path) -> None:
    project_dir = tmp_path / "myproj"
    _write(project_dir / "myproj.gp", "NAME: foo\n")
    _write(project_dir / "myproj-archive.gp", "NAME: bar\n")

    report = migrate_project_dir(project_dir)

    assert report.migrated_count == 2
    assert (project_dir / "myproj.sase").read_text() == "NAME: foo\n"
    assert (project_dir / "myproj-archive.sase").read_text() == "NAME: bar\n"
    assert not (project_dir / "myproj.gp").exists()
    assert not (project_dir / "myproj-archive.gp").exists()


def test_migrate_skips_identical_canonical_sibling(tmp_path: Path) -> None:
    project_dir = tmp_path / "myproj"
    _write(project_dir / "myproj.gp", "NAME: foo\n")
    _write(project_dir / "myproj.sase", "NAME: foo\n")

    report = migrate_project_dir(project_dir)

    assert report.migrated_count == 0
    assert report.skipped_identical == [str(project_dir / "myproj.gp")]
    # The redundant legacy copy is removed when contents match.
    assert not (project_dir / "myproj.gp").exists()
    assert (project_dir / "myproj.sase").read_text() == "NAME: foo\n"


def test_migrate_reports_conflict_when_contents_differ(tmp_path: Path) -> None:
    project_dir = tmp_path / "myproj"
    _write(project_dir / "myproj.gp", "NAME: legacy\n")
    _write(project_dir / "myproj.sase", "NAME: canonical\n")

    report = migrate_project_dir(project_dir)

    assert report.conflict_count == 1
    legacy_path, reason = report.conflicts[0]
    assert legacy_path == str(project_dir / "myproj.gp")
    assert "canonical sibling already exists" in reason
    # Without --force the canonical copy is preserved untouched.
    assert (project_dir / "myproj.gp").read_text() == "NAME: legacy\n"
    assert (project_dir / "myproj.sase").read_text() == "NAME: canonical\n"


def test_migrate_force_overrides_conflict(tmp_path: Path) -> None:
    project_dir = tmp_path / "myproj"
    _write(project_dir / "myproj.gp", "NAME: legacy\n")
    _write(project_dir / "myproj.sase", "NAME: canonical\n")

    report = migrate_project_dir(project_dir, force=True)

    assert report.migrated_count == 1
    assert (project_dir / "myproj.sase").read_text() == "NAME: legacy\n"
    assert not (project_dir / "myproj.gp").exists()


def test_migrate_all_projects_aggregates_across_projects(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    _write(projects_dir / "alpha" / "alpha.gp", "A")
    _write(projects_dir / "beta" / "beta.gp", "B")
    # Project with no legacy file is silently ignored.
    _write(projects_dir / "gamma" / "gamma.sase", "G")

    report = migrate_all_projects(projects_dir)

    assert report.migrated_count == 2
    migrated_dests = {Path(dest).name for _, dest in report.migrated}
    assert migrated_dests == {"alpha.sase", "beta.sase"}


def test_migrate_handles_missing_legacy_files(tmp_path: Path) -> None:
    project_dir = tmp_path / "myproj"
    project_dir.mkdir()

    report = migrate_project_dir(project_dir)

    assert report.migrated_count == 0
    assert report.conflict_count == 0
    assert report.skipped_count == 0


def test_migrate_respects_archive_pair_when_active_missing(tmp_path: Path) -> None:
    """If only the archive legacy file exists, it should still be migrated."""
    project_dir = tmp_path / "myproj"
    _write(project_dir / "myproj-archive.gp", "archived")

    report = migrate_project_dir(project_dir)

    assert report.migrated_count == 1
    assert (project_dir / "myproj-archive.sase").read_text() == "archived"


def test_migrate_all_projects_with_default_root(tmp_path: Path, monkeypatch) -> None:
    """Without an explicit projects_dir argument, the helper falls back to
    ``~/.sase/projects`` derived from ``Path.home()``."""
    fake_home = tmp_path / "home"
    fake_projects = fake_home / ".sase" / "projects"
    _write(fake_projects / "demo" / "demo.gp", "demo")
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(
        "sase.ace.changespec.project_spec_migration.Path.home",
        lambda: fake_home,
    )

    report = migrate_all_projects()

    assert report.migrated_count == 1
    assert (fake_projects / "demo" / "demo.sase").read_text() == "demo"
    assert os.environ["HOME"] == str(fake_home)
