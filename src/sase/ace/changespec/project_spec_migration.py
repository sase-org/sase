"""Legacy migration names backed by :mod:`sase.ace.patch.project_spec_migration`."""

from __future__ import annotations

import os
from pathlib import Path

from sase.ace.patch import project_spec_migration as _migration
from sase.ace.patch.locking import changespec_lock

MigrationReport = _migration.MigrationReport


def _sync_legacy_patch_points() -> None:
    _migration.os = os
    _migration.patch_lock = changespec_lock


def migrate_project_dir(project_dir: Path, *, force: bool = False) -> MigrationReport:
    _sync_legacy_patch_points()
    return _migration.migrate_project_dir(project_dir, force=force)


def migrate_all_projects(
    projects_dir: Path | None = None, *, force: bool = False
) -> MigrationReport:
    _sync_legacy_patch_points()
    return _migration.migrate_all_projects(projects_dir, force=force)


__all__ = [
    "MigrationReport",
    "Path",
    "changespec_lock",
    "migrate_all_projects",
    "migrate_project_dir",
    "os",
]
