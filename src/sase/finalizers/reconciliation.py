"""Machine-owned commit reconciliation helpers for ``builtin@commit``.

These used to live on the deprecated ``run_commit_finalizer`` orchestrator.
The generic controller still needs auto-commit, bead publication, and
clean-result classification, so they sit behind this built-in-finalizer API.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

from sase.llm_provider.commit_finalizer_git import (
    auto_commit_done_sdd_plan_status,
    auto_commit_sdd_prompt_qa_candidate,
    normalize_path,
    sdd_prompt_qa_auto_commit_candidates,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import BeadStateSyncOutcome, DirtyState

_logger = logging.getLogger(__name__)

_WORKSPACE_NUM_ENV_VARS: tuple[str, ...] = (
    "SASE_AGENT_WORKSPACE_NUM",
    "SASE_GIT_WORKSPACE_NUM",
)


@dataclass(frozen=True)
class PreparedCommitDirtyState:
    """Dirty-state snapshot after machine-owned auto-commits."""

    dirty_state: DirtyState
    done_plan_auto_committed: bool = False
    sdd_prompt_qa_auto_committed: bool = False
    sdd_store_auto_committed: bool = False
    bead_publication_error: str | None = None


def prepare_commit_dirty_state(
    project_dir: str,
    artifacts: Path | None,
) -> PreparedCommitDirtyState:
    """Auto-commit machine-owned SDD/bead work, then rescan remaining dirt."""

    bead_sync = auto_commit_separate_sdd_store_if_possible(project_dir, artifacts)
    dirty_state = collect_dirty_state(project_dir, artifact_root=artifacts)
    dirty_state, qa_auto_committed = auto_commit_external_sdd_prompt_qa_if_possible(
        project_dir,
        dirty_state,
        artifacts,
    )
    dirty_state, done_auto_committed = auto_commit_done_plan_status_if_possible(
        project_dir,
        dirty_state,
        artifacts,
    )
    return PreparedCommitDirtyState(
        dirty_state=dirty_state,
        done_plan_auto_committed=done_auto_committed,
        sdd_prompt_qa_auto_committed=qa_auto_committed,
        sdd_store_auto_committed=bead_sync.committed,
        bead_publication_error=bead_sync.publication_error,
    )


def auto_commit_done_plan_status_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    """Commit an SDD plan whose only remaining edit is a done-status flip."""

    if not dirty_state.repos:
        return dirty_state, False
    if not auto_commit_done_sdd_plan_status(dirty_state):
        return dirty_state, False
    refreshed = collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, True


def auto_commit_external_sdd_prompt_qa_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    """Best-effort safety net for proven Q&A-only external prompt edits."""

    candidates = sdd_prompt_qa_auto_commit_candidates(dirty_state)
    if not candidates:
        return dirty_state, False

    committed_any = False
    for candidate in candidates:
        try:
            committed_any = (
                auto_commit_sdd_prompt_qa_candidate(candidate) or committed_any
            )
        except Exception:
            _logger.warning(
                "Failed to auto-commit agents-sidecar prompt Q&A in %s",
                candidate.repo_dir,
                exc_info=True,
            )

    if not committed_any:
        return dirty_state, False
    refreshed = collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, True


def auto_commit_separate_sdd_store_if_possible(
    project_dir: str, artifacts_dir: Path | None = None
) -> BeadStateSyncOutcome:
    """Commit and publish machine-managed external bead state.

    Committing is not enough on its own: the configured push policy may be
    queued, detached, or aimed at a different checkout than the one holding the
    commit, so a finalizer-created bead commit is verified as published and the
    failure is reported rather than left to die with the workspace.
    """

    beads_root = _auto_commit_bead_state(project_dir, artifacts_dir)
    if beads_root is None:
        return BeadStateSyncOutcome()
    return BeadStateSyncOutcome(
        committed=True,
        publication_error=_unpublished_bead_state_error(beads_root),
    )


def clean_result_reason(
    *,
    done_plan_auto_committed: bool,
    sdd_prompt_qa_auto_committed: bool,
    sdd_store_auto_committed: bool,
) -> str:
    """Classify a clean commit outcome after machine-owned auto-commits."""

    auto_committed: list[str] = []
    if done_plan_auto_committed:
        auto_committed.append("done_plan_status")
    if sdd_prompt_qa_auto_committed:
        auto_committed.append("sdd_prompt_qa")
    if sdd_store_auto_committed:
        auto_committed.append("sdd_store")
    if not auto_committed:
        return "no_changes"
    return "auto_committed_" + "_and_".join(auto_committed)


def _auto_commit_bead_state(
    project_dir: str, artifacts_dir: Path | None
) -> Path | None:
    """Best-effort commit of leftover bead state; returns the store committed."""

    try:
        if not _separate_sdd_store_repo_may_exist(project_dir):
            return None

        from sase.sdd.files import commit_sdd_store_files
        from sase.sdd.store import (
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
            resolve_sdd_store,
        )

        workspace_num = _finalizer_workspace_num(project_dir)
        store = resolve_sdd_store(project_dir, workspace_num)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
        }:
            return None
        repo_roots = (
            [store.repo_root_for_kind(role) for role in store.split_sidecar_roles()]
            if store.is_sidecar_storage
            else [store.repo_root]
        )
        if not any((root / ".git").exists() for root in repo_roots):
            return None
        beads_root = store.kind_root("beads")
        from sase.bead.sync import bead_state_is_clean

        if bead_state_is_clean(beads_root):
            return None
        committed = commit_sdd_store_files(
            store,
            "chore(beads): sync bead state",
            auto_commit_type="beads",
            paths=[beads_root],
            artifacts_dir=artifacts_dir,
        )
        return beads_root if committed else None
    except Exception:
        _logger.warning(
            "Failed to auto-commit separate SDD store during finalization",
            exc_info=True,
        )
        return None


def _unpublished_bead_state_error(beads_root: Path) -> str | None:
    """Publish the finalizer's bead commit; report it when it stayed local."""

    from sase.bead.cli_common import (
        BeadPublicationError,
        ensure_bead_mutation_published,
    )

    try:
        ensure_bead_mutation_published(
            beads_root,
            description="finalizer bead-state sync commit",
        )
    except BeadPublicationError as exc:
        return exc.diagnostic
    except Exception:
        _logger.warning(
            "Failed to verify publication of the finalizer bead-state commit",
            exc_info=True,
        )
    return None


def _separate_sdd_store_repo_may_exist(project_dir: str) -> bool:
    """Return whether a legacy or split external SDD clone is present."""

    project_path = Path(project_dir).expanduser()
    primary_candidates = [project_path]

    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(project_path))
    except Exception:
        found = None
    if found is not None and found[1].primary_workspace_dir:
        primary_candidates.append(Path(found[1].primary_workspace_dir))

    workspace_num = _workspace_num_from_env()
    if workspace_num is not None and workspace_num > 1:
        suffix_primary = _suffix_stripped_primary_workspace(project_path, workspace_num)
        if suffix_primary is not None:
            primary_candidates.append(suffix_primary)

    if any(
        (candidate / ".sase" / "sdd" / ".git").exists()
        for candidate in primary_candidates
    ):
        return True

    try:
        from sase.linked_repos import sidecar_repo_clone_dir
        from sase.sdd.store import read_sdd_store_record

        for primary in primary_candidates:
            record = read_sdd_store_record(primary)
            if record is None or not record.is_sidecar_storage:
                continue
            for kind in record.sidecars:
                clone = Path(sidecar_repo_clone_dir(project_path, kind))
                if (clone / ".git").exists():
                    return True
    except Exception:
        return False
    return False


def _suffix_stripped_primary_workspace(
    project_path: Path,
    workspace_num: int,
) -> Path | None:
    suffix = f"_{workspace_num}"
    parts = list(project_path.parts)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].endswith(suffix):
            parts[index] = parts[index][: -len(suffix)]
            return Path(*parts)
    return None


def _finalizer_workspace_num(project_dir: str) -> int:
    project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    if project_file:
        workspace_num = _workspace_num_for_project_file(project_file, project_dir)
        if workspace_num is not None:
            return workspace_num

    workspace_num = _workspace_num_from_env()
    if workspace_num is not None:
        return workspace_num
    return 1


def _workspace_num_for_project_file(project_file: str, project_dir: str) -> int | None:
    env_num = _workspace_num_from_env()
    if env_num is not None:
        return env_num

    try:
        from sase.workspace_provider.utils import parse_workspace_dir

        primary_dir = parse_workspace_dir(project_file)
    except Exception:
        return None

    if not primary_dir:
        return None

    primary_path = Path(normalize_path(primary_dir))
    project_path = Path(normalize_path(project_dir))
    if project_path == primary_path:
        return 0
    if project_path.parent != primary_path.parent:
        return None

    prefix = f"{primary_path.name}_"
    if not project_path.name.startswith(prefix):
        return None
    suffix = project_path.name[len(prefix) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _workspace_num_from_env() -> int | None:
    for key in _WORKSPACE_NUM_ENV_VARS:
        raw = os.environ.get(key)
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            continue
    return None


__all__ = [
    "PreparedCommitDirtyState",
    "auto_commit_done_plan_status_if_possible",
    "auto_commit_external_sdd_prompt_qa_if_possible",
    "auto_commit_separate_sdd_store_if_possible",
    "clean_result_reason",
    "prepare_commit_dirty_state",
]
