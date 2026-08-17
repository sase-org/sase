"""Shared enabled-project inventory for bead-gate chops.

``bead_task_triage`` and ``bead_stale_cleanup`` scan the same enabled-project
set. The inventory lives here so each chop can label its own warnings without
re-exporting these symbols from either chop's private state module.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.chops.sdk import ChopLogger
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records


@dataclass(frozen=True)
class ProjectInventory:
    stores: tuple[tuple[str, Path], ...]
    skipped_projects: frozenset[str] = frozenset()
    sweep_allowed: bool = True


def enabled_project_stores(log: ChopLogger, *, chop: str) -> ProjectInventory:
    """Return bead-store paths for every enabled, non-home, non-system project.

    *chop* is the caller identity used in warning prefixes so two chops sharing
    this helper do not appear to emit each other's diagnostics.
    """
    records = list(
        list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    )
    stores: list[tuple[str, Path]] = []
    skipped_projects: set[str] = set()
    for record in records:
        if (
            not record.is_project
            or record.state != "enabled"
            or record.system_managed
            or record.project_name == "home"
        ):
            continue
        try:
            beads_dir = canonical_beads_dir_for_project(record.project_name)
        except Exception as exc:  # noqa: BLE001 - continue with healthy projects.
            skipped_projects.add(record.project_name)
            log.warning(
                f"[{chop}] Failed to locate bead store for "
                f"{project_display_name(record.project_name)}: {exc}"
            )
            continue
        if beads_dir is None:
            skipped_projects.add(record.project_name)
            continue
        stores.append((record.project_name, beads_dir))
    return ProjectInventory(
        stores=tuple(stores),
        skipped_projects=frozenset(skipped_projects),
        sweep_allowed=bool(records),
    )


def coerce_project_inventory(
    value: ProjectInventory | Iterable[tuple[str, Path]],
) -> ProjectInventory:
    """Normalize legacy test doubles that still return the old stores list."""
    if isinstance(value, ProjectInventory):
        return value
    return ProjectInventory(stores=tuple(value))


def project_display_name(project_name: str) -> str:
    try:
        from sase.project_display_names import project_display_name_for

        return project_display_name_for(project_name)
    except Exception:  # noqa: BLE001 - logging must not perturb reconciliation.
        return project_name


__all__ = [
    "ProjectInventory",
    "coerce_project_inventory",
    "enabled_project_stores",
    "project_display_name",
]
