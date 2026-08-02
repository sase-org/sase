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


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _prompt_renderings(
    ctx: AgentExecContext,
    state: LoopState,
) -> tuple[str | None, str | None]:
    """Load the panel's XPrompt and rendered prompt for chat persistence."""

    current_dir = Path(state.current_artifacts_dir or ctx.artifacts_dir)
    fallback_dir = Path(ctx.artifacts_dir)
    candidates = (
        (current_dir,)
        if current_dir == fallback_dir
        else (
            current_dir,
            fallback_dir,
        )
    )

    xprompt_prompt: str | None = None
    xprompt_dir = current_dir
    for directory in candidates:
        content = _read_text(directory / "raw_xprompt.md")
        if content is not None:
            xprompt_prompt = content
            xprompt_dir = directory
            break

    from sase.agent.artifact_files_cache import ArtifactFileCache

    cache = ArtifactFileCache()
    rendered_prompt: str | None = None
    for directory in candidates:
        selected = cache.select_prompt_file(
            str(directory),
            is_workflow_child=False,
            step_name=None,
        )
        if selected is not None:
            rendered_prompt = cache.read_text(selected)
            break

    if xprompt_prompt is not None:
        xprompt_prompt = _link_xprompt_prompt(
            xprompt_prompt,
            artifacts_dir=xprompt_dir,
            workspace_dir=Path(ctx.workspace_dir),
            project_name=ctx.project_name,
        )
    return xprompt_prompt, rendered_prompt


def _link_xprompt_prompt(
    prompt: str,
    *,
    artifacts_dir: Path,
    workspace_dir: Path,
    project_name: str,
) -> str:
    """Best-effort hosted link rewriting for one stored XPrompt prompt."""

    try:
        from sase.agents_sync.git import run_git
        from sase.agents_sync.prompt_archive.preparation import repository_roots
        from sase.sdd.hosted_links import HostedLinkResolver
        from sase.sdd.plan_refs import workspace_context_for_plan_resolution
        from sase.sdd.store import resolve_sdd_store
        from sase.xprompt_links import (
            XpromptTargetResolver,
            load_xprompt_source_records,
            rewrite_xprompt_source_links,
        )

        records = load_xprompt_source_records(artifacts_dir)
        if not records:
            return prompt
        primary_root, workspace_num = workspace_context_for_plan_resolution(
            workspace_dir
        )
        revision_result = run_git(
            primary_root,
            ["rev-parse", "HEAD"],
            op="chat_history.xprompt_revision",
        )
        primary_revision = revision_result.stdout.strip()
        if revision_result.returncode != 0 or not primary_revision:
            return prompt
        store = resolve_sdd_store(primary_root, workspace_num)
        hosted = HostedLinkResolver(
            store,
            project=project_name,
            primary_root=primary_root,
            git_runner=run_git,
        )
        resolver = XpromptTargetResolver(
            primary_root=primary_root,
            primary_revision=primary_revision,
            hosted=hosted,
            git_runner=run_git,
            repository_roots=repository_roots(),
        )
        return rewrite_xprompt_source_links(prompt, records, resolver)
    except Exception:
        return prompt


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
        DiffScan,
        collect_agent_image_paths,
        collect_agent_markdown_paths,
        collect_agent_video_paths,
        same_git_repo,
    )

    workspace_dir = getattr(ctx, "workspace_dir", os.getcwd())
    commit_records = _commit_records(step_output)
    if step_output and step_output.get("meta_pr_url"):
        include_head_commit = True
    elif commit_records:
        include_head_commit = any(
            same_git_repo(cwd, workspace_dir)
            for record in commit_records
            if (cwd := _metadata_str(record, "cwd")) is not None
        )
    elif step_output and (commit_cwd := _metadata_str(step_output, "meta_commit_cwd")):
        include_head_commit = same_git_repo(commit_cwd, workspace_dir)
    else:
        include_head_commit = bool(step_output and step_output.get("meta_new_commit"))

    diff_scans: list[DiffScan] = []
    seen_diff_paths: set[str] = set()
    for record in commit_records:
        record_diff_path = _metadata_str(record, "diff_path")
        if record_diff_path is None:
            continue
        normalized_diff_path = _normalized_path(record_diff_path)
        if normalized_diff_path in seen_diff_paths:
            continue
        seen_diff_paths.add(normalized_diff_path)
        diff_scans.append(DiffScan(record_diff_path, _metadata_str(record, "cwd")))
    if diff_path and _normalized_path(diff_path) not in seen_diff_paths:
        diff_scans.append(DiffScan(diff_path, workspace_dir))

    base_files = [path for path in [saved_path, diff_path] if path]
    extra_repo_scans = _sdd_repo_scans(ctx)
    markdown_paths = collect_agent_markdown_paths(
        workspace_dir,
        diff_scans=diff_scans,
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
        diff_scans=diff_scans,
        include_head_commit=include_head_commit,
        existing_files=[*base_files, *markdown_pdf_paths],
        extra_repo_scans=extra_repo_scans,
    )
    video_paths = collect_agent_video_paths(
        workspace_dir,
        diff_scans=diff_scans,
        include_head_commit=include_head_commit,
        existing_files=[*base_files, *markdown_pdf_paths, *image_paths],
        extra_repo_scans=extra_repo_scans,
    )

    try:
        from sase.core.artifact_file_facade import persist_default_artifact_files

        persist_default_artifact_files(
            state.current_artifacts_dir,
            image_paths=image_paths,
            video_paths=video_paths,
            workspace_dir=workspace_dir,
            project=ctx.project_name,
            workspace_num=ctx.workspace_num,
            print_summary=True,
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


def _enforce_artifact_retention() -> None:
    try:
        from datetime import UTC, datetime, timedelta

        from sase.config import (
            get_artifact_retention_enabled,
            get_artifact_retention_keep_per_label,
            get_artifact_retention_max_age_days,
            get_artifact_retention_trash_grace_days,
        )
        from sase.core.artifact_file_explicit import read_artifact_file_index
        from sase.core.artifact_file_protection import collect_protected_artifact_ids
        from sase.core.artifact_file_retention import (
            RetentionPolicy,
            plan_artifact_file_retention,
        )
        from sase.core.artifact_file_trash import (
            purge_trashed_artifact_files,
            trash_artifact_files,
        )

        if not get_artifact_retention_enabled():
            return

        now = datetime.now(UTC)
        protections = collect_protected_artifact_ids()
        if protections.sources_unavailable:
            sources = ", ".join(protections.sources_unavailable)
            print(
                "[artifacts] retention skipped: "
                f"protection sources unavailable: {sources}"
            )
            return

        max_age_days = get_artifact_retention_max_age_days()
        policy = RetentionPolicy(
            now=now.isoformat(),
            keep_per_label=get_artifact_retention_keep_per_label(),
            before=None if max_age_days == 0 else f"{max_age_days}d",
            protected_ids=protections.ids,
        )
        plan = plan_artifact_file_retention(policy)
        rows_by_id = {row.id: row for row in read_artifact_file_index()}
        selected_rows = []
        missing_rows = 0
        for item in plan.selected:
            row = rows_by_id.get(item.id)
            if row is None:
                missing_rows += 1
            else:
                selected_rows.append(row)
        trashed = trash_artifact_files(
            selected_rows,
            reason="retention",
            now=policy.now,
        )
        purge_cutoff = (
            now - timedelta(days=get_artifact_retention_trash_grace_days())
        ).isoformat()
        purged = purge_trashed_artifact_files(before=purge_cutoff)
        missing_note = (
            f", skipped {missing_rows} disappeared rows" if missing_rows else ""
        )
        print(
            "[artifacts] retention: "
            f"trashed {trashed.rows_trashed} rows, "
            f"reclaimed {trashed.bytes_reclaimed} bytes, "
            f"purged {len(purged.purged_entry_ids)} trash entries"
            f"{missing_note}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[artifacts] retention failed: {exc}")


def _commit_records(step_output: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not step_output:
        return []
    records = step_output.get("meta_commits")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def _normalized_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def _sdd_repo_scans(ctx: AgentExecContext) -> list[Any]:
    try:
        from sase.axe.image_attachments import ExtraRepoScan
        from sase.sdd.files import is_sdd_internal_path
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
            exclude=is_sdd_internal_path,
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


def _final_execution_provider(state: LoopState) -> str | None:
    latest_meta = _read_transcript_agent_meta(state.current_artifacts_dir)
    return _metadata_str(latest_meta, "exec_llm_provider")


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
