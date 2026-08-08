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
    resolve_memory_file_sources,
    resolve_project_layout,
    resolve_xprompt_file_sources,
)
from sase.core.snippet_catalog_facade import compose_snippet_catalog
from sase.xprompt.loader import (
    detect_project,
    get_all_xprompts,
    get_xprompt_search_paths,
)
from sase.xprompt.project_identity import (
    canonical_xprompt_project,
    known_project_namespaces,
)
from sase.xprompt.snippet_bridge import build_xprompt_snippet_entries_from_catalog

PROMPT_SOURCE_SUFFIXES = frozenset({".md", ".yml", ".yaml"})
PROMPT_SOURCE_DEBOUNCE_S = 0.3


@dataclass(frozen=True, slots=True)
class PromptCatalogSnapshot:
    """App-owned prompt/snippet catalog snapshot."""

    generation: int
    source_token: tuple[Any, ...]
    explicit_snippets: Mapping[str, str]
    snippets: Mapping[str, str]
    user_snippets: Mapping[str, str]
    assist_entries_by_project: Mapping[
        str | None,
        tuple[XPromptAssistEntry, ...],
    ]


def build_prompt_catalog_snapshot(
    *,
    generation: int,
    projects: Iterable[str | None],
    previous_source_token: tuple[Any, ...] | None = None,
    pending_snippet_saves: Mapping[str, str] | None = None,
    config_dirty: bool = False,
) -> PromptCatalogSnapshot | None:
    """Build a complete prompt catalog snapshot off the UI thread.

    Returns ``None`` when the prompt source token has not changed. The caller
    keeps publishing the previous snapshot in that case.
    """
    if config_dirty:
        from sase.config.core import clear_config_cache

        clear_config_cache()

    project_tuple = _normalize_prompt_catalog_projects(projects)
    source_token = _prompt_source_token(project_tuple)
    if previous_source_token is not None and source_token == previous_source_token:
        return None

    xprompts = get_all_xprompts(project=None)
    explicit_snippets = {
        entry.trigger: entry.template
        for entry in build_xprompt_snippet_entries_from_catalog(xprompts)
    }

    from sase.config import load_merged_config

    merged = load_merged_config()
    ace_cfg = merged.get("ace", {}) if isinstance(merged, dict) else {}
    raw_user_snippets = ace_cfg.get("snippets", {}) if isinstance(ace_cfg, dict) else {}
    user_snippets: dict[str, str] = {}
    if isinstance(raw_user_snippets, dict):
        user_snippets = {
            str(key): value
            for key, value in raw_user_snippets.items()
            if isinstance(value, str)
        }
        explicit_snippets.update(user_snippets)
    if pending_snippet_saves:
        explicit_snippets.update(pending_snippet_saves)
    composed_snippets = compose_snippet_catalog(explicit_snippets)

    assist_entries_by_project: dict[str | None, tuple[XPromptAssistEntry, ...]] = {}
    for project in project_tuple:
        assist_entries_by_project[project] = tuple(
            build_xprompt_assist_entries(project=project)
        )

    return PromptCatalogSnapshot(
        generation=generation,
        source_token=source_token,
        explicit_snippets=dict(explicit_snippets),
        snippets=dict(composed_snippets.templates),
        user_snippets=user_snippets,
        assist_entries_by_project=assist_entries_by_project,
    )


def compose_pending_snippet_saves(
    explicit_snippets: Mapping[str, str],
    pending_snippet_saves: Mapping[str, str],
) -> dict[str, str]:
    """Overlay and compose session-local snippet saves off the UI thread."""
    explicit = dict(explicit_snippets)
    explicit.update(pending_snippet_saves)
    return compose_snippet_catalog(explicit).templates


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
    memory_dirs = [
        directory
        for project in project_tuple
        for directory in _memory_source_dirs(project)
    ]
    return (
        ("projects", project_tuple),
        ("config", current_config_token()),
        ("xprompt_files", _prompt_file_tokens(get_xprompt_search_paths())),
        ("project_files", _project_prompt_file_tokens(project_dirs)),
        ("memory_files", _prompt_file_tokens(memory_dirs)),
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
        *[
            directory
            for project in _normalize_prompt_catalog_projects(projects)
            for directory in _memory_source_dirs(project)
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


def prompt_source_change_touches_config(changed_paths: Iterable[Path]) -> bool:
    """Return whether a watcher burst may contain a merged-config edit.

    This intentionally uses only path names so the UI-thread watcher callback
    never discovers project roots, stats files, or loads configuration.  A
    conservatively classified xprompt named ``sase.yml`` merely causes one
    extra fresh config read in the catalog worker.
    """
    for raw_path in changed_paths:
        path = raw_path.expanduser()
        if path == CONFIG_DIR:
            return True
        if path.name == "sase.yml":
            return True
        if path.name.startswith("sase_") and path.suffix.lower() in {
            ".yml",
            ".yaml",
        }:
            return True
    return False


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
    """Return per-project xprompt source directories to token/watch.

    The project string is normalized first: these directories are named after
    the canonical user-facing project namespace, so a caller passing a
    ProjectSpec directory key or alias must still watch the same paths.
    """
    canonical = canonical_xprompt_project(project) or project
    resolved = tuple(
        source.path
        for source in resolve_xprompt_file_sources(project=canonical)
        if source.path is not None and source.scope == "home_project"
    )
    configured_legacy = CONFIG_DIR / "xprompts" / canonical
    return tuple(dict.fromkeys((*resolved, configured_legacy)))


def _memory_source_dirs(project: str | None) -> tuple[Path, ...]:
    """Return flat memory roots that can contribute ``memory/<stem>`` entries."""
    canonical = canonical_xprompt_project(project) if project is not None else None
    detected = canonical_xprompt_project(detect_project())
    if canonical is not None and detected != canonical:
        workspace = known_project_namespaces().get(canonical)
        if workspace is not None:
            sources = resolve_memory_file_sources(
                project=canonical,
                project_root=workspace,
            )
        else:
            sources = resolve_memory_file_sources(
                project=canonical,
                include_discovered_project=False,
            )
    else:
        sources = resolve_memory_file_sources(project=canonical)
    roots = [candidate for source in sources for candidate in source.paths.candidates]
    return tuple(dict.fromkeys(roots))


def _project_config_paths() -> tuple[Path, ...]:
    root = discover_project_root()
    if root is None:
        return ()
    return resolve_project_layout(root).config.candidates


__all__ = [
    "PROMPT_SOURCE_DEBOUNCE_S",
    "PROMPT_SOURCE_SUFFIXES",
    "PromptCatalogSnapshot",
    "build_prompt_catalog_snapshot",
    "compose_pending_snippet_saves",
    "prompt_source_change_touches_config",
    "prompt_source_watch_paths",
]
