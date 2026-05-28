"""Provider-neutral commit finalization for SASE-launched agents."""

from __future__ import annotations

import os
from pathlib import Path

from sase.commit_instructions import build_commit_details

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
from .commit_finalizer_git import auto_commit_done_sdd_plan_status, git_changed_files
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
from .types import InvokeResult, ModelTier

_DirtyRepoKind = finalizer_types._DirtyRepoKind
_FinalizerStatus = finalizer_types._FinalizerStatus
_WorkspaceStrategy = finalizer_types._WorkspaceStrategy

_CommitFinalizerConfig = CommitFinalizerConfig
_CommitFinalizerError = CommitFinalizerError
_CommitFinalizerResult = CommitFinalizerResult
_DirtyRepo = DirtyRepo
_DirtyState = DirtyState
_SiblingTarget = SiblingTarget

_changed_files_from_git_status = finalizer_git._changed_files_from_git_status
_git_changed_files = git_changed_files
_normalize_path = finalizer_git._normalize_path

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
_sibling_workspace_strategy = finalizer_state._sibling_workspace_strategy
_workspace_num_for_project_file = finalizer_state._workspace_num_for_project_file
_workspace_num_from_env = finalizer_state._workspace_num_from_env

__all__ = [
    "CommitFinalizerConfig",
    "CommitFinalizerError",
    "CommitFinalizerResult",
    "DirtyRepo",
    "_DirtyRepoKind",
    "DirtyState",
    "_FinalizerStatus",
    "SiblingTarget",
    "_WorkspaceStrategy",
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
    "_result_advisory_changed_files",
    "_result_changed_files",
    "_sibling_commit_instruction",
    "_sibling_targets_from_config",
    "_sibling_targets_from_env",
    "_sibling_workspace_strategy",
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
) -> InvokeResult:
    """Run bounded commit finalization after a successful provider turn."""
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
    dirty_state = _collect_dirty_state(project_dir, artifact_root=artifact_root)
    dirty_state, auto_committed = _auto_commit_done_plan_status_if_possible(
        project_dir,
        dirty_state,
        artifact_root,
    )
    if dirty_state.is_clean:
        _write_result(
            artifact_root,
            _CommitFinalizerResult(
                status="finalized" if auto_committed else "clean",
                reason=(
                    "auto_committed_done_plan_status"
                    if auto_committed
                    else "no_changes"
                ),
                project_dir=project_dir,
                passes=0,
                changed_files=[],
            ),
        )
        return invoke_result

    saw_advisory_repos = bool(dirty_state.advisory_repos)
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
            f"commit_finalizer_pass_{pass_number}_prompt.md",
            follow_up_prompt,
        )

        follow_up = provider.invoke(
            follow_up_prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
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

        dirty_state = _collect_dirty_state(project_dir, artifact_root=artifact_root)
        dirty_state, auto_committed = _auto_commit_done_plan_status_if_possible(
            project_dir,
            dirty_state,
            artifact_root,
        )
        saw_advisory_repos = saw_advisory_repos or bool(dirty_state.advisory_repos)
        if not dirty_state.repos:
            if dirty_state.advisory_repos:
                reason = "advisory_dirty_remaining"
            elif saw_advisory_repos:
                reason = "advisory_clean_after_pass"
            elif auto_committed:
                reason = "auto_committed_done_plan_status"
            else:
                reason = "clean_after_pass"
            _write_result(
                artifact_root,
                _CommitFinalizerResult(
                    status="finalized",
                    reason=reason,
                    project_dir=project_dir,
                    passes=pass_number,
                    changed_files=[],
                    advisory_changed_files=(
                        _result_advisory_changed_files(dirty_state)
                        if saw_advisory_repos
                        else None
                    ),
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
            advisory_changed_files=(
                _result_advisory_changed_files(dirty_state)
                if saw_advisory_repos
                else None
            ),
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


def _result_advisory_changed_files(dirty_state: DirtyState) -> list[str]:
    changed: list[str] = []
    for repo in dirty_state.advisory_repos:
        changed.extend(f"{repo.name}:{path}" for path in repo.changed_files)
    return changed
