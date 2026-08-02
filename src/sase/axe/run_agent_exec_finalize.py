"""Final outcome assembly for the agent execution loop.

Chat persistence and artifact processing live in focused sibling modules. Private
helper imports remain available here for compatibility with existing callers.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from sase.axe.run_agent_exec_finalize_artifacts import (
    collect_default_artifacts as _collect_default_artifacts,
    commit_records_from_step_output as _commit_records,
    enforce_artifact_retention as _enforce_artifact_retention,
    normalized_path as _normalized_path,
    render_markdown_pdfs as _render_markdown_pdfs,
    sdd_repo_scans as _sdd_repo_scans,
)
from sase.axe.run_agent_exec_finalize_chat import (
    final_done_agent_name as _final_done_agent_name,
    final_execution_provider as _final_execution_provider,
    final_transcript_model_provider as _final_transcript_model_provider,
    link_saved_chats as _link_saved_chats,
    load_prompt_renderings as _load_prompt_renderings,
    metadata_str as _metadata_str,
    read_plan_path as _read_plan_path,
    read_retry_handoff_meta as _read_retry_handoff_meta,
    read_transcript_agent_meta as _read_transcript_agent_meta,
    rewrite_xprompt_links as _link_xprompt_prompt,
)
from sase.axe.run_agent_exec_markers import write_done_marker_and_update_index
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_exec_types import AgentExecContext, AgentExecResult, LoopState
from sase.axe.run_agent_helpers import extract_step_output_and_diff_path
from sase.axe.run_agent_helpers import is_workflow_noop
from sase.axe.run_agent_phases import build_done_marker
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.retry_config import RetryState

_ORIGINAL_EXTRACT_STEP_OUTPUT_AND_DIFF_PATH = extract_step_output_and_diff_path
_ORIGINAL_FORMAT_EXTRA_SECTIONS = format_extra_sections
_ORIGINAL_IS_WORKFLOW_NOOP = is_workflow_noop
_ORIGINAL_SAVE_CHAT_HISTORY = save_chat_history


def _compat_attr(name: str, current: Any, original: Any) -> Any:
    """Honor legacy patches applied to ``sase.axe.run_agent_exec``."""
    if current is not original:
        return current
    exec_mod = sys.modules.get("sase.axe.run_agent_exec")
    return getattr(exec_mod, name, current) if exec_mod is not None else current


def _extract_step_output_and_diff_path(artifacts_dir: str) -> Any:
    func = _compat_attr(
        "extract_step_output_and_diff_path",
        extract_step_output_and_diff_path,
        _ORIGINAL_EXTRACT_STEP_OUTPUT_AND_DIFF_PATH,
    )
    return func(artifacts_dir)


def _format_extra_sections(artifacts_dir: str) -> str:
    func = _compat_attr(
        "format_extra_sections",
        format_extra_sections,
        _ORIGINAL_FORMAT_EXTRA_SECTIONS,
    )
    return func(artifacts_dir)


def _is_workflow_noop(artifacts_dir: str) -> bool:
    func = _compat_attr(
        "is_workflow_noop",
        is_workflow_noop,
        _ORIGINAL_IS_WORKFLOW_NOOP,
    )
    return func(artifacts_dir)


def _save_chat_history(**kwargs: Any) -> str:
    func = _compat_attr(
        "save_chat_history",
        save_chat_history,
        _ORIGINAL_SAVE_CHAT_HISTORY,
    )
    return func(**kwargs)


def _prompt_renderings(
    ctx: AgentExecContext,
    state: LoopState,
) -> tuple[str | None, str | None]:
    """Load prompts while preserving the legacy link-helper patch point."""
    return _load_prompt_renderings(
        ctx,
        state,
        link_xprompt_prompt=_link_xprompt_prompt,
    )


def _build_retry_metadata(tracker: RetryTracker) -> dict[str, Any] | None:
    if tracker.retry_count <= 0 and not tracker.using_fallback:
        return None
    retry_meta: dict[str, Any] = {
        "retry_count": tracker.retry_count,
        "retry_errors": tracker.retry_errors,
        "used_fallback": tracker.using_fallback,
    }
    if tracker.using_fallback and tracker.retry_cfg:
        retry_meta["fallback_model"] = tracker.retry_cfg.fallback_model
    return retry_meta


def _restore_execution_env(state: LoopState) -> None:
    os.environ.pop("SASE_ARTIFACTS_DIR", None)
    os.environ.pop("SASE_PLAN", None)
    os.environ.pop("SASE_AGENT_ROOT_TIMESTAMP", None)
    if state.original_agent_timestamp is None:
        os.environ.pop("SASE_AGENT_TIMESTAMP", None)
    else:
        os.environ["SASE_AGENT_TIMESTAMP"] = state.original_agent_timestamp


def finalize_loop(
    ctx: AgentExecContext,
    state: LoopState,
    tracker: RetryTracker,
    result: Any,
) -> AgentExecResult:
    """Post-loop cleanup: retry state, done marker, result construction."""
    RetryState.delete_from(ctx.artifacts_dir)
    fallback_model_override = os.environ.get("SASE_MODEL_OVERRIDE")
    if "SASE_MODEL_OVERRIDE" in os.environ:
        del os.environ["SASE_MODEL_OVERRIDE"]

    retry_meta = _build_retry_metadata(tracker)
    _restore_execution_env(state)
    done_agent_name = _final_done_agent_name(ctx, state)
    metadata_model, metadata_llm_provider = _final_transcript_model_provider(
        ctx,
        state,
        tracker,
        fallback_model_override,
    )
    execution_llm_provider = _final_execution_provider(state)

    saved_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = []
    markdown_source_count = 0
    image_paths: list[str] = []
    video_paths: list[str] = []
    step_output: dict[str, Any] | None = None

    if state.loop_outcome == "completed" and result is not None:
        response_content = getattr(result, "response_text", "") or ""
    else:
        response_content = ""

    extra = _format_extra_sections(state.current_artifacts_dir)
    xprompt_prompt, rendered_prompt = _prompt_renderings(ctx, state)
    saved_path = _save_chat_history(
        prompt=state.current_prompt,
        response=response_content,
        workflow="ace-run",
        agent=done_agent_name,
        timestamp=ctx.timestamp,
        extra_sections=extra,
        branch_or_workspace=ctx.cl_name,
        metadata_agent=done_agent_name,
        metadata_model=metadata_model,
        metadata_llm_provider=metadata_llm_provider,
        metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
        xprompt_prompt=xprompt_prompt,
        rendered_prompt=rendered_prompt,
    )
    print(f"\nChat history saved to: {saved_path}")

    if state.loop_outcome == "completed":
        _link_saved_chats(state, saved_path)
        plan_path = _read_plan_path(state.current_artifacts_dir)
        step_output, diff_path = _extract_step_output_and_diff_path(
            state.current_artifacts_dir
        )
        (
            markdown_pdf_paths,
            markdown_source_count,
            image_paths,
            video_paths,
            default_artifacts_persisted,
        ) = _collect_default_artifacts(ctx, state, saved_path, diff_path, step_output)
        _enforce_artifact_retention()

        completed_outcome = (
            "noop" if _is_workflow_noop(state.current_artifacts_dir) else "completed"
        )
        done_marker = build_done_marker(
            ctx.cl_name,
            ctx.project_file,
            ctx.timestamp,
            ctx.artifacts_timestamp,
            ctx.workspace_num,
            ctx.workspace_dir,
            ctx.output_path,
            completed_outcome,
            agent_name=done_agent_name,
            agent_model=ctx.agent_model,
            agent_llm_provider=ctx.agent_llm_provider,
            agent_exec_llm_provider=execution_llm_provider,
            agent_vcs_provider=ctx.agent_vcs_provider,
            agent_hidden=ctx.agent_hidden,
            response_path=saved_path,
            step_output=step_output,
            diff_path=diff_path,
            plan_path=plan_path,
            markdown_pdf_paths=markdown_pdf_paths,
            image_paths=image_paths,
            video_paths=video_paths,
            retry_metadata=retry_meta,
            default_artifacts_persisted=default_artifacts_persisted,
        )
        done_path = write_done_marker_and_update_index(
            state.current_artifacts_dir,
            done_marker,
        )
        print(f"Done marker written to: {done_path}")
    else:
        retried_as_timestamp: str | None = None
        retry_chain_root_timestamp: str | None = None
        retry_error_category: str | None = None
        if state.loop_outcome == "failed_retried":
            actual_outcome = "failed"
            (
                retried_as_timestamp,
                retry_chain_root_timestamp,
                retry_error_category,
            ) = _read_retry_handoff_meta(ctx)
        else:
            actual_outcome = state.loop_outcome

        done_marker = build_done_marker(
            ctx.cl_name,
            ctx.project_file,
            ctx.timestamp,
            ctx.artifacts_timestamp,
            ctx.workspace_num,
            ctx.workspace_dir,
            ctx.output_path,
            actual_outcome,
            agent_name=done_agent_name,
            agent_model=ctx.agent_model,
            agent_llm_provider=ctx.agent_llm_provider,
            agent_exec_llm_provider=execution_llm_provider,
            agent_vcs_provider=ctx.agent_vcs_provider,
            agent_hidden=ctx.agent_hidden,
            response_path=saved_path,
            retry_metadata=retry_meta,
            retried_as_timestamp=retried_as_timestamp,
            retry_chain_root_timestamp=retry_chain_root_timestamp,
            retry_error_category=retry_error_category,
        )
        done_path = write_done_marker_and_update_index(
            state.current_artifacts_dir,
            done_marker,
        )
        print(f"Done marker written to: {done_path} (outcome: {state.loop_outcome})")

    if state.current_artifacts_dir != ctx.artifacts_dir:
        write_done_marker_and_update_index(ctx.artifacts_dir, done_marker)

    return AgentExecResult(
        success=state.loop_outcome in {"completed", "epic_approved"},
        outcome=state.loop_outcome,
        saved_path=saved_path,
        diff_path=diff_path,
        markdown_pdf_paths=markdown_pdf_paths,
        markdown_source_count=markdown_source_count,
        image_paths=image_paths,
        video_paths=video_paths,
        current_artifacts_dir=state.current_artifacts_dir,
        step_output=step_output,
    )


_finalize_loop = finalize_loop
