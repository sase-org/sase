"""Best-effort SDD auto-commit safety nets for ``builtin@commit``."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.llm_provider.commit_finalizer_git import (
    auto_commit_done_sdd_plan_status,
    auto_commit_sdd_bead_reprojection_candidate,
    auto_commit_sdd_prompt_qa_candidate,
    sdd_bead_reprojection_auto_commit_candidates,
    sdd_prompt_qa_auto_commit_candidates,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import DirtyState

_logger = logging.getLogger(__name__)


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


def auto_commit_sdd_bead_reprojection_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    """Best-effort safety net for proven beads ``issues.jsonl`` reprojections."""

    candidates = sdd_bead_reprojection_auto_commit_candidates(dirty_state)
    if not candidates:
        return dirty_state, False

    committed_any = False
    for candidate in candidates:
        try:
            committed_any = (
                auto_commit_sdd_bead_reprojection_candidate(
                    candidate,
                    artifacts_dir=artifact_root,
                )
                or committed_any
            )
        except Exception:
            _logger.warning(
                "Failed to auto-commit beads-sidecar issues.jsonl reprojection in %s",
                candidate.repo_dir,
                exc_info=True,
            )

    if not committed_any:
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
