"""Display-only project name resolution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def project_display_name_for(
    key: str,
    projects_root: Path | str | None = None,
) -> str:
    """Return the logical project name for *key*, falling back to *key*."""
    return _project_display_name_map_cached(projects_root).get(key, key)


__all__ = [
    "project_display_name_for",
]
