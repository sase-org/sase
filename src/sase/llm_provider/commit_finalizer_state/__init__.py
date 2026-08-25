"""Dirty repository discovery for commit finalization."""

from __future__ import annotations

from pathlib import Path

from sase.commit_instructions import build_commit_details
from sase.linked_repos import (
    opened_external_repo_records,
    opened_linked_repo_names,
    opened_linked_repo_workspace_dirs,
)

from .. import commit_finalizer_git as finalizer_git
from ..commit_finalizer_baseline import DirtyBaseline, load_dirty_baseline
from ..commit_finalizer_git import (
    filter_sase_reserved_paths,
    split_pre_existing_changed_files,
)
from ..commit_finalizer_prompting import build_dirty_details, build_pre_existing_details
from ..commit_finalizer_types import DIRTY_REPO_KIND_PRIORITY, DirtyRepo, DirtyState
from ._baseline_repos import collect_baseline_repositories
from ._dirty_repos import (
    dirty_agents_prompt_archive_repo as _dirty_agents_prompt_archive_repo,
    dirty_configured_sibling_repos as _dirty_configured_sibling_repos,
    dirty_opened_external_repos as _dirty_opened_external_repos,
    dirty_sdd_store_repos as _dirty_sdd_store_repos,
)
from ._sibling_targets import configured_sibling_targets as _configured_sibling_targets

__all__ = [
    "collect_baseline_repositories",
    "collect_dirty_state",
]


def _dedupe_dirty_repos_by_path(repos: list[DirtyRepo]) -> list[DirtyRepo]:
    """Collapse ``repos`` sharing a normalized path into a single entry.

    The winning entry keeps the most specific ``kind`` (see
    ``DIRTY_REPO_KIND_PRIORITY``) and the union of both entries'
    ``changed_files``, in first-seen order.
    """
    order: list[str] = []
    by_path: dict[str, DirtyRepo] = {}
    for repo in repos:
        key = finalizer_git.normalize_path(repo.path)
        existing = by_path.get(key)
        if existing is None:
            order.append(key)
            by_path[key] = repo
            continue
        merged_files = tuple(
            dict.fromkeys((*existing.changed_files, *repo.changed_files))
        )
        winner = (
            repo
            if DIRTY_REPO_KIND_PRIORITY[repo.kind]
            < DIRTY_REPO_KIND_PRIORITY[existing.kind]
            else existing
        )
        by_path[key] = DirtyRepo(
            name=winner.name,
            path=winner.path,
            changed_files=merged_files,
            kind=winner.kind,
        )
    return [by_path[key] for key in order]


def collect_dirty_state(
    project_dir: str,
    *,
    artifact_root: Path | None = None,
) -> DirtyState:
    has_main_changes, main_files, main_instruction, main_details = (
        _build_commit_details(project_dir)
    )

    main_repo = (
        DirtyRepo(
            name="main",
            path=finalizer_git.normalize_path(project_dir),
            changed_files=tuple(main_files),
            kind="main",
        )
        if has_main_changes
        else None
    )
    sibling_targets = _configured_sibling_targets(project_dir)
    opened_names = opened_linked_repo_names(artifact_root)
    opened_workspace_dirs = opened_linked_repo_workspace_dirs(artifact_root)
    if opened_names:
        opened_workspace_dirs = {
            **dict.fromkeys(sorted(opened_names), ""),
            **opened_workspace_dirs,
        }
    sibling_repos = tuple(
        _dirty_configured_sibling_repos(
            sibling_targets,
            opened_workspace_dirs=opened_workspace_dirs,
        )
    )
    external_repos = tuple(
        _dirty_opened_external_repos(opened_external_repo_records(artifact_root))
    )
    sdd_repos = (
        *_dirty_sdd_store_repos(project_dir),
        *_dirty_agents_prompt_archive_repo(project_dir),
    )
    repos: list[DirtyRepo] = []
    if main_repo is not None:
        repos.append(main_repo)
    repos.extend(sibling_repos)
    repos.extend(external_repos)
    repos.extend(sdd_repos)
    repos = _dedupe_dirty_repos_by_path(repos)

    repos, pre_existing_repos = _exclude_pre_existing_baseline(
        repos, load_dirty_baseline(artifact_root)
    )
    main_repo = next((repo for repo in repos if repo.kind == "main"), None)
    if main_repo is None:
        main_details = ""
    elif main_repo.changed_files != tuple(main_files):
        main_details = _render_main_details(
            list(main_repo.changed_files), main_instruction
        )
    sibling_repos = tuple(repo for repo in repos if repo.kind == "sibling")
    external_repos = tuple(repo for repo in repos if repo.kind == "external")
    sdd_repos = tuple(repo for repo in repos if repo.kind == "sdd")

    details = build_dirty_details(
        main_details=main_details,
        main_instruction=main_instruction,
        main_repo=main_repo,
        sibling_repos=sibling_repos,
        external_repos=external_repos,
        sdd_repos=sdd_repos,
    )
    details = build_pre_existing_details(details, pre_existing_repos)
    return DirtyState(
        project_dir=finalizer_git.normalize_path(project_dir),
        repos=tuple(repos),
        details=details,
    )


def _exclude_pre_existing_baseline(
    repos: list[DirtyRepo],
    baseline: DirtyBaseline | None,
) -> tuple[list[DirtyRepo], tuple[DirtyRepo, ...]]:
    """Split *repos* into (still relevant, unchanged-since-baseline).

    Only paths whose git status and content hash are provably unchanged
    since the baseline are excluded; a baseline-dirty path this run edited
    again keeps its current fingerprint and so stays in the must-commit set.
    """
    if not baseline:
        return repos, ()

    still: list[DirtyRepo] = []
    pre_existing: list[DirtyRepo] = []
    for repo in repos:
        baseline_fingerprints = baseline.get(finalizer_git.normalize_path(repo.path))
        still_files, pre_existing_files = split_pre_existing_changed_files(
            repo.path, list(repo.changed_files), baseline_fingerprints
        )
        if still_files:
            still.append(
                repo
                if still_files == list(repo.changed_files)
                else DirtyRepo(
                    name=repo.name,
                    path=repo.path,
                    changed_files=tuple(still_files),
                    kind=repo.kind,
                )
            )
        if pre_existing_files:
            pre_existing.append(
                DirtyRepo(
                    name=repo.name,
                    path=repo.path,
                    changed_files=tuple(pre_existing_files),
                    kind=repo.kind,
                )
            )
    return still, tuple(pre_existing)


def _render_main_details(changed_files: list[str], instruction: str) -> str:
    details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
    if instruction:
        details += f"\n\n{instruction}"
    return details


def _build_commit_details(project_dir: str) -> tuple[bool, list[str], str, str]:
    has_changes, changed_files, instruction, details = build_commit_details(project_dir)
    if not has_changes:
        return (False, [], "", "")

    filtered = filter_sase_reserved_paths(changed_files)
    if not filtered:
        return (False, [], "", "")
    if filtered == changed_files:
        return (has_changes, changed_files, instruction, details)

    return (True, filtered, instruction, _render_main_details(filtered, instruction))
