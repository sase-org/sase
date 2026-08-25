"""Runner-start baseline repository checkout discovery."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sase.linked_repos import HIDDEN_SIDECAR_ROLES

from .. import commit_finalizer_git as finalizer_git
from ..commit_finalizer_types import DIRTY_REPO_KIND_PRIORITY, BaselineRepo
from ._sibling_targets import configured_sibling_targets
from ._workspace_num import workspace_num_for_project_file, workspace_num_from_env

_logger = logging.getLogger(__name__)

_BASELINE_CHECKOUT_SCAN_LIMIT = 128
_BASELINE_CHECKOUT_SCAN_MAX_DEPTH = 5


def collect_baseline_repositories(project_dir: str) -> tuple[BaselineRepo, ...]:
    """Return every repository checkout visible at runner-start baseline time."""

    repos: list[BaselineRepo] = []
    main = _baseline_main_repo(project_dir)
    if main is not None:
        repos.append(main)
    repos.extend(_baseline_configured_sibling_repos(project_dir))
    repos.extend(_baseline_sdd_store_repos(project_dir))
    repos.extend(_baseline_agents_prompt_archive_repo(project_dir))
    repos.extend(_baseline_workspace_repo_checkouts(project_dir))
    return tuple(_dedupe_baseline_repos_by_path(repos))


def _baseline_main_repo(project_dir: str) -> BaselineRepo | None:
    path = Path(project_dir).expanduser()
    if not _has_git_entry(path):
        return None
    return BaselineRepo(
        name="main",
        path=finalizer_git.normalize_path(str(path)),
        kind="main",
    )


def _baseline_configured_sibling_repos(project_dir: str) -> list[BaselineRepo]:
    repos: list[BaselineRepo] = []
    for target in configured_sibling_targets(project_dir):
        path = Path(target.workspace_dir).expanduser()
        if not _has_git_entry(path):
            continue
        repos.append(
            BaselineRepo(
                name=target.name,
                path=finalizer_git.normalize_path(str(path)),
                kind="sibling",
            )
        )
    return repos


def _baseline_sdd_store_repos(project_dir: str) -> list[BaselineRepo]:
    """Return existing SDD repository checkouts, including clean ones."""

    try:
        from sase.sdd._commit_store import sdd_commit_targets, sdd_store_label
        from sase.sdd.store import (
            SDD_STORAGE_SIDECAR_REPOS,
            SDD_STORAGE_SEPARATE_REPO,
            resolve_sdd_store,
        )

        project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
        workspace_num = None
        if project_file:
            workspace_num = workspace_num_for_project_file(project_file, project_dir)
        if workspace_num is None:
            workspace_num = workspace_num_from_env()
        store = resolve_sdd_store(project_dir, workspace_num or 1)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
        }:
            return []

        repos: list[BaselineRepo] = []
        for target_store, _paths in sdd_commit_targets(store, None):
            if target_store.sidecar_role in HIDDEN_SIDECAR_ROLES:
                continue
            repo_root = target_store.repo_root.expanduser()
            if not _has_git_entry(repo_root):
                continue
            repos.append(
                BaselineRepo(
                    name=(
                        sdd_store_label(target_store)
                        or target_store.sidecar_role
                        or "sdd"
                    ),
                    path=finalizer_git.normalize_path(str(repo_root)),
                    kind="sdd",
                )
            )
        return repos
    except Exception:
        return []


def _baseline_agents_prompt_archive_repo(project_dir: str) -> list[BaselineRepo]:
    """Return the agents prompt-archive sidecar checkout, if one is present."""

    try:
        from sase.agents_sync.commit_publication import resolve_publication_project_key
        from sase.agents_sync.targets import resolve_sync_targets

        selector = resolve_publication_project_key(Path(project_dir))
        selection = resolve_sync_targets((selector,)) if selector else None
        if selection is None or len(selection.targets) != 1:
            return []
        agents_root = selection.targets[0].sidecar_path.expanduser()
        if not _has_git_entry(agents_root):
            return []
        return [
            BaselineRepo(
                name="agents prompt archive",
                path=finalizer_git.normalize_path(str(agents_root)),
                kind="sdd",
            )
        ]
    except Exception:
        return []


def _baseline_workspace_repo_checkouts(project_dir: str) -> list[BaselineRepo]:
    """Return pre-existing checkouts below ``sase/repos``."""

    repos_root = Path(project_dir).expanduser() / "sase" / "repos"
    if not repos_root.is_dir():
        return []

    repos: list[BaselineRepo] = []
    for repo_root in _iter_workspace_repo_checkouts(repos_root):
        repos.append(
            BaselineRepo(
                name=_workspace_checkout_name(repos_root, repo_root),
                path=finalizer_git.normalize_path(str(repo_root)),
                kind="external",
            )
        )
    return repos


def _iter_workspace_repo_checkouts(repos_root: Path) -> list[Path]:
    checkouts: list[Path] = []
    try:
        for current, dirnames, filenames in os.walk(repos_root):
            current_path = Path(current)
            if ".git" in dirnames or ".git" in filenames:
                checkouts.append(current_path)
                dirnames[:] = []
                if len(checkouts) >= _BASELINE_CHECKOUT_SCAN_LIMIT:
                    _logger.warning(
                        "Commit finalizer baseline checkout scan reached the %d "
                        "checkout limit under %s; skipped remaining directories "
                        "after %s",
                        _BASELINE_CHECKOUT_SCAN_LIMIT,
                        repos_root,
                        current_path,
                    )
                    break
                continue

            if _relative_depth(current_path, repos_root) >= (
                _BASELINE_CHECKOUT_SCAN_MAX_DEPTH
            ):
                dirnames[:] = []
            else:
                dirnames[:] = sorted(name for name in dirnames if name != ".git")
    except OSError:
        return checkouts
    return checkouts


def _workspace_checkout_name(repos_root: Path, repo_root: Path) -> str:
    try:
        return repo_root.relative_to(repos_root).as_posix()
    except ValueError:
        return repo_root.name


def _relative_depth(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return _BASELINE_CHECKOUT_SCAN_MAX_DEPTH


def _has_git_entry(path: Path) -> bool:
    return (path / ".git").exists()


def _dedupe_baseline_repos_by_path(repos: list[BaselineRepo]) -> list[BaselineRepo]:
    order: list[str] = []
    by_path: dict[str, BaselineRepo] = {}
    for repo in repos:
        key = finalizer_git.normalize_path(repo.path)
        existing = by_path.get(key)
        if existing is None:
            order.append(key)
            by_path[key] = repo
            continue
        if (
            DIRTY_REPO_KIND_PRIORITY[repo.kind]
            < DIRTY_REPO_KIND_PRIORITY[existing.kind]
        ):
            by_path[key] = repo
    return [by_path[key] for key in order]
