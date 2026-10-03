"""Canonical project namespace helpers for macro lookup."""

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
    """Load known project workspaces lazily to keep macro imports acyclic."""
    from sase.macro.loader_sources import (
        get_known_project_workspaces as _get_known_project_workspaces,
    )

    return _get_known_project_workspaces()


#: Whether the process-wide identity registry has been built. Set on the first
#: successful or degraded build and cleared by invalidation, so keystroke paths
#: can check readiness without touching the ``lru_cache`` internals or disk.
_identity_ready = False


@lru_cache(maxsize=1)
def _identity_registry() -> tuple[dict[str, str], ProjectDisplaySnapshot] | None:
    """Return cached project alias and display-name projections."""
    global _identity_ready  # noqa: PLW0603
    try:
        result = load_project_alias_map(), load_project_display_snapshot()
    except Exception:
        result = None
    _identity_ready = True
    return result


def macro_project_identity_ready() -> bool:
    """Return whether the identity registry is already built.

    Memory-only: never touches disk and never lists project records.
    """
    return _identity_ready


def warm_macro_project_identity() -> None:
    """Build the identity registry for off-thread callers.

    Never raises: registry failures degrade to a cached empty projection.
    Safe to call from worker threads; keystroke paths must never call it.
    """
    try:
        _identity_registry()
    except Exception:
        pass


@lru_cache(maxsize=512)
def _canonical_macro_project(ref: str) -> str:
    registry = _identity_registry()
    if registry is None:
        return ref

    alias_map, display_snapshot = registry
    return project_display_name_for_ref(ref, display_snapshot, alias_map) or ref


def canonical_macro_project(ref: str | None) -> str | None:
    """Return the canonical user-facing macro namespace for *ref*.

    Accepts a ProjectSpec directory key, configured ``PROJECT_NAME``, or alias.
    Unknown refs are returned unchanged so ad-hoc namespaces continue to work.
    Registry read failures degrade to the input ref and never raise.
    """
    if ref is None:
        return None
    value = ref.strip()
    if not value:
        return None
    return _canonical_macro_project(value)


def invalidate_macro_project_identity() -> None:
    """Clear process-lifetime macro project identity projections."""
    global _identity_ready  # noqa: PLW0603
    _identity_registry.cache_clear()
    _canonical_macro_project.cache_clear()
    _identity_ready = False


def known_project_namespaces() -> dict[str, Path]:
    """Return enabled project workspaces keyed by canonical macro namespace."""
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
    "canonical_macro_project",
    "invalidate_macro_project_identity",
    "known_project_namespaces",
    "macro_project_identity_ready",
    "warm_macro_project_identity",
]
