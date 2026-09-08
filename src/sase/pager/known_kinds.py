"""Freeze artifact-reference kind catalogs for pager document scanning."""

from __future__ import annotations

from collections.abc import Iterable

from sase.artifact_ref_models import ArtifactRefContext
from sase.pager.link_context import LinkResolutionContext
from sase.pager.owner import artifact_context_for_link_context


def freeze_known_kinds(kinds: Iterable[str] = ()) -> tuple[str, ...]:
    """Return a stable, de-duplicated kind tuple suitable for section storage."""
    return tuple(dict.fromkeys(kind for kind in kinds if kind))


def known_kinds_from_artifact_context(
    context: ArtifactRefContext | None,
) -> tuple[str, ...]:
    """Return the configured scan kinds already carried by *context*."""
    if context is None:
        return ()
    try:
        return freeze_known_kinds(context.known_kinds)
    except (ImportError, RuntimeError, TypeError, ValueError):
        return ()


def known_kinds_from_link_context(
    context: LinkResolutionContext | None,
) -> tuple[str, ...]:
    """Return scan kinds discoverable from *context* outside the paint path."""
    if context is None:
        return ()
    try:
        artifact_context = artifact_context_for_link_context(context)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return ()
    return known_kinds_from_artifact_context(artifact_context)


__all__ = [
    "freeze_known_kinds",
    "known_kinds_from_artifact_context",
    "known_kinds_from_link_context",
]
