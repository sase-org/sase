"""Prompt catalog snapshots for the ACE TUI.

This module keeps disk/config loading out of Textual event handlers. The app
asks workers to build immutable-enough snapshots here, then swaps the finished
snapshot on the UI thread.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    build_xprompt_assist_entries,
)
from sase.config.core import CONFIG_DIR, current_config_token, stat_token
from sase.content_layout import (
    discover_project_root,
    resolve_project_layout,
    resolve_xprompt_file_sources,
)
from sase.xprompt.loader import get_all_xprompts, get_xprompt_search_paths
from sase.xprompt.snippet_bridge import (
    build_xprompt_snippet_entries_from_catalog,
    resolve_snippet_references,
)

PROMPT_SOURCE_SUFFIXES = frozenset({".md", ".yml", ".yaml"})
PROMPT_SOURCE_DEBOUNCE_S = 0.3


@dataclass(frozen=True, slots=True)
class PromptCatalogSnapshot:
    """App-owned prompt/snippet catalog snapshot."""

    generation: int
    source_token: tuple[Any, ...]
    snippets: Mapping[str, str]
    assist_entries_by_project: Mapping[
        str | None,
        tuple[XPromptAssistEntry, ...],
    ]


def build_prompt_catalog_snapshot(
    *,
    generation: int,
    projects: Iterable[str | None],
    previous_source_token: tuple[Any, ...] | None = None,
) -> PromptCatalogSnapshot | None:
    """Build a complete prompt catalog snapshot off the UI thread.

    Returns ``None`` when the prompt source token has not changed. The caller
    keeps publishing the previous snapshot in that case.
    """
    project_tuple = _normalize_prompt_catalog_projects(projects)
    source_token = _prompt_source_token(project_tuple)
    if previous_source_token is not None and source_token == previous_source_token:
        return None

    xprompts = get_all_xprompts(project=None)
    snippets = {
        entry.trigger: entry.template
        for entry in build_xprompt_snippet_entries_from_catalog(xprompts)
    }

    from sase.config import load_merged_config

    merged = load_merged_config()
    ace_cfg = merged.get("ace", {}) if isinstance(merged, dict) else {}
    raw_user_snippets = ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
    if isinstance(raw_user_snippets, dict):
        snippets.update(
            {
                str(key): value
                for key, value in raw_user_snippets.items()
                if isinstance(value, str)
            }
        )
    snippets = resolve_snippet_references(snippets)

    assist_entries_by_project: dict[str | None, tuple[XPromptAssistEntry, ...]] = {}
    for project in project_tuple:
        assist_entries_by_project[project] = tuple(
            build_xprompt_assist_entries(project=project)
        )

    return PromptCatalogSnapshot(
        generation=generation,
        source_token=source_token,
        snippets=dict(snippets),
        assist_entries_by_project=assist_entries_by_project,
    )


def _normalize_prompt_catalog_projects(
    projects: Iterable[str | None],
) -> tuple[str | None, ...]:
    """Return a stable project tuple, always including the default catalog."""
    normalized = {project for project in projects if project}
    return (None, *tuple(sorted(normalized)))


def _prompt_source_token(projects: Iterable[str | None]) -> tuple[Any, ...]:
    """Return a cheap source token for editable prompt/snippet sources."""
    project_tuple = _normalize_prompt_catalog_projects(projects)
    project_dirs = [
        directory
        for project in project_tuple
        if project is not None
        for directory in _project_xprompt_dirs(project)
    ]
    return (
        ("projects", project_tuple),
        ("config", current_config_token()),
        ("xprompt_files", _prompt_file_tokens(get_xprompt_search_paths())),
        ("project_files", _project_prompt_file_tokens(project_dirs)),
    )


def prompt_source_watch_paths(projects: Iterable[str | None]) -> list[Path]:
    """Return directories to watch for editable prompt/snippet source changes."""
    roots: list[Path] = [
        CONFIG_DIR,
        *get_xprompt_search_paths(),
        *[
            directory
            for project in _normalize_prompt_catalog_projects(projects)
            if project is not None
            for directory in _project_xprompt_dirs(project)
        ],
        *[path.parent for path in _project_config_paths()],
    ]

    watch_paths: dict[str, Path] = {}
    for root in roots:
        path = root.expanduser()
        candidate = path if path.exists() else path.parent
        try:
            if candidate.is_dir():
                watch_paths[str(candidate)] = candidate
        except OSError:
            continue
    return list(watch_paths.values())


def prompt_source_change_is_relevant(
    changed_paths: Iterable[Path],
    projects: Iterable[str | None],
) -> bool:
    """Return True when a watcher event touches an editable prompt source."""
    roots = _prompt_source_roots(projects)
    for raw_path in changed_paths:
        path = raw_path.expanduser()
        if _is_config_source_path(path):
            return True
        for root in roots:
            if _path_is_direct_prompt_source(path, root):
                return True
            if path == root:
                return True
    return False


def _prompt_source_roots(projects: Iterable[str | None]) -> tuple[Path, ...]:
    return (
        *tuple(path.expanduser() for path in get_xprompt_search_paths()),
        *tuple(
            directory
            for project in _normalize_prompt_catalog_projects(projects)
            if project is not None
            for directory in _project_xprompt_dirs(project)
        ),
    )


def _prompt_file_tokens(dirs: Iterable[Path]) -> tuple[Any, ...]:
    tokens: list[Any] = []
    for directory in dirs:
        try:
            files = sorted(
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in PROMPT_SOURCE_SUFFIXES
            )
        except OSError:
            files = []
        tokens.append((str(directory), tuple(stat_token(path) for path in files)))
    return tuple(tokens)


def _project_prompt_file_tokens(dirs: Iterable[Path]) -> tuple[Any, ...]:
    return _prompt_file_tokens(dirs)


def _project_xprompt_dirs(project: str) -> tuple[Path, ...]:
    resolved = tuple(
        source.path
        for source in resolve_xprompt_file_sources(project=project)
        if source.path is not None and source.scope == "home_project"
    )
    configured_legacy = CONFIG_DIR / "xprompts" / project
    return tuple(dict.fromkeys((*resolved, configured_legacy)))


def _project_config_paths() -> tuple[Path, ...]:
    root = discover_project_root()
    if root is None:
        return ()
    return resolve_project_layout(root).config.candidates


def _is_config_source_path(path: Path) -> bool:
    if path in _project_config_paths():
        return True
    if path == CONFIG_DIR:
        return True
    if path.parent != CONFIG_DIR:
        return False
    if path.name == "sase.yml":
        return True
    return path.name.startswith("sase_") and path.suffix.lower() in {".yml", ".yaml"}


def _path_is_direct_prompt_source(path: Path, root: Path) -> bool:
    if path.parent == root and path.suffix.lower() in PROMPT_SOURCE_SUFFIXES:
        return True
    return path.parent == root.parent and path.name == root.name


__all__ = [
    "PROMPT_SOURCE_DEBOUNCE_S",
    "PROMPT_SOURCE_SUFFIXES",
    "PromptCatalogSnapshot",
    "build_prompt_catalog_snapshot",
    "prompt_source_change_is_relevant",
    "prompt_source_watch_paths",
]
