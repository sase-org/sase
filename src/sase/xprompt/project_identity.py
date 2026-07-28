"""Canonical project namespace helpers for xprompt lookup."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sase.project_aliases import load_project_alias_map
from sase.project_display_names import (
    ProjectDisplaySnapshot,
    load_project_display_snapshot,
)
from sase.xprompt.loader_sources import get_known_project_workspaces


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
    project_key = alias_map.get(ref, ref)
    if project_key != ref and project_key not in display_snapshot:
        return ref
    return display_snapshot.label_for(project_key)


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
    "known_project_namespaces",
]
