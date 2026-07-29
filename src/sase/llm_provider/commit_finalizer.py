"""Provider-neutral commit finalization for SASE-launched agents."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sase.commit_instructions import build_commit_details
from sase.core.commit_finalizer_prompt_artifacts import (
    commit_finalizer_pass_prompt_filename,
)

from . import commit_finalizer_artifacts as finalizer_artifacts
from . import commit_finalizer_config as finalizer_config
from . import commit_finalizer_git as finalizer_git
from . import commit_finalizer_prompting as finalizer_prompting
from . import commit_finalizer_state as finalizer_state
from . import commit_finalizer_types as finalizer_types
from .commit_finalizer_artifacts import artifact_root, write_result, write_text
from .commit_finalizer_config import (
    load_finalizer_config,
    resolve_finalizer_project_dir,
)
from .commit_finalizer_git import (
    auto_commit_done_sdd_plan_status,
    git_changed_files,
    sdd_prompt_qa_auto_commit_candidates,
)
from .commit_finalizer_prompting import (
    append_response,
    build_dirty_details,
    build_follow_up_prompt,
    failure_message,
    merge_usage,
)
from .commit_finalizer_state import collect_dirty_state
from .commit_finalizer_types import (
    CommitFinalizerConfig,
    CommitFinalizerError,
    CommitFinalizerResult,
    DirtyRepo,
    DirtyState,
    SiblingTarget,
)
from .base import LLMProvider
from .types import InvokeResult, LLMInvocationOptions, ModelTier

_DirtyRepoKind = finalizer_types._DirtyRepoKind
_FinalizerStatus = finalizer_types._FinalizerStatus

_CommitFinalizerConfig = CommitFinalizerConfig
_CommitFinalizerError = CommitFinalizerError
_CommitFinalizerResult = CommitFinalizerResult
_DirtyRepo = DirtyRepo
_DirtyState = DirtyState
_SiblingTarget = SiblingTarget

_changed_files_from_git_status = finalizer_git._changed_files_from_git_status
_git_changed_files = git_changed_files
_normalize_path = finalizer_git.normalize_path

_append_response = append_response
_build_dirty_details = build_dirty_details
_build_follow_up_prompt = build_follow_up_prompt
_failure_message = failure_message
_merge_usage = merge_usage
_result_changed_files = finalizer_prompting._result_changed_files
_sibling_commit_instruction = finalizer_prompting._sibling_commit_instruction

_artifact_root = artifact_root
_write_result = write_result
_write_text = write_text

_normalize_max_passes = finalizer_config._normalize_max_passes
_workspace_env_value = finalizer_config._workspace_env_value
_load_finalizer_config = load_finalizer_config
_resolve_finalizer_project_dir = resolve_finalizer_project_dir

_collect_dirty_state = collect_dirty_state
_configured_sibling_targets = finalizer_state._configured_sibling_targets
_dirty_configured_sibling_repos = finalizer_state._dirty_configured_sibling_repos
_sibling_targets_from_config = finalizer_state._sibling_targets_from_config
_sibling_targets_from_env = finalizer_state._sibling_targets_from_env
_workspace_num_for_project_file = finalizer_state._workspace_num_for_project_file
_workspace_num_from_env = finalizer_state._workspace_num_from_env

_logger = logging.getLogger(__name__)

__all__ = [
    "CommitFinalizerConfig",
    "CommitFinalizerError",
    "CommitFinalizerResult",
    "DirtyRepo",
    "_DirtyRepoKind",
    "DirtyState",
    "_FinalizerStatus",
    "SiblingTarget",
    "append_response",
    "artifact_root",
    "build_dirty_details",
    "build_follow_up_prompt",
    "_changed_files_from_git_status",
    "collect_dirty_state",
    "_configured_sibling_targets",
    "_dirty_configured_sibling_repos",
    "failure_message",
    "git_changed_files",
    "load_finalizer_config",
    "merge_usage",
    "_normalize_max_passes",
    "_normalize_path",
    "resolve_finalizer_project_dir",
    "_result_changed_files",
    "_sibling_commit_instruction",
    "_sibling_targets_from_config",
    "_sibling_targets_from_env",
    "_workspace_env_value",
    "_workspace_num_for_project_file",
    "_workspace_num_from_env",
    "write_result",
    "write_text",
    "build_commit_details",
    "run_commit_finalizer",
]


def run_commit_finalizer(
    *,
    provider: LLMProvider,
    original_prompt: str,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None = None,
    options: LLMInvocationOptions | None = None,
) -> InvokeResult:
    """Run bounded commit finalization after a successful provider turn.

    ``options`` carries the same resolved per-invocation options (e.g.
    reasoning effort) used for the original turn, so commit/fix follow-ups run
    at the same effort instead of falling back to the provider default.
    """
    config = _load_finalizer_config()
    artifact_root = _artifact_root(artifacts_dir)

    if os.environ.get("SASE_DISABLE_COMMIT_STOP_HOOK"):
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="skipped",
                reason="disabled_by_env",
                project_dir=None,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    if not config.enabled:
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="skipped",
                reason="disabled_by_config",
                project_dir=None,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    if not os.environ.get("SASE_AGENT_TIMESTAMP"):
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="skipped",
                reason="outside_sase_agent",
                project_dir=None,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    project_dir = _resolve_finalizer_project_dir()
    sdd_store_auto_committed = _auto_commit_separate_sdd_store_if_possible(
        project_dir, artifact_root
    )
    dirty_state = _collect_dirty_state(project_dir, artifact_root=artifact_root)
    dirty_state, sdd_prompt_qa_auto_committed = (
        _auto_commit_external_sdd_prompt_qa_if_possible(
            project_dir,
            dirty_state,
            artifact_root,
        )
    )
    dirty_state, done_plan_auto_committed = _auto_commit_done_plan_status_if_possible(
        project_dir,
        dirty_state,
        artifact_root,
    )
    if dirty_state.is_clean:
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status=(
                    "finalized"
                    if done_plan_auto_committed
                    or sdd_prompt_qa_auto_committed
                    or sdd_store_auto_committed
                    else "clean"
                ),
                reason=_clean_result_reason(
                    done_plan_auto_committed=done_plan_auto_committed,
                    sdd_prompt_qa_auto_committed=sdd_prompt_qa_auto_committed,
                    sdd_store_auto_committed=sdd_store_auto_committed,
                ),
                project_dir=project_dir,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    accumulated_content = invoke_result.content
    accumulated_usage = invoke_result.usage

    for pass_number in range(1, config.max_passes + 1):
        follow_up_prompt = _build_follow_up_prompt(
            original_prompt=original_prompt,
            accumulated_response=accumulated_content,
            details=dirty_state.details,
            pass_number=pass_number,
            max_passes=config.max_passes,
        )
        _write_text(
            artifact_root,
            commit_finalizer_pass_prompt_filename(pass_number),
            follow_up_prompt,
        )

        follow_up = provider.invoke(
            follow_up_prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
        )
        _write_text(
            artifact_root,
            f"commit_finalizer_pass_{pass_number}_response.md",
            follow_up.content,
        )

        accumulated_content = _append_response(
            accumulated_content,
            follow_up.content,
        )
        accumulated_usage = _merge_usage(accumulated_usage, follow_up.usage)

        sdd_store_auto_committed = (
            _auto_commit_separate_sdd_store_if_possible(project_dir, artifact_root)
            or sdd_store_auto_committed
        )
        dirty_state = _collect_dirty_state(project_dir, artifact_root=artifact_root)
        dirty_state, qa_auto_committed = (
            _auto_commit_external_sdd_prompt_qa_if_possible(
                project_dir,
                dirty_state,
                artifact_root,
            )
        )
        sdd_prompt_qa_auto_committed = qa_auto_committed or sdd_prompt_qa_auto_committed
        dirty_state, done_auto_committed = _auto_commit_done_plan_status_if_possible(
            project_dir,
            dirty_state,
            artifact_root,
        )
        done_plan_auto_committed = done_auto_committed or done_plan_auto_committed
        if not dirty_state.repos:
            reason = (
                _clean_result_reason(
                    done_plan_auto_committed=done_plan_auto_committed,
                    sdd_prompt_qa_auto_committed=sdd_prompt_qa_auto_committed,
                    sdd_store_auto_committed=sdd_store_auto_committed,
                )
                if done_plan_auto_committed
                or sdd_prompt_qa_auto_committed
                or sdd_store_auto_committed
                else "clean_after_pass"
            )
            _write_result(
                artifact_root,
                _CommitFinalizerResult(
                    status="finalized",
                    reason=reason,
                    project_dir=project_dir,
                    passes=pass_number,
                    changed_files=[],
                ),
            )
            return InvokeResult(content=accumulated_content, usage=accumulated_usage)

    error = _failure_message(dirty_state, config.max_passes)
    _write_result(
        artifact_root,
        _CommitFinalizerResult(
            status="failed",
            reason="dirty_after_max_passes",
            project_dir=project_dir,
            passes=config.max_passes,
            changed_files=_result_changed_files(dirty_state),
            error=error,
        ),
    )
    raise _CommitFinalizerError(error)


def _auto_commit_done_plan_status_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    if not dirty_state.repos:
        return dirty_state, False
    if not auto_commit_done_sdd_plan_status(dirty_state):
        return dirty_state, False
    refreshed = _collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, True


def _auto_commit_external_sdd_prompt_qa_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool]:
    """Best-effort safety net for proven Q&A-only external prompt edits."""
    candidates = sdd_prompt_qa_auto_commit_candidates(dirty_state)
    if not candidates:
        return dirty_state, False

    try:
        from sase.sdd.files import commit_sdd_store_files
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(project_dir, _finalizer_workspace_num(project_dir))
    except Exception:
        _logger.warning(
            "Failed to resolve external SDD store for Q&A auto-commit",
            exc_info=True,
        )
        return dirty_state, False

    committed_any = False
    for candidate in candidates:
        for relative_path in candidate.paths:
            prompt_path = Path(candidate.repo_dir) / relative_path
            try:
                committed_any = (
                    commit_sdd_store_files(
                        store,
                        f"Add Q&A to {prompt_path.stem} prompt",
                        auto_commit_type="sdd",
                        paths=[prompt_path],
                        artifacts_dir=artifact_root,
                    )
                    or committed_any
                )
            except Exception:
                _logger.warning(
                    "Failed to auto-commit external SDD prompt Q&A: %s",
                    prompt_path,
                    exc_info=True,
                )

    if not committed_any:
        return dirty_state, False
    refreshed = _collect_dirty_state(project_dir, artifact_root=artifact_root)
    return refreshed, True


def _auto_commit_separate_sdd_store_if_possible(
    project_dir: str, artifacts_dir: Path | None = None
) -> bool:
    """Best-effort safety net for machine-managed external bead state."""
    try:
        if not _separate_sdd_store_repo_may_exist(project_dir):
            return False

        from sase.sdd.files import commit_sdd_store_files
        from sase.sdd.store import (
            SDD_STORAGE_SIDECAR_REPOS,
            SDD_STORAGE_SEPARATE_REPO,
            resolve_sdd_store,
        )

        workspace_num = _finalizer_workspace_num(project_dir)
        store = resolve_sdd_store(project_dir, workspace_num)
        if store.storage not in {
            SDD_STORAGE_SEPARATE_REPO,
            SDD_STORAGE_SIDECAR_REPOS,
        }:
            return False
        repo_roots = (
            [store.repo_root_for_kind(role) for role in store.split_sidecar_roles()]
            if store.is_sidecar_storage
            else [store.repo_root]
        )
        if not any((root / ".git").exists() for root in repo_roots):
            return False
        beads_root = store.kind_root("beads")
        from sase.bead.sync import bead_state_is_clean

        if bead_state_is_clean(beads_root):
            return False
        return commit_sdd_store_files(
            store,
            "chore(beads): sync bead state",
            auto_commit_type="beads",
            paths=[beads_root],
            artifacts_dir=artifacts_dir,
        )
    except Exception:
        _logger.warning(
            "Failed to auto-commit separate SDD store during finalization",
            exc_info=True,
        )
        return False


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


def _clean_result_reason(
    *,
    done_plan_auto_committed: bool,
    sdd_prompt_qa_auto_committed: bool,
    sdd_store_auto_committed: bool,
) -> str:
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
