"""Shared helpers for locating and reading project bead stores."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sase.bead.model import Issue, Status
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BeadProject
from sase.bead.workspace import (
    get_project_beads_dirs_for_project,
    resolve_primary_workspace_for_project,
)
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

_NON_CLOSED_STATUSES: list[Status] = [
    status for status in Status if status is not Status.CLOSED
]


def canonical_beads_dir_for_project(project: str) -> Path | None:
    """Return the canonical readable bead-store directory for *project*.

    This locator is read-only. Automated writers must use a writable
    :class:`~sase.workspace_provider.ownership.OperationContext` instead
    of mutating the path returned here.
    """
    beads_dirs = get_project_beads_dirs_for_project(project)
    if not beads_dirs:
        return None
    return beads_dirs[0]


def canonical_plans_dir_for_project(project: str) -> Path | None:
    """Return the canonical readable plans directory for *project*."""
    return canonical_sidecar_dir_for_project(project, "plans")


def canonical_sidecar_dir_for_project(project: str, role: str) -> Path | None:
    """Return the canonical readable sidecar root for *role* in *project*.

    Readers (catalogs, wait evaluation, mobile views) may use this path.
    Automated mutation must go through a writable operation context.
    """
    primary = resolve_primary_workspace_for_project(project)
    if primary is None:
        return None
    try:
        from sase.sdd.store import resolve_sdd_store

        root = resolve_sdd_store(primary, PRIMARY_WORKSPACE_NUM).kind_root(role)
    except (OSError, RuntimeError, ValueError):
        return None
    return root if root.is_dir() else None


def open_bead_project_for_beads_dir(beads_dir: Path) -> BeadProject:
    """Open a :class:`BeadProject` for any supported bead-store layout."""
    parts = beads_dir.parts
    if len(parts) >= 2 and parts[-2:] == ("sdd", "beads"):
        return BeadProject(beads_dir.parents[1], beads_dirname=BEADS_DIRNAME)
    if len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"):
        return BeadProject(beads_dir.parent, beads_dirname=BEADS_DIRNAME_NON_VC)
    return BeadProject(beads_dir.parent, beads_dirname=beads_dir.name)


def closed_bead_ids_for_project(project: str) -> frozenset[str] | None:
    """Return closed bead IDs, or ``None`` when the store is unavailable."""
    try:
        beads_dir = canonical_beads_dir_for_project(project)
        if beads_dir is None:
            return None
        with open_bead_project_for_beads_dir(beads_dir) as bead_project:
            issues = bead_project.list_issues(statuses=[Status.CLOSED])
    except Exception:  # noqa: BLE001 - unavailable stores must fail closed.
        return None
    return frozenset(issue.id for issue in issues)


def open_bead_candidates_for_project(project: str) -> tuple[Issue, ...] | None:
    """Return non-closed beads from the canonical store, or ``None``."""
    try:
        beads_dir = canonical_beads_dir_for_project(project)
        if beads_dir is None:
            return None
        with open_bead_project_for_beads_dir(beads_dir) as bead_project:
            issues = bead_project.list_issues(statuses=_NON_CLOSED_STATUSES)
    except Exception:  # noqa: BLE001 - unavailable stores must fail closed.
        return None
    return tuple(issues)


def bead_statuses_for_project(
    project: str,
    bead_ids: Iterable[str],
) -> dict[str, str] | None:
    """Return requested bead IDs mapped to status values, or ``None``.

    ``None`` means the project's canonical bead store was unavailable. IDs
    that do not exist in the store are omitted from the returned mapping.

    The Rust ``bead_show`` binding is single-id only, so this uses one
    ``list_issues`` store query and matches requested IDs in Python.
    """
    try:
        beads_dir = canonical_beads_dir_for_project(project)
        if beads_dir is None:
            return None
        wanted = set(bead_ids)
        with open_bead_project_for_beads_dir(beads_dir) as bead_project:
            if not wanted:
                return {}
            return _statuses_from_issues(bead_project.list_issues(), wanted)
    except Exception:  # noqa: BLE001 - unavailable stores must fail closed.
        return None


def _statuses_from_issues(
    issues: Iterable[Issue],
    wanted: set[str],
) -> dict[str, str]:
    """Map requested IDs to statuses from one already-loaded issue list."""
    by_id: dict[str, Issue] = {}
    by_suffix: dict[str, Issue | None] = {}
    for issue in issues:
        by_id[issue.id] = issue
        suffix = issue.id.rsplit("-", 1)[-1]
        if suffix == issue.id:
            continue
        by_suffix[suffix] = None if suffix in by_suffix else issue
    statuses: dict[str, str] = {}
    for bead_id in wanted:
        matched = by_id.get(bead_id)
        if matched is None:
            matched = by_suffix.get(bead_id)
        if matched is None:
            continue
        statuses[bead_id] = matched.status.value
    return statuses
