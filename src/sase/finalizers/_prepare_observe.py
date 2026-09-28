"""Repository observation for conditional completion preparation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import subprocess
from typing import Any

from sase.finalizers.commit_validation import protected_baseline_paths
from sase.finalizers.declaration_recovery_evidence import (
    direct_written_paths,
    written_paths_from_tool_calls,
)
from sase.finalizers.declaration_store import repository_obligation_id
from sase.linked_repos import opened_external_repo_records, opened_linked_repo_records
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_git import git_changed_files, normalize_path
from sase.llm_provider.commit_finalizer_git_status import (
    UNKNOWN_HEAD_SENTINEL,
    dirty_path_fingerprints,
    git_head_commit_id,
)
from sase.llm_provider.commit_finalizer_state import (
    collect_baseline_repositories,
    collect_dirty_state,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo

_GIT_TIMEOUT_SECONDS = 5


def observe_completion_repositories(root: Path) -> list[dict[str, Any]]:
    """Observe HEAD, index, and dirty paths for every relevant opened repo."""

    project_dir = resolve_finalizer_project_dir()
    dirty = collect_dirty_state(project_dir, artifact_root=root)
    dirty_by_path = {normalize_path(repo.path): repo for repo in dirty.repos}
    written = written_paths_from_tool_calls(root)
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for repo in _observation_repos(project_dir, root, dirty.repos):
        path = normalize_path(repo.path)
        if path in seen:
            continue
        seen.add(path)
        dirty_repo = dirty_by_path.get(path, repo)
        observations.append(
            _observe_one_repository(
                dirty_repo,
                artifacts=root,
                written_paths=written,
            )
        )
    return observations


def _observation_repos(
    project_dir: str,
    artifacts: Path,
    dirty_repos: Sequence[DirtyRepo],
) -> list[DirtyRepo]:
    repos: list[DirtyRepo] = list(dirty_repos)
    for baseline in collect_baseline_repositories(project_dir):
        repos.append(
            DirtyRepo(
                name=baseline.name,
                path=baseline.path,
                changed_files=(),
                kind=baseline.kind,
            )
        )
    for name, record in opened_linked_repo_records(artifacts).items():
        workspace = record.get("workspace_dir") or record.get("path")
        if not workspace:
            continue
        repos.append(
            DirtyRepo(
                name=name,
                path=workspace,
                changed_files=(),
                kind="sibling",
            )
        )
    for name, record in opened_external_repo_records(artifacts).items():
        workspace = record.get("workspace_dir") or record.get("path")
        if not workspace:
            continue
        repos.append(
            DirtyRepo(
                name=name,
                path=workspace,
                changed_files=(),
                kind="external",
            )
        )
    return repos


def _observe_one_repository(
    repo: DirtyRepo,
    *,
    artifacts: Path,
    written_paths: tuple[str, ...],
) -> dict[str, Any]:
    head = git_head_commit_id(repo.path)
    head_tree = (
        _git_output(repo.path, ["rev-parse", "HEAD^{tree}"]) or UNKNOWN_HEAD_SENTINEL
    )
    index_tree = _git_output(repo.path, ["write-tree"]) or UNKNOWN_HEAD_SENTINEL
    fingerprints = dirty_path_fingerprints(repo.path)
    protected = set(
        protected_baseline_paths(
            artifacts,
            repo.path,
            get_changed_files=git_changed_files,
        )
    )
    run_written = set(
        direct_written_paths(
            repo_path=repo.path,
            written_paths=written_paths,
            named_paths=tuple(fingerprints),
        )
    )
    paths: list[dict[str, Any]] = []
    complete = (
        head not in {"", UNKNOWN_HEAD_SENTINEL}
        and head_tree not in {"", UNKNOWN_HEAD_SENTINEL}
        and index_tree not in {"", UNKNOWN_HEAD_SENTINEL}
    )
    for rel_path, (xy, content_hash) in sorted(fingerprints.items()):
        kind, mode = _path_kind_and_mode(repo.path, rel_path, xy)
        if kind != "deleted" and content_hash is None:
            complete = False
        paths.append(
            {
                "path": rel_path,
                "xy": xy,
                "content_hash": content_hash,
                "mode": mode,
                "kind": kind,
                "protected": rel_path in protected,
                "foreign": rel_path not in run_written and rel_path in protected,
            }
        )
    return {
        "repo_id": repository_obligation_id(repo),
        "kind": repo.kind,
        "name": repo.name,
        "head": head,
        "head_tree": head_tree,
        "index_tree": index_tree,
        "paths": paths,
        "complete": complete,
    }


def _path_kind_and_mode(
    repo_dir: str,
    rel_path: str,
    xy: str,
) -> tuple[str, str | None]:
    if "D" in xy:
        return "deleted", None
    full = Path(repo_dir) / rel_path.split(" -> ", 1)[0]
    try:
        if full.is_symlink():
            return "symlink", f"{full.lstat().st_mode:o}"
        if not full.exists():
            return "deleted", None
        if full.is_file():
            kind = "untracked" if "?" in xy else "file"
            return kind, f"{full.stat().st_mode:o}"
    except OSError:
        return "other", None
    return "other", None


def _git_output(repo_dir: str, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
