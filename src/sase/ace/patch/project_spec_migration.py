"""Rename existing ``.gp`` project spec files to the canonical ``.sase`` extension.

Scans ``~/.sase/projects/<project>/`` for legacy active and archive project
spec files. For each legacy file the rename is performed atomically under the
existing project-file lock so concurrent Patch writers cannot observe a
half-renamed state.

The migration is conservative by design:

* If a canonical ``.sase`` sibling already exists, the legacy file is skipped
  as a conflict unless its contents are byte-for-byte identical to the
  canonical sibling, in which case the redundant legacy copy is removed.
  ``force=True`` overrides the conflict rule and replaces the canonical
  sibling with the legacy contents.
* If only the legacy file exists, it is atomically renamed to the canonical
  path.

The helper returns counts so callers (CLI / startup probes) can summarize the
result.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from contextlib import ExitStack
from pathlib import Path

from sase.core.paths import sase_projects_dir

from .locking import patch_lock
from .project_spec_path import (
    active_project_spec_filename,
    archive_project_spec_filename,
    legacy_active_project_spec_filename,
    legacy_archive_project_spec_filename,
)


@dataclass
class MigrationReport:
    """Summary of a project spec migration run."""

    migrated: list[tuple[str, str]] = field(default_factory=list)
    skipped_identical: list[str] = field(default_factory=list)
    conflicts: list[tuple[str, str]] = field(default_factory=list)
    missing_legacy: list[str] = field(default_factory=list)

    @property
    def migrated_count(self) -> int:
        return len(self.migrated)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_identical) + len(self.missing_legacy)

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)


def _migrate_one(
    legacy_path: Path, canonical_path: Path, *, force: bool, report: MigrationReport
) -> None:
    """Atomically migrate a single legacy file to the canonical path.

    Hold both path-derived ProjectSpec locks while comparing/removing/replacing
    files so legacy ``.gp`` writers and canonical ``.sase`` writers cannot race
    the migration.
    """
    if not legacy_path.exists():
        report.missing_legacy.append(str(legacy_path))
        return

    with ExitStack() as stack:
        stack.enter_context(patch_lock(str(legacy_path)))
        stack.enter_context(patch_lock(str(canonical_path)))

        if not legacy_path.exists():
            report.missing_legacy.append(str(legacy_path))
            return

        if canonical_path.exists():
            try:
                legacy_bytes = legacy_path.read_bytes()
                canonical_bytes = canonical_path.read_bytes()
            except OSError as exc:
                report.conflicts.append((str(legacy_path), f"read failed: {exc}"))
                return

            if legacy_bytes == canonical_bytes:
                try:
                    legacy_path.unlink()
                except FileNotFoundError:
                    pass
                report.skipped_identical.append(str(legacy_path))
                return

            if not force:
                report.conflicts.append(
                    (
                        str(legacy_path),
                        "canonical sibling already exists and differs: "
                        f"{canonical_path}",
                    )
                )
                return

        os.replace(legacy_path, canonical_path)
    report.migrated.append((str(legacy_path), str(canonical_path)))


def migrate_project_dir(project_dir: Path, *, force: bool = False) -> MigrationReport:
    """Migrate the active and archive spec files inside one project directory.

    Returns a per-directory report. Errors during reads/renames surface as
    conflict entries so callers can present them without crashing the run.
    """
    report = MigrationReport()
    project_name = project_dir.name

    pairs = (
        (
            project_dir / legacy_active_project_spec_filename(project_name),
            project_dir / active_project_spec_filename(project_name),
        ),
        (
            project_dir / legacy_archive_project_spec_filename(project_name),
            project_dir / archive_project_spec_filename(project_name),
        ),
    )

    for legacy_path, canonical_path in pairs:
        if not legacy_path.exists():
            continue
        _migrate_one(legacy_path, canonical_path, force=force, report=report)

    return report


def migrate_all_projects(
    projects_dir: Path | None = None, *, force: bool = False
) -> MigrationReport:
    """Migrate every project under ``projects_dir`` (default ``~/.sase/projects``).

    The aggregated report covers all project directories visited.
    """
    if projects_dir is None:
        projects_dir = sase_projects_dir()

    aggregate = MigrationReport()
    if not projects_dir.is_dir():
        return aggregate

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        per_project = migrate_project_dir(project_dir, force=force)
        aggregate.migrated.extend(per_project.migrated)
        aggregate.skipped_identical.extend(per_project.skipped_identical)
        aggregate.conflicts.extend(per_project.conflicts)
        aggregate.missing_legacy.extend(per_project.missing_legacy)

    return aggregate
