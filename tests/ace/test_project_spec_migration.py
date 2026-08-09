"""Tests for the .gp -> .sase project spec migration helper."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any

import pytest

from sase.ace.patch.project_spec_migration import (
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
        "sase.ace.patch.project_spec_migration.Path.home",
        lambda: fake_home,
    )

    report = migrate_all_projects()

    assert report.migrated_count == 1
    assert (fake_projects / "demo" / "demo.sase").read_text() == "demo"
    assert os.environ["HOME"] == str(fake_home)


def test_migrate_compares_and_replaces_under_both_path_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "myproj"
    legacy = project_dir / "myproj.gp"
    canonical = project_dir / "myproj.sase"
    _write(legacy, "NAME: legacy\n")
    _write(canonical, "NAME: canonical\n")

    active_locks: set[str] = set()
    checked_reads: list[Path] = []
    original_read_bytes = Path.read_bytes
    original_replace = os.replace

    @contextmanager
    def fake_patch_lock(project_file: str) -> Iterator[None]:
        active_locks.add(project_file)
        try:
            yield
        finally:
            active_locks.remove(project_file)

    def checked_read_bytes(path: Path) -> bytes:
        if path in (legacy, canonical):
            assert str(legacy) in active_locks
            assert str(canonical) in active_locks
            checked_reads.append(path)
        return original_read_bytes(path)

    def checked_replace(src: Any, dst: Any) -> None:
        assert str(legacy) in active_locks
        assert str(canonical) in active_locks
        original_replace(src, dst)

    monkeypatch.setattr(
        "sase.ace.patch.project_spec_migration.patch_lock",
        fake_patch_lock,
    )
    monkeypatch.setattr(Path, "read_bytes", checked_read_bytes)
    monkeypatch.setattr(
        "sase.ace.patch.project_spec_migration.os.replace",
        checked_replace,
    )

    report = migrate_project_dir(project_dir, force=True)

    assert report.migrated_count == 1
    assert checked_reads == [legacy, canonical]
    assert canonical.read_text() == "NAME: legacy\n"
