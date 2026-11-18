"""Per-source dirty-repository discovery for commit finalization."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import os
from pathlib import Path

from sase.linked_repos import HIDDEN_SIDECAR_ROLES

from .. import commit_finalizer_git as finalizer_git
from ..commit_finalizer_git import (
    git_changed_files,
    has_only_prompt_qa_diff,
    is_prompt_archive_path,
)
from ..commit_finalizer_git_status import git_status_records
from ..commit_finalizer_types import DirtyRepo, SiblingTarget
from ._repository_candidates import (
    known_sdd_sidecar_paths,
    sibling_candidates as _shared_sibling_candidates,
)
from ._workspace_num import workspace_num_for_project_file, workspace_num_from_env

_logger = logging.getLogger(__name__)


def dirty_opened_external_repos(
    records: Mapping[str, Mapping[str, str]],
    *,
    known_sdd_paths: Mapping[str, str] | None = None,
) -> list[DirtyRepo]:
    """Return dirty external repositories recorded in this agent run."""

    dirty: list[DirtyRepo] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()
    for name, record in records.items():
        canonical_name = (record.get("ref") or name).strip()
        workspace_dir = record.get("workspace_dir", "").strip()
        if not canonical_name or not workspace_dir:
            continue
        workspace_dir = finalizer_git.normalize_path(workspace_dir)
        if known_sdd_paths is not None and workspace_dir in known_sdd_paths:
            continue
        if canonical_name in seen_names or workspace_dir in seen_paths:
            continue
        changed_files = git_changed_files(workspace_dir)
        if not changed_files:
            continue
        dirty.append(
            DirtyRepo(
                name=canonical_name,
                path=workspace_dir,
                changed_files=tuple(changed_files),
                kind="external",
            )
        )
        seen_names.add(canonical_name)
        seen_paths.add(workspace_dir)
    return dirty


def dirty_sdd_store_repos(project_dir: str) -> list[DirtyRepo]:
    """Return dirty external SDD repositories owned by this workspace."""

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

        dirty: list[DirtyRepo] = []
        targets = sdd_commit_targets(store, None)
        for target_store, _paths in targets:
            if target_store.sidecar_role in HIDDEN_SIDECAR_ROLES:
                continue
            repo_root = target_store.repo_root.expanduser()
            if not (repo_root / ".git").exists():
                continue
            changed_files = git_changed_files(str(repo_root))
            if not changed_files:
                continue
            dirty.append(
                DirtyRepo(
                    name=(
                        sdd_store_label(target_store)
                        or target_store.sidecar_role
                        or "sdd"
                    ),
                    path=finalizer_git.normalize_path(str(repo_root)),
                    changed_files=tuple(changed_files),
                    kind="sdd",
                )
            )
        return dirty
    except Exception:
        return []


def dirty_agents_prompt_archive_repo(project_dir: str) -> list[DirtyRepo]:
    """Return a dirty agents sidecar only for proven Q&A prompt edits.

    The agents prompt archive is machine-wide, host-owned state: a run's own
    question-gate Q&A snapshot (written by ``followup.py`` into the canonical
    prompt file) is the only edit a run intentionally leaves there for the
    finalizer's Q&A auto-commit to pick up. Everything else in this checkout —
    untracked prompt files, ``prompts/<YYYYMM>/README.md`` index edits,
    non-Q&A modifications, anything under ``artifacts/`` or
    ``files/objects/`` — is agents-sync publication scratch: written only
    under the agents-sync lock, always regenerable from the local artifact
    pool, and durably queued in the publication outbox before any attempt.
    Claiming it as this run's dirty work would misattribute a concurrent
    agent's publication (see the ``prompt_archive_finalizer_contention``
    tale).
    """

    try:
        from sase.agents_sync.commit_publication import resolve_publication_project_key
        from sase.agents_sync.targets import resolve_sync_targets

        selector = resolve_publication_project_key(Path(project_dir))
        selection = resolve_sync_targets((selector,)) if selector else None
        if selection is None or len(selection.targets) != 1:
            return []
        agents_root = selection.targets[0].sidecar_path.expanduser()
        if not (agents_root / ".git").exists():
            return []
        repo_dir = str(agents_root)
        status_records = git_status_records(repo_dir)
        if not status_records:
            return []

        qa_paths: list[str] = []
        foreign_paths: list[str] = []
        for record in status_records:
            if (
                record.xy == " M"
                and is_prompt_archive_path(record.path)
                and has_only_prompt_qa_diff(repo_dir, record.path)
            ):
                qa_paths.append(record.path)
            else:
                foreign_paths.append(record.path)

        if foreign_paths:
            _logger.debug(
                "agents-sync publication scratch left for the publisher: "
                "repo=%s paths=%s",
                repo_dir,
                foreign_paths,
            )
        if not qa_paths:
            return []
        return [
            DirtyRepo(
                name="agents prompt archive",
                path=finalizer_git.normalize_path(repo_dir),
                changed_files=tuple(qa_paths),
                kind="sdd",
            )
        ]
    except Exception:
        return []


def dirty_configured_sibling_repos(
    sibling_targets: list[SiblingTarget],
    *,
    opened_workspace_dirs: Mapping[str, str] | None = None,
    opened_names: set[str] | None = None,
    known_sdd_paths: Mapping[str, str] | None = None,
) -> list[DirtyRepo]:
    if opened_workspace_dirs is None:
        opened_workspace_dirs = dict.fromkeys(sorted(opened_names or set()), "")

    targets_by_name = {target.name: target for target in sibling_targets}
    dirty: list[DirtyRepo] = []
    seen_names: set[str] = set()
    seen_paths: set[str] = set()

    for name, workspace_dir in _blocking_sibling_candidates(
        sibling_targets,
        opened_workspace_dirs=opened_workspace_dirs,
        targets_by_name=targets_by_name,
    ):
        if known_sdd_paths is not None and workspace_dir in known_sdd_paths:
            continue
        if name in seen_names or workspace_dir in seen_paths:
            continue
        changed_files = git_changed_files(workspace_dir)
        if not changed_files:
            continue

        dirty.append(
            DirtyRepo(
                name=name,
                path=workspace_dir,
                changed_files=tuple(changed_files),
                kind="sibling",
            )
        )
        seen_names.add(name)
        seen_paths.add(workspace_dir)
    return dirty


def _blocking_sibling_candidates(
    sibling_targets: list[SiblingTarget],
    *,
    opened_workspace_dirs: Mapping[str, str],
    targets_by_name: Mapping[str, SiblingTarget],
) -> list[tuple[str, str]]:
    """Delegate to the shared enumeration used by the guard."""

    return _shared_sibling_candidates(
        sibling_targets,
        dict(opened_workspace_dirs),
        dict(targets_by_name),
    )
