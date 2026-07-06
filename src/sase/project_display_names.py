"""Display-only project name resolution helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import project_display_name_map


@dataclass(frozen=True)
class _ProjectDisplayNameCacheEntry:
    signature: tuple[str, int]
    display_names: dict[str, str]


_PROJECT_DISPLAY_NAME_CACHE: _ProjectDisplayNameCacheEntry | None = None


def _projects_dir_signature(projects_root: Path) -> tuple[str, int] | None:
    try:
        stat = projects_root.stat()
    except OSError:
        return None
    return (str(projects_root), stat.st_mtime_ns)


def _project_display_name_map_cached(
    projects_root: Path | str | None = None,
) -> dict[str, str]:
    """Return cached ``directory key -> user-facing name`` mappings."""
    global _PROJECT_DISPLAY_NAME_CACHE  # noqa: PLW0603

    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    signature = _projects_dir_signature(root)
    if (
        signature is not None
        and _PROJECT_DISPLAY_NAME_CACHE is not None
        and _PROJECT_DISPLAY_NAME_CACHE.signature == signature
    ):
        return dict(_PROJECT_DISPLAY_NAME_CACHE.display_names)

    try:
        display_names = project_display_name_map(
            list_project_records(root, "all", include_home=True)
        )
    except Exception:
        display_names = {}

    if signature is not None:
        _PROJECT_DISPLAY_NAME_CACHE = _ProjectDisplayNameCacheEntry(
            signature=signature,
            display_names=dict(display_names),
        )
    return dict(display_names)


def project_display_name_map_signature(
    projects_root: Path | str | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return a stable signature for the current display-name map."""
    return tuple(sorted(_project_display_name_map_cached(projects_root).items()))


def attach_project_display_names(
    agents: Iterable[Any],
    projects_root: Path | str | None = None,
) -> None:
    """Populate display-only project names on duck-typed agent objects."""
    candidates: list[tuple[Any, str]] = []
    for agent in agents:
        if not hasattr(agent, "project_display_name"):
            continue
        project_file = getattr(agent, "project_file", None)
        if not project_file:
            continue
        key = Path(str(project_file)).parent.name
        candidates.append((agent, key))

    if not candidates:
        return

    display_names = _project_display_name_map_cached(projects_root)
    for agent, key in candidates:
        display = display_names.get(key)
        agent.project_display_name = display if display and display != key else None


def project_display_name_for(
    key: str,
    projects_root: Path | str | None = None,
) -> str:
    """Return the logical project name for *key*, falling back to *key*."""
    return _project_display_name_map_cached(projects_root).get(key, key)


def humanize_vcs_refs_in_text(
    text: str,
    projects_root: Path | str | None = None,
) -> str:
    """Rewrite canonical project directory keys in VCS tags to display names.

    Applies :func:`humanize_project_refs_in_prompt` using the mtime-keyed
    display-name cache, so per-keystroke callers (e.g. ``<ctrl+p>`` MRU
    cycling) pay only a ``stat()`` plus dict lookup rather than a fresh disk
    read. Text without a display-name override for its ref is returned
    unchanged.
    """
    from sase.project_aliases import humanize_project_refs_in_prompt

    return humanize_project_refs_in_prompt(
        text, _project_display_name_map_cached(projects_root)
    )


__all__ = [
    "attach_project_display_names",
    "humanize_vcs_refs_in_text",
    "project_display_name_map_signature",
    "project_display_name_for",
]
