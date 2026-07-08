"""Resolve the repo set for ``sase vcs log`` from the current workspace.

Reuses existing resolvers only — the primary workspace dir, the linked-repo
resolver, and the SDD store resolver — so ``sase vcs log`` sees exactly the
constellation every other SASE surface does. Resolution is read-only:
linked repos are resolved with ``materialize=False`` and the SDD store is
only inspected, never created.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.project_display_names import project_display_name_for
from sase.vcs_log.models import LogRepo

_KIND_ORDER = {"primary": 0, "linked": 1, "sdd": 2}


@dataclass(frozen=True)
class ResolvedRepos:
    """Repos to log plus any non-fatal resolution warnings."""

    repos: list[LogRepo]
    warnings: list[str]


def resolve_log_repos(
    *,
    cwd: str,
    repo_filters: Sequence[str] = (),
    current_only: bool = False,
) -> ResolvedRepos:
    """Resolve the primary + linked + SDD repos for the timeline.

    When *cwd* is not inside a recognized SASE project, falls back to
    logging just the current repo (or a single warning when *cwd* is not a
    VCS repository at all). ``--repo`` filtering and ``--current-only`` are
    applied here so downstream collection sees the final repo set.
    """
    from sase.main.utils import ensure_project_file_and_get_workspace_num

    warnings: list[str] = []
    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num(create_missing=False)
    )

    if project_file and project_name:
        repos = _resolve_project_repos(
            project_file=project_file,
            project_name=project_name,
            workspace_num=workspace_num if workspace_num is not None else 0,
            cwd=cwd,
            current_only=current_only,
            warnings=warnings,
        )
    else:
        repos = _resolve_fallback_repos(cwd, warnings)

    repos.sort(key=lambda repo: (_KIND_ORDER.get(repo.kind, 9), repo.name))

    if repo_filters:
        repos = _apply_filters(repos, list(repo_filters), warnings)

    return ResolvedRepos(repos=repos, warnings=warnings)


def _resolve_project_repos(
    *,
    project_file: str,
    project_name: str,
    workspace_num: int,
    cwd: str,
    current_only: bool,
    warnings: list[str],
) -> list[LogRepo]:
    primary_dir = _primary_workspace_dir(project_file, cwd, workspace_num)
    repos: list[LogRepo] = [
        LogRepo(
            name=project_display_name_for(project_name),
            path=primary_dir,
            kind="primary",
        )
    ]

    if current_only:
        return repos

    repos.extend(_resolve_linked_repos(project_file, primary_dir, warnings))
    sdd_repo = _resolve_sdd_repo(primary_dir, workspace_num, warnings)
    if sdd_repo is not None:
        repos.append(sdd_repo)
    return repos


def _primary_workspace_dir(project_file: str, cwd: str, workspace_num: int) -> str:
    """Return the primary checkout dir (WORKSPACE_DIR is the source of truth)."""
    from sase.workspace_provider.utils import parse_workspace_dir

    primary = parse_workspace_dir(project_file)
    if primary:
        return os.path.expanduser(primary)
    # No WORKSPACE_DIR recorded: derive from the current checkout.
    from sase.sdd import get_primary_workspace_dir

    return get_primary_workspace_dir(cwd, workspace_num)


def _resolve_linked_repos(
    project_file: str, primary_dir: str, warnings: list[str]
) -> list[LogRepo]:
    from sase.linked_repos import resolve_linked_repos_for_project

    try:
        resolution = resolve_linked_repos_for_project(
            project_file=project_file,
            workspace_dir=primary_dir,
            workspace_num=0,
            materialize=False,
        )
    except Exception as exc:  # pragma: no cover - defensive
        warnings.append(f"linked repos could not be resolved: {exc}")
        return []

    for warning in resolution.warnings:
        warnings.append(f"linked repos: {warning}")

    repos: list[LogRepo] = []
    for repo in resolution.repos:
        # Prefer the linked repo's primary checkout; it is the stable,
        # always-materialized copy (numbered workspaces are ephemeral).
        path = repo.primary_dir or repo.workspace_dir
        if path:
            repos.append(LogRepo(name=repo.name, path=path, kind="linked"))
    return repos


def _resolve_sdd_repo(
    primary_dir: str, workspace_num: int, warnings: list[str]
) -> LogRepo | None:
    from sase.sdd import resolve_sdd_store
    from sase.sdd.store import SDD_STORAGE_SEPARATE_REPO

    try:
        store = resolve_sdd_store(primary_dir, workspace_num)
    except Exception as exc:  # pragma: no cover - defensive
        warnings.append(f"sdd store could not be resolved: {exc}")
        return None

    # Only a separate git repo is a distinct history: in_tree commits already
    # appear in the primary log, and local storage is unversioned.
    if store.storage != SDD_STORAGE_SEPARATE_REPO:
        return None
    if not (store.sdd_dir / ".git").is_dir():
        return None

    return LogRepo(
        name=_sdd_label(primary_dir),
        path=str(store.sdd_dir),
        kind="sdd",
    )


def _sdd_label(primary_dir: str) -> str:
    from sase.sdd import read_sdd_store_record

    try:
        record = read_sdd_store_record(Path(primary_dir))
    except Exception:  # pragma: no cover - defensive
        record = None
    if record is not None and record.repo:
        return record.repo
    return "sdd"


def _resolve_fallback_repos(cwd: str, warnings: list[str]) -> list[LogRepo]:
    """Not in a project: log just the current repo, if it is a VCS repo."""
    from sase.vcs_provider import get_vcs_provider

    try:
        get_vcs_provider(cwd)
    except Exception:
        warnings.append(f"{cwd} is not a recognized SASE workspace or VCS repository")
        return []

    name = os.path.basename(os.path.abspath(cwd.rstrip("/"))) or "current"
    return [LogRepo(name=name, path=cwd, kind="primary")]


def _apply_filters(
    repos: list[LogRepo], filters: list[str], warnings: list[str]
) -> list[LogRepo]:
    filter_set = set(filters)
    matched: list[LogRepo] = []
    used: set[str] = set()
    for repo in repos:
        names = {repo.name}
        if repo.kind == "sdd":
            names.add("sdd")
        hit = names & filter_set
        if hit:
            matched.append(repo)
            used |= hit
    for name in filters:
        if name not in used:
            warnings.append(f"--repo {name!r} did not match any repository")
    return matched


__all__ = ["ResolvedRepos", "resolve_log_repos"]
