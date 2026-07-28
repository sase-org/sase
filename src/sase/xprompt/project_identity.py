"""Canonical project namespace helpers for xprompt lookup."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.project_display_names import ProjectDisplaySnapshot


def load_project_alias_map() -> dict[str, str]:
    """Load project aliases without importing alias prompts during package init."""
    from sase.project_aliases import load_project_alias_map as _load_project_alias_map

    return _load_project_alias_map()


def load_project_display_snapshot() -> ProjectDisplaySnapshot:
    """Load display names lazily to avoid project-alias import cycles."""
    from sase.project_display_names import (
        load_project_display_snapshot as _load_project_display_snapshot,
    )

    return _load_project_display_snapshot()


def project_display_name_for_ref(
    ref: str,
    display_snapshot: ProjectDisplaySnapshot,
    alias_map: dict[str, str],
) -> str | None:
    """Resolve one project ref lazily through the display-name helper."""
    from sase.project_display_names import (
        project_display_name_for_ref as _project_display_name_for_ref,
    )

    return _project_display_name_for_ref(ref, display_snapshot, alias_map)


def get_known_project_workspaces() -> dict[str, Path]:
    """Load known project workspaces lazily to keep xprompt imports acyclic."""
    from sase.xprompt.loader_sources import (
        get_known_project_workspaces as _get_known_project_workspaces,
    )

    return _get_known_project_workspaces()


@lru_cache(maxsize=1)
def _identity_registry() -> tuple[dict[str, str], ProjectDisplaySnapshot] | None:
    """Return cached project alias and display-name projections."""
    try:
        return load_project_alias_map(), load_project_display_snapshot()
    except Exception:
        return None


@lru_cache(maxsize=512)
def _canonical_xprompt_project(ref: str) -> str:
    registry = _identity_registry()
    if registry is None:
        return ref

    alias_map, display_snapshot = registry
    return project_display_name_for_ref(ref, display_snapshot, alias_map) or ref


def canonical_xprompt_project(ref: str | None) -> str | None:
    """Return the canonical user-facing xprompt namespace for *ref*.

    Accepts a ProjectSpec directory key, configured ``PROJECT_NAME``, or alias.
    Unknown refs are returned unchanged so ad-hoc namespaces continue to work.
    Registry read failures degrade to the input ref and never raise.
    """
    if ref is None:
        return None
    value = ref.strip()
    if not value:
        return None
    return _canonical_xprompt_project(value)


def invalidate_xprompt_project_identity() -> None:
    """Clear process-lifetime xprompt project identity projections."""
    _identity_registry.cache_clear()
    _canonical_xprompt_project.cache_clear()


def known_project_namespaces() -> dict[str, Path]:
    """Return enabled project workspaces keyed by canonical xprompt namespace."""
    try:
        workspaces = get_known_project_workspaces()
    except Exception:
        return {}

    registry = _identity_registry()
    if registry is None:
        return dict(workspaces)

    _alias_map, display_snapshot = registry
    return {
        display_snapshot.label_for(project_key): workspace
        for project_key, workspace in workspaces.items()
    }


__all__ = [
    "canonical_xprompt_project",
    "invalidate_xprompt_project_identity",
    "known_project_namespaces",
]
