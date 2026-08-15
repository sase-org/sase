"""Configured linked repository resolution for launched agents.

This module is the stable public facade for linked-repository support. Focused
resolution support, clone paths, workspace lifecycle, environment handling,
marker persistence, and configuration helpers live in neighboring modules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import re
import subprocess as subprocess  # Re-exported for compatibility with test patches.
from typing import Any

from sase._linked_repo_config import (
    AGENTS_SIDECAR_ROLE,
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_BEADS_DESCRIPTION,
    DEFAULT_LINKED_REPOS_CONFIG_KEY,
    DEFAULT_PLANS_DESCRIPTION,
    DEFAULT_RESEARCH_DESCRIPTION,
    HIDDEN_SIDECAR_ROLES,
    LINKED_REPOS_CONFIG_KEY,
    REPOS_CONFIG_KEY,
    SIBLING_REPOS_CONFIG_KEY,
    _DEFAULT_LINKED_REPO_MARKER,
    _SIDECAR_REMOTE_URL_KEY,
    _SIDECAR_REPO_MARKER,
    _SIDECAR_ROLE_KEY,
    _SIDECAR_SLUG_KEY,
    inject_default_linked_repos,
    merged_repo_entries_from_config,
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
    OpenedRepoKind,
    opened_external_repo_records,
    opened_linked_repo_names,
    opened_linked_repo_records,
    opened_linked_repo_workspace_dirs,
    opened_repo_records,
    record_opened_external_repo,
    record_opened_linked_repo,
    record_opened_repo,
)
from sase._linked_repo_paths import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    SIDECAR_REPO_CLONES_SUBDIR,
    external_repo_clone_dir,
    hidden_sidecar_clone_dir,
    linked_repo_clone_dir,
    sdd_sidecar_clone_dirname,
    sidecar_repo_clone_dir,
)
from sase._linked_repo_workspaces import (
    clear_workspace_repos,
    materialize_linked_repo_workspace,
    refresh_clean_linked_checkout,
)

# Preserve the historical class identity for introspection and pickling even
# though their implementations now live in the environment helper module.
LinkedRepoResolution.__module__ = __name__
_ResolvedLinkedRepo.__module__ = __name__

__all__ = [
    "AGENTS_SIDECAR_ROLE",
    "DEFAULT_AGENTS_DESCRIPTION",
    "DEFAULT_BEADS_DESCRIPTION",
    "DEFAULT_LINKED_REPOS_CONFIG_KEY",
    "DEFAULT_PLANS_DESCRIPTION",
    "DEFAULT_RESEARCH_DESCRIPTION",
    "EXTERNAL_REPO_CLONES_SUBDIR",
    "SIDECAR_REPO_CLONES_SUBDIR",
    "LINKED_REPO_CLONES_SUBDIR",
    "LINKED_REPO_ENV_PREFIX",
    "LINKED_REPO_ENV_SUFFIXES",
    "LINKED_REPOS_CONFIG_KEY",
    "LINKED_REPOS_JSON_ENV",
    "HIDDEN_SIDECAR_ROLES",
    "OPENED_LINKED_FILENAME",
    "OPENED_SIBLINGS_FILENAME",
    "OpenedRepoKind",
    "REPOS_CONFIG_KEY",
    "SIBLING_REPO_ENV_PREFIX",
    "SIBLING_REPO_ENV_SUFFIXES",
    "SIBLING_REPOS_CONFIG_KEY",
    "SIBLING_REPOS_JSON_ENV",
    "LinkedRepoResolution",
    "apply_linked_repo_env",
    "clear_workspace_repos",
    "external_repo_clone_dir",
    "hidden_sidecar_clone_dir",
    "sidecar_repo_clone_dir",
    "is_legacy_static_linked_repo_record",
    "linked_repo_clone_dir",
    "linked_repo_metadata_from_env",
    "materialize_linked_repo_workspace",
    "refresh_clean_linked_checkout",
    "opened_external_repo_records",
    "opened_linked_repo_names",
    "opened_linked_repo_records",
    "opened_linked_repo_workspace_dirs",
    "opened_repo_records",
    "record_opened_external_repo",
    "record_opened_linked_repo",
    "record_opened_repo",
    "resolve_linked_repos_for_project",
    "sdd_sidecar_clone_dirname",
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
    entries, merge_warnings = merged_repo_entries_from_config(
        resolved_config,
        primary_workspace_dir=primary_workspace_dir,
    )
    entries = inject_default_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        local_config=config if config is not None else local_config,
        config=resolved_config,
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
        is_sidecar = entry.get(_SIDECAR_REPO_MARKER) is True
        disabled = entry.get("disabled") is True
        sidecar_role = _entry_text(entry, _SIDECAR_ROLE_KEY)
        sidecar_slug = _entry_text(entry, _SIDECAR_SLUG_KEY)
        remote_url = _entry_text(entry, _SIDECAR_REMOTE_URL_KEY)
        if disabled:
            continue
        if is_sidecar and sidecar_role in HIDDEN_SIDECAR_ROLES:
            continue
        if not isinstance(name, str) or not name.strip():
            kind = "sidecar" if is_sidecar else "linked repo"
            resolution_warnings.append(f"Skipping {kind} with missing name")
            continue
        if not isinstance(raw_path, str) or not raw_path.strip():
            resolution_warnings.append(
                f"Skipping {'sidecar' if is_sidecar else 'linked repo'} "
                f"{name!r} with missing path"
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
            if not is_sidecar:
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
                sidecar_dirname=sidecar_role if is_sidecar else None,
                expected_remote_url=remote_url,
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
                kind="sidecar" if is_sidecar else "linked",
                slug=sidecar_slug or None,
                remote_url=remote_url or None,
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


def _resolve_workspace_dir(
    primary_dir: str,
    *,
    name: str,
    host_primary_dir: str,
    workspace_num: int,
    config: Mapping[str, Any],
    materialize: bool,
    sidecar_dirname: str | None = None,
    expected_remote_url: str = "",
) -> str:
    if workspace_num <= 1:
        if materialize and sidecar_dirname is not None and expected_remote_url:
            return materialize_linked_repo_workspace(
                primary_dir=primary_dir,
                workspace_dir=primary_dir,
                workspace_num=workspace_num,
                expected_remote_url=expected_remote_url,
            )
        return primary_dir

    from sase.workspace_provider.store import WorkspaceStore

    host_workspace_dir = (
        WorkspaceStore(host_primary_dir, config=config)
        .resolve(workspace_num)
        .checkout_dir.rstrip("/")
    )
    sidecar_dirname = sidecar_dirname or sdd_sidecar_clone_dirname(
        host_primary_dir,
        name,
        config=config,
    )
    target = (
        sidecar_repo_clone_dir(host_workspace_dir, sidecar_dirname)
        if sidecar_dirname is not None
        else linked_repo_clone_dir(host_workspace_dir, name)
    )
    if not materialize:
        return target

    return materialize_linked_repo_workspace(
        primary_dir=primary_dir,
        workspace_dir=target,
        workspace_num=workspace_num,
        expected_remote_url=expected_remote_url or None,
    )


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


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
