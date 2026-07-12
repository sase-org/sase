"""Display-only project name resolution helpers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from sase.core.paths import make_safe_filename, sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import project_display_name_map


@dataclass(frozen=True)
class _ProjectDisplayNameCacheEntry:
    signature: tuple[str, int]
    display_names: dict[str, str]


_PROJECT_DISPLAY_NAME_CACHE: _ProjectDisplayNameCacheEntry | None = None
_CL_NAME_TOKEN_RE = re.compile(
    r"(?P<prefix>^|(?<=[\s(\[{]))"
    r"(?P<name>[A-Za-z0-9_.~-]+)"
    r"(?P<suffix>(?=$|[\s)\]},.!?;:\"']))"
)


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


def _humanize_cl_name_with_map(name: str, display_names: dict[str, str]) -> str:
    if not display_names or not name:
        return name

    if name in display_names:
        return display_names[name]
    if "_" not in name:
        return name

    for key, display in sorted(
        display_names.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        prefix = f"{key}_"
        if name.startswith(prefix):
            return f"{display}_{name[len(prefix) :]}"
    return name


def humanize_cl_name(
    name: str,
    projects_root: Path | str | None = None,
) -> str:
    """Rewrite a ChangeSpec/agent name that starts with a project key."""
    return _humanize_cl_name_with_map(
        name,
        _project_display_name_map_cached(projects_root),
    )


def humanize_cl_names_in_text(
    text: str,
    projects_root: Path | str | None = None,
) -> str:
    """Rewrite standalone ChangeSpec/agent name tokens in display text."""
    display_names = _project_display_name_map_cached(projects_root)
    if not text or not display_names:
        return text

    def replace(match: re.Match[str]) -> str:
        return (
            match.group("prefix")
            + _humanize_cl_name_with_map(match.group("name"), display_names)
            + match.group("suffix")
        )

    return _CL_NAME_TOKEN_RE.sub(replace, text)


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


# symvision: https://github.com/sase-org/sase-telegram.git
def humanize_safe_stem(
    stem: str,
    projects_root: Path | str | None = None,
) -> str:
    """Rewrite a filename-safe project/ChangeSpec stem prefix for display."""
    display_names = _project_display_name_map_cached(projects_root)
    if not stem or not display_names:
        return stem

    safe_prefixes: list[tuple[str, str]] = []
    for key, display in display_names.items():
        safe_key = make_safe_filename(key)
        if safe_key:
            safe_prefixes.append((safe_key, display))
    for safe_key, display in sorted(
        safe_prefixes,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if stem == safe_key:
            return display
        for separator in ("-", "_"):
            prefix = f"{safe_key}{separator}"
            if stem.startswith(prefix):
                return f"{display}{separator}{stem[len(prefix) :]}"
    return stem


__all__ = [
    "attach_project_display_names",
    "humanize_cl_names_in_text",
    "humanize_cl_name",
    "humanize_safe_stem",
    "humanize_vcs_refs_in_text",
    "project_display_name_map_signature",
    "project_display_name_for",
]
