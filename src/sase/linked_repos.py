"""Configured linked repository resolution for launched agents.

This module is the stable public facade for linked-repository support. Focused
environment, marker-persistence, and configuration helpers live in neighboring
internal modules; resolution and materialization remain here because callers
patch these public functions at runtime.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import errno
import os
from pathlib import Path
import re
import shutil
from typing import Any

from sase._linked_repo_config import (
    DEFAULT_LINKED_REPOS_CONFIG_KEY,
    DEFAULT_PLANS_DESCRIPTION,
    DEFAULT_RESEARCH_DESCRIPTION,
    LINKED_REPOS_CONFIG_KEY,
    SIBLING_REPOS_CONFIG_KEY,
    _DEFAULT_LINKED_REPO_MARKER,
    inject_default_linked_repos,
    merged_entries_from_config,
    normalize_path,
    read_project_local_config,
    resolution_config,
    resolve_config_path,
)
from sase._linked_repo_env import (
    LINKED_REPO_ENV_PREFIX,
    LINKED_REPO_ENV_SUFFIXES,
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPO_ENV_PREFIX,
    SIBLING_REPO_ENV_SUFFIXES,
    SIBLING_REPOS_JSON_ENV,
    LinkedRepoResolution,
    ResolvedLinkedRepo as _ResolvedLinkedRepo,
    apply_linked_repo_env,
    is_legacy_static_linked_repo_record,
    linked_repo_metadata_from_env,
    scrub_linked_repo_env,
)
from sase._linked_repo_markers import (
    OPENED_LINKED_FILENAME,
    OPENED_SIBLINGS_FILENAME,
    opened_linked_repo_names,
    opened_linked_repo_records,
    opened_linked_repo_workspace_dirs,
    record_opened_linked_repo,
)

# Host-scoped normal linked clones are launch-scoped and live separately from
# durable SDD companion clones. The cache is internal and is never exposed to
# agents through environment variables or opened-workspace markers.
COMPANION_REPO_CLONES_SUBDIR = ("sase", "repos")
LINKED_REPO_CLONES_SUBDIR = ("sase", "repos", "linked")
LINKED_REPO_CACHE_SUBDIR = ("sase", "repos", ".linked-cache")

# Preserve the historical class identity for introspection and pickling even
# though their implementations now live in the environment helper module.
LinkedRepoResolution.__module__ = __name__
_ResolvedLinkedRepo.__module__ = __name__

__all__ = [
    "DEFAULT_LINKED_REPOS_CONFIG_KEY",
    "DEFAULT_PLANS_DESCRIPTION",
    "DEFAULT_RESEARCH_DESCRIPTION",
    "COMPANION_REPO_CLONES_SUBDIR",
    "LINKED_REPO_CLONES_SUBDIR",
    "LINKED_REPO_CACHE_SUBDIR",
    "LINKED_REPO_ENV_PREFIX",
    "LINKED_REPO_ENV_SUFFIXES",
    "LINKED_REPOS_CONFIG_KEY",
    "LINKED_REPOS_JSON_ENV",
    "OPENED_LINKED_FILENAME",
    "OPENED_SIBLINGS_FILENAME",
    "SIBLING_REPO_ENV_PREFIX",
    "SIBLING_REPO_ENV_SUFFIXES",
    "SIBLING_REPOS_CONFIG_KEY",
    "SIBLING_REPOS_JSON_ENV",
    "LinkedRepoResolution",
    "apply_linked_repo_env",
    "clear_linked_repo_clones",
    "companion_repo_clone_dir",
    "is_legacy_static_linked_repo_record",
    "is_sdd_companion_repo",
    "linked_repo_clone_dir",
    "linked_repo_metadata_from_env",
    "materialize_linked_repo_workspace",
    "opened_linked_repo_names",
    "opened_linked_repo_records",
    "opened_linked_repo_workspace_dirs",
    "record_opened_linked_repo",
    "resolve_linked_repos_for_project",
    "scrub_linked_repo_env",
]


def resolve_linked_repos_for_project(
    *,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    config: Mapping[str, Any] | None = None,
    materialize: bool = True,
) -> LinkedRepoResolution:
    """Resolve configured linked repos for a launched project workspace."""

    primary_workspace_dir = _primary_workspace_dir(project_file, workspace_dir)
    local_config = read_project_local_config(primary_workspace_dir)
    resolved_config = resolution_config(primary_workspace_dir, config)
    entries, merge_warnings = merged_entries_from_config(resolved_config)
    entries = inject_default_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        local_config=config if config is not None else local_config,
    )
    resolution = _resolve_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        workspace_num=workspace_num,
        config=resolved_config,
        materialize=materialize,
    )
    if merge_warnings:
        return LinkedRepoResolution(
            resolution.repos,
            (*merge_warnings, *resolution.warnings),
        )
    return resolution


def _resolve_linked_repos(
    entries: Sequence[Mapping[str, Any]],
    *,
    primary_workspace_dir: str,
    workspace_num: int,
    config: Mapping[str, Any],
    materialize: bool = True,
) -> LinkedRepoResolution:
    """Resolve merged linked-repo config entries into concrete paths."""

    primary_root = normalize_path(primary_workspace_dir)
    resolved: list[_ResolvedLinkedRepo] = []
    resolution_warnings: list[str] = []
    used_env_names: set[str] = set()

    for entry in entries:
        name = entry.get("name")
        raw_path = entry.get("path")
        auto_clone = entry.get("auto_clone") is True
        if not isinstance(name, str) or not name.strip():
            resolution_warnings.append("Skipping linked repo with missing name")
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            resolution_warnings.append(
                f"Skipping linked repo {name!r} with missing path"
            )
            continue

        if "workspace" in entry:
            resolution_warnings.append(
                f"Linked repo {name!r} uses deprecated workspace configuration; "
                "ignoring it because linked workspaces are now host-scoped"
            )

        primary_dir = resolve_config_path(raw_path, relative_to=primary_root)
        if not Path(primary_dir).is_dir():
            if entry.get(_DEFAULT_LINKED_REPO_MARKER) is True:
                continue
            resolution_warnings.append(
                f"Skipping linked repo {name!r}: primary path does not exist: "
                f"{primary_dir}"
            )
            continue

        try:
            resolved_workspace_dir = _resolve_workspace_dir(
                primary_dir,
                name=name,
                host_primary_dir=primary_root,
                workspace_num=workspace_num,
                config=config,
                materialize=materialize,
            )
        except RuntimeError as exc:
            resolution_warnings.append(f"Skipping linked repo {name!r}: {exc}")
            continue

        env_name = _unique_env_name(_sanitize_env_name(name), used_env_names)
        used_env_names.add(env_name)
        resolved.append(
            _ResolvedLinkedRepo(
                name=name,
                env_name=env_name,
                primary_dir=primary_dir,
                workspace_dir=resolved_workspace_dir,
                workspace_num=workspace_num,
                auto_clone=auto_clone,
            )
        )

    return LinkedRepoResolution(tuple(resolved), tuple(resolution_warnings))


def _primary_workspace_dir(project_file: str, workspace_dir: str) -> str:
    from sase.workspace_provider.utils import parse_workspace_dir

    parsed = parse_workspace_dir(project_file)
    if parsed:
        return normalize_path(parsed)
    fallback = workspace_dir or os.getcwd()
    return normalize_path(fallback)


def linked_repo_clone_dir(host_checkout: str | Path, name: str) -> str:
    """Return the canonical host-scoped clone path for linked repo *name*."""

    return normalize_path(
        str(Path(host_checkout).joinpath(*LINKED_REPO_CLONES_SUBDIR, name))
    )


def companion_repo_clone_dir(host_checkout: str | Path, name: str) -> str:
    """Return the durable host-scoped clone path for SDD companion *name*."""

    return normalize_path(
        str(Path(host_checkout).joinpath(*COMPANION_REPO_CLONES_SUBDIR, name))
    )


def _repo_basename(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1]


def _sdd_companion_repo_names(primary_workspace_dir: str | Path) -> frozenset[str]:
    """Return authoritative SDD companion basenames for a host project."""

    from sase.sdd.store import read_sdd_store_record

    primary = Path(primary_workspace_dir).expanduser().resolve(strict=False)
    record = read_sdd_store_record(primary)
    if record is not None:
        return frozenset(
            _repo_basename(companion.repo)
            for companion in (record.plans, record.research)
            if companion is not None
        )

    project_name = primary.name
    if not project_name:
        return frozenset()
    return frozenset({f"{project_name}--plans", f"{project_name}--research"})


def is_sdd_companion_repo(
    primary_workspace_dir: str | Path,
    name: str,
) -> bool:
    """Return whether *name* is an SDD companion of the host project."""

    return name in _sdd_companion_repo_names(primary_workspace_dir)


def _linked_repo_cache_dir(host_checkout: str | Path, name: str) -> Path:
    return Path(host_checkout).joinpath(*LINKED_REPO_CACHE_SUBDIR, name)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def clear_linked_repo_clones(workspace_dir: str | Path) -> None:
    """Stash normal linked clones in the internal cache and empty their root."""

    linked_root = Path(workspace_dir).joinpath(*LINKED_REPO_CLONES_SUBDIR)
    if not linked_root.is_dir():
        return

    cache_root = Path(workspace_dir).joinpath(*LINKED_REPO_CACHE_SUBDIR)
    for child in list(linked_root.iterdir()):
        if child.is_dir() and not child.is_symlink():
            cache_root.mkdir(parents=True, exist_ok=True)
            cached = cache_root / child.name
            if cached.exists() or cached.is_symlink():
                _remove_path(cached)
            os.rename(child, cached)
        elif child.exists() or child.is_symlink():
            _remove_path(child)

    # Concurrent or unusual filesystem activity must not leave an unaudited
    # ready-made entry in the launch-visible directory.
    for child in list(linked_root.iterdir()):
        _remove_path(child)


def _restore_linked_repo_clone(host_checkout: Path, name: str) -> None:
    target = Path(linked_repo_clone_dir(host_checkout, name))
    cached = _linked_repo_cache_dir(host_checkout, name)
    if target.exists() or target.is_symlink() or not cached.exists():
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(cached, target)
    except FileNotFoundError:
        # A parallel opener already consumed the cache entry.
        return
    except OSError as exc:
        if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
            raise
        # A parallel opener populated the destination first.
        return


def _linked_repo_clone_location(
    workspace_dir: str | Path,
) -> tuple[Path, str, bool] | None:
    """Return ``(host_checkout, name, is_companion)`` for a known layout."""

    path = Path(workspace_dir).expanduser().resolve(strict=False)
    layouts = (
        (LINKED_REPO_CLONES_SUBDIR, False),
        (COMPANION_REPO_CLONES_SUBDIR, True),
    )
    for subdir, is_companion in layouts:
        parent_parts = path.parent.parts
        if len(parent_parts) < len(subdir):
            continue
        if tuple(parent_parts[-len(subdir) :]) != subdir:
            continue
        host_checkout = path.parent
        for _ in subdir:
            host_checkout = host_checkout.parent
        return host_checkout, path.name, is_companion
    return None


def _resolve_workspace_dir(
    primary_dir: str,
    *,
    name: str,
    host_primary_dir: str,
    workspace_num: int,
    config: Mapping[str, Any],
    materialize: bool,
) -> str:
    if workspace_num <= 1:
        return primary_dir

    from sase.workspace_provider.store import WorkspaceStore

    host_workspace_dir = (
        WorkspaceStore(host_primary_dir, config=config)
        .resolve(workspace_num)
        .checkout_dir.rstrip("/")
    )
    target = (
        companion_repo_clone_dir(host_workspace_dir, name)
        if is_sdd_companion_repo(host_primary_dir, name)
        else linked_repo_clone_dir(host_workspace_dir, name)
    )
    if not materialize:
        return target

    return materialize_linked_repo_workspace(
        primary_dir=primary_dir,
        workspace_dir=target,
        workspace_num=workspace_num,
    )


def materialize_linked_repo_workspace(
    *, primary_dir: str, workspace_dir: str, workspace_num: int
) -> str:
    """Clone a host-scoped linked workspace and initialize its SDD companion."""

    from sase.workspace_provider.utils import ensure_git_clone_at

    location = _linked_repo_clone_location(workspace_dir)
    if location is not None:
        host_checkout, name, is_companion = location
        from sase.workspace_provider.git_exclude import ensure_git_info_exclude_entry

        ensure_git_info_exclude_entry(str(host_checkout), "/sase/repos/")
        if is_companion:
            workspace_dir = companion_repo_clone_dir(host_checkout, name)
        else:
            workspace_dir = linked_repo_clone_dir(host_checkout, name)
            _restore_linked_repo_clone(host_checkout, name)

    checkout_dir = ensure_git_clone_at(primary_dir, workspace_num, workspace_dir)
    try:
        from sase.sdd.store import ensure_workspace_sdd_clone

        ensure_workspace_sdd_clone(checkout_dir, workspace_num)
    except Exception:
        pass
    return normalize_path(checkout_dir)


def _sanitize_env_name(name: str) -> str:
    env_name = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").upper()
    return env_name or "REPO"


def _unique_env_name(base: str, used: set[str]) -> str:
    if base not in used:
        return base
    index = 2
    while f"{base}_{index}" in used:
        index += 1
    return f"{base}_{index}"
