"""Finalization and artifact collection for the agent execution loop."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

from sase.axe.run_agent_exec_markers import (
    clear_workflow_pdf_activity,
    short_pdf_source,
    update_workflow_pdf_status,
    write_done_marker_and_update_index,
)
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_exec_types import AgentExecContext, AgentExecResult, LoopState
from sase.axe.run_agent_helpers import extract_step_output_and_diff_path
from sase.axe.run_agent_helpers import is_workflow_noop
from sase.axe.run_agent_phases import build_done_marker
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.retry_config import RetryState
from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    canonical_plan_chain_suffix,
    plan_chain_agent_name,
)

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


def _final_done_agent_name(ctx: AgentExecContext, state: LoopState) -> str | None:
    if state.agent_step <= 1 or not ctx.agent_name:
        return ctx.agent_name
    plan_chain_suffix = canonical_plan_chain_suffix(state.current_role_suffix)
    if plan_chain_suffix is not None:
        return plan_chain_agent_name(ctx.agent_name, plan_chain_suffix)
    return f"{ctx.agent_name}.{state.agent_step}"


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


def _link_saved_chats(state: LoopState, saved_path: str) -> None:
    state.saved_chat_paths.append(
        (state.current_role_suffix or PLAN_CHAIN_CODER_SUFFIX, saved_path)
    )
    if len(state.saved_chat_paths) <= 1:
        return
    from sase.history.chat_links import append_links_to_chat, build_linked_chats_section

    for role, path in state.saved_chat_paths:
        links_section = build_linked_chats_section(
            state.saved_chat_paths, current_role=role
        )
        append_links_to_chat(os.path.expanduser(path), links_section)


def _read_plan_path(artifacts_dir: str) -> str | None:
    plan_path_file = os.path.join(artifacts_dir, "plan_path.json")
    try:
        with open(plan_path_file, encoding="utf-8") as f:
            return json.load(f).get("plan_path")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _render_markdown_pdfs(
    ctx: AgentExecContext,
    state: LoopState,
    markdown_paths: list[str],
) -> list[str]:
    from sase.attachments.markdown_pdf import (
        MAX_MARKDOWN_PDF_ATTACHMENTS,
        MarkdownPdfProgressEvent,
        render_markdown_pdf_attachments,
    )

    workspace_dir = getattr(ctx, "workspace_dir", os.getcwd())
    markdown_source_count = len(markdown_paths)
    print(
        "Preparing PDFs from Markdown... "
        f"found {markdown_source_count}, cap {MAX_MARKDOWN_PDF_ATTACHMENTS}"
    )

    def _handle_pdf_progress(event: MarkdownPdfProgressEvent) -> None:
        source = short_pdf_source(event.source_path, workspace_dir)
        pdf_status = {
            "stage": event.stage,
            "source_path": source or event.source_path,
            "pdf_path": event.pdf_path,
            "engine": event.engine,
            "index": event.index,
            "total": event.total,
            "generated": event.generated,
            "skipped": event.skipped,
            "reason": event.reason,
            "cap": MAX_MARKDOWN_PDF_ATTACHMENTS,
            "active": event.stage != "completed",
        }
        pdf_status = {k: v for k, v in pdf_status.items() if v is not None}
        if event.stage == "started":
            print(
                "[PDF] preparing Markdown PDFs "
                f"({event.total or 0} source(s), "
                f"cap {MAX_MARKDOWN_PDF_ATTACHMENTS})"
            )
        elif event.stage == "source_started":
            print(f"[PDF] {event.index}/{event.total} {source}")
        elif event.stage == "engine_started":
            print(f"[PDF] {event.index}/{event.total} trying {event.engine}: {source}")
        elif event.stage == "source_succeeded":
            print(f"[PDF] {event.index}/{event.total} done: {source}")
        elif event.stage == "source_failed":
            print(
                f"[PDF] {event.index}/{event.total} failed: {source} ({event.reason})"
            )
        elif event.stage == "skipped":
            print(
                f"[PDF] {event.index}/{event.total} skipped: {source} ({event.reason})"
            )
        elif event.stage == "completed":
            print(
                "[PDF] complete: "
                f"{event.generated or 0} generated, {event.skipped or 0} skipped"
            )
        update_workflow_pdf_status(state.current_artifacts_dir, pdf_status)

    if markdown_source_count <= MAX_MARKDOWN_PDF_ATTACHMENTS:
        return render_markdown_pdf_attachments(
            markdown_paths,
            workspace_dir=workspace_dir,
            artifacts_dir=state.current_artifacts_dir,
            progress=_handle_pdf_progress,
        )

    reason = (
        f"over attachment limit ({markdown_source_count} > "
        f"{MAX_MARKDOWN_PDF_ATTACHMENTS})"
    )
    print(f"[PDF] skipped Markdown PDF rendering: {reason}")
    update_workflow_pdf_status(
        state.current_artifacts_dir,
        {
            "stage": "completed",
            "total": markdown_source_count,
            "generated": 0,
            "skipped": markdown_source_count,
            "reason": reason,
            "cap": MAX_MARKDOWN_PDF_ATTACHMENTS,
            "active": False,
        },
    )
    return []


def _collect_default_artifacts(
    ctx: AgentExecContext,
    state: LoopState,
    saved_path: str | None,
    diff_path: str | None,
    step_output: dict[str, Any] | None,
) -> tuple[list[str], int, list[str], list[str], bool]:
    from sase.axe.image_attachments import (
        collect_agent_image_paths,
        collect_agent_markdown_paths,
        collect_agent_video_paths,
    )

    include_head_commit = bool(
        step_output
        and any(step_output.get(key) for key in ("meta_new_commit", "meta_pr_url"))
    )
    workspace_dir = getattr(ctx, "workspace_dir", os.getcwd())
    base_files = [path for path in [saved_path, diff_path] if path]
    extra_repo_scans = _sdd_repo_scans(ctx)
    markdown_paths = collect_agent_markdown_paths(
        workspace_dir,
        diff_path=diff_path,
        include_head_commit=include_head_commit,
        existing_files=base_files,
        artifacts_dir=state.current_artifacts_dir,
        extra_repo_scans=extra_repo_scans,
    )
    markdown_source_count = len(markdown_paths)
    markdown_pdf_paths = _render_markdown_pdfs(ctx, state, markdown_paths)
    clear_workflow_pdf_activity(state.current_artifacts_dir)
    image_paths = collect_agent_image_paths(
        workspace_dir,
        diff_path=diff_path,
        include_head_commit=include_head_commit,
        existing_files=[*base_files, *markdown_pdf_paths],
        extra_repo_scans=extra_repo_scans,
    )
    video_paths = collect_agent_video_paths(
        workspace_dir,
        diff_path=diff_path,
        include_head_commit=include_head_commit,
        existing_files=[*base_files, *markdown_pdf_paths, *image_paths],
        extra_repo_scans=extra_repo_scans,
    )

    try:
        from sase.core.agent_artifact_facade import persist_default_agent_artifacts

        persist_default_agent_artifacts(
            state.current_artifacts_dir,
            image_paths=image_paths,
            video_paths=video_paths,
            workspace_dir=workspace_dir,
        )
        default_artifacts_persisted = True
    except Exception as exc:  # noqa: BLE001
        print(f"[artifacts] failed to persist default artifacts: {exc}")
        default_artifacts_persisted = False

    return (
        markdown_pdf_paths,
        markdown_source_count,
        image_paths,
        video_paths,
        default_artifacts_persisted,
    )


def _sdd_repo_scans(ctx: AgentExecContext) -> list[Any]:
    try:
        from sase.axe.image_attachments import ExtraRepoScan
        from sase.sdd.store import SDD_STORAGE_SEPARATE_REPO, resolve_sdd_store

        store = resolve_sdd_store(ctx.workspace_dir, ctx.workspace_num)
    except Exception:
        return []

    if store.is_in_tree:
        return []
    repo_root = Path(store.repo_root).expanduser()
    if not (repo_root / ".git").exists():
        return []

    base_sha = _metadata_str(ctx.agent_meta, "sdd_base_sha")
    if base_sha is None:
        base_sha = _metadata_str(
            _read_transcript_agent_meta(ctx.artifacts_dir),
            "sdd_base_sha",
        )
    agent_name = ctx.agent_name
    if agent_name is None:
        agent_name = _metadata_str(
            _read_transcript_agent_meta(ctx.artifacts_dir),
            "name",
        )
    # A separate-repo store is an isolated per-workspace clone. Its working
    # tree should normally be clean because the commit finalizer sweeps the
    # agent's SDD writes first, but a crashed prior run can rarely leave files
    # that git alone cannot attribute. Shared local stores are never scanned
    # for working-tree files because concurrent agents write to the same tree.
    include_working_tree = store.storage == SDD_STORAGE_SEPARATE_REPO
    return [
        ExtraRepoScan(
            str(repo_root),
            base_sha,
            agent_name=agent_name,
            include_working_tree=include_working_tree,
        )
    ]


def _read_retry_handoff_meta(
    ctx: AgentExecContext,
) -> tuple[str | None, str | None, str | None]:
    try:
        meta_path = os.path.join(ctx.artifacts_dir, "agent_meta.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, None, None
    if not isinstance(meta, dict):
        return None, None, None
    return (
        meta.get("retried_as_timestamp"),
        meta.get("retry_chain_root_timestamp"),
        meta.get("retry_error_category"),
    )


def _read_transcript_agent_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _metadata_str(meta: dict[str, Any], key: str) -> str | None:
    value = meta.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _final_transcript_model_provider(
    ctx: AgentExecContext,
    state: LoopState,
    tracker: RetryTracker,
    fallback_model_override: str | None,
) -> tuple[str | None, str | None]:
    latest_meta = _read_transcript_agent_meta(state.current_artifacts_dir)
    model = _metadata_str(latest_meta, "model") or ctx.agent_model
    llm_provider = _metadata_str(latest_meta, "llm_provider") or ctx.agent_llm_provider

    fallback_model = fallback_model_override
    if fallback_model is None and tracker.using_fallback and tracker.retry_cfg:
        fallback_model = tracker.retry_cfg.fallback_model
    if fallback_model:
        try:
            from sase.llm_provider.registry import resolve_model_provider

            resolved_provider, resolved_model = resolve_model_provider(fallback_model)
        except Exception:
            resolved_provider, resolved_model = None, fallback_model
        model = resolved_model
        if resolved_provider:
            llm_provider = resolved_provider

    return model, llm_provider


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

    saved_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = []
    markdown_source_count = 0
    image_paths: list[str] = []
    video_paths: list[str] = []
    step_output: dict[str, Any] | None = None

    if state.loop_outcome == "completed":
        assert result is not None
        response_content = result.response_text or ""
    else:
        response_content = ""

    extra = _format_extra_sections(state.current_artifacts_dir)
    saved_path = _save_chat_history(
        prompt=state.current_prompt,
        response=response_content,
        workflow="ace-run",
        timestamp=ctx.timestamp,
        extra_sections=extra,
        branch_or_workspace=ctx.cl_name,
        metadata_agent=done_agent_name,
        metadata_model=metadata_model,
        metadata_llm_provider=metadata_llm_provider,
        metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
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
        success=state.loop_outcome == "completed",
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
