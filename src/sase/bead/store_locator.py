"""Shared helpers for locating and reading project bead stores."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import Status
from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC, BeadProject
from sase.bead.workspace import get_project_beads_dirs_for_project


def canonical_beads_dir_for_project(project: str) -> Path | None:
    """Return the canonical readable bead-store directory for *project*."""
    beads_dirs = get_project_beads_dirs_for_project(project)
    if not beads_dirs:
        return None
    return beads_dirs[0]


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
