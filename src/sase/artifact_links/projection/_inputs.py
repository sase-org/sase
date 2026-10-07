"""Resolve the store-scoped facts every projection rule reads."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.artifact_links.projection._model import ProjectionInputs
from sase.repo_inventory import collect_repo_inventory
from sase.sdd.store import AGENTS_SIDECAR_ROLE

if TYPE_CHECKING:
    from sase.sdd.store import SddStore


def build_projection_inputs(
    *, project_key: str, sdd_store: SddStore | None
) -> ProjectionInputs:
    """Build :class:`ProjectionInputs` strictly from already-owned roots."""

    primary_repo_root, primary_repo_name = _resolve_primary_repo(project_key)
    return ProjectionInputs(
        project_key=project_key,
        primary_repo_root=primary_repo_root,
        primary_repo_name=primary_repo_name,
        agents_sidecar_root=_resolve_agents_root(sdd_store),
        bead_store_root=_resolve_bead_store_root(project_key),
    )


def _resolve_primary_repo(project_key: str) -> tuple[Path | None, str | None]:
    try:
        inventory = collect_repo_inventory(project=project_key)
    except Exception:  # noqa: BLE001 - projection is best-effort.
        return None, None
    for record in inventory.records:
        if record.kind != "primary" or record.project_key != project_key:
            continue
        for clone in record.clones:
            if clone.exists:
                return Path(clone.path), record.name
    return None, None


def _resolve_agents_root(sdd_store: SddStore | None) -> Path | None:
    if sdd_store is None:
        return None
    try:
        root = sdd_store.repo_root_for_kind(AGENTS_SIDECAR_ROLE)
    except Exception:  # noqa: BLE001 - no agents sidecar means this rule is inert.
        return None
    return root if root.is_dir() else None


def _resolve_bead_store_root(project_key: str) -> Path | None:
    from sase.bead.store_locator import canonical_beads_dir_for_project

    try:
        beads_dir = canonical_beads_dir_for_project(project_key)
    except Exception:  # noqa: BLE001 - no bead store means this rule is inert.
        return None
    if beads_dir is None or not beads_dir.is_dir():
        return None
    return beads_dir


__all__ = ["build_projection_inputs"]
