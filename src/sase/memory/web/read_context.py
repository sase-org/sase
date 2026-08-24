"""Project-over-home scoped web discovery for read-time CLI consumers."""

from __future__ import annotations

from pathlib import Path

from .discovery import discover_memory_webs
from .feature import memory_webs_enabled
from .models import ScopedMemoryWeb
from .scope import merge_memory_web_scopes


def discover_scoped_memory_webs(
    project_root: Path,
    home_root: Path,
) -> tuple[ScopedMemoryWeb, ...]:
    """Discover and scope-merge webs visible to a read command.

    Returns an empty tuple when the ``memory_webs`` flag is disabled, so
    every web/strand selector resolves as unknown, matching an ordinary note
    with ``web: true`` frontmatter that is simply ignored.
    """
    if not memory_webs_enabled():
        return ()

    project_discovery = discover_memory_webs(project_root)
    resolved_project = project_root.resolve(strict=False)
    resolved_home = home_root.resolve(strict=False)
    home_webs = (
        ()
        if resolved_home == resolved_project
        else discover_memory_webs(home_root).webs
    )
    return merge_memory_web_scopes(
        project_webs=project_discovery.webs,
        home_webs=home_webs,
    )


__all__ = ["discover_scoped_memory_webs"]
