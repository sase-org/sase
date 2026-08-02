"""Default artifact collection and retention for agent finalization."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.axe.run_agent_exec_finalize_chat import (
    metadata_str,
    read_transcript_agent_meta,
)
from sase.axe.run_agent_exec_markers import (
    clear_workflow_pdf_activity,
    short_pdf_source,
    update_workflow_pdf_status,
)
from sase.axe.run_agent_exec_types import AgentExecContext, LoopState


def render_markdown_pdfs(
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


def collect_default_artifacts(
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
    commit_records = commit_records_from_step_output(step_output)
    if step_output and step_output.get("meta_pr_url"):
        include_head_commit = True
    elif commit_records:
        include_head_commit = any(
            same_git_repo(cwd, workspace_dir)
            for record in commit_records
            if (cwd := metadata_str(record, "cwd")) is not None
        )
    elif step_output and (commit_cwd := metadata_str(step_output, "meta_commit_cwd")):
        include_head_commit = same_git_repo(commit_cwd, workspace_dir)
    else:
        include_head_commit = bool(step_output and step_output.get("meta_new_commit"))

    diff_scans: list[DiffScan] = []
    seen_diff_paths: set[str] = set()
    for record in commit_records:
        record_diff_path = metadata_str(record, "diff_path")
        if record_diff_path is None:
            continue
        normalized_diff_path = normalized_path(record_diff_path)
        if normalized_diff_path in seen_diff_paths:
            continue
        seen_diff_paths.add(normalized_diff_path)
        diff_scans.append(DiffScan(record_diff_path, metadata_str(record, "cwd")))
    if diff_path and normalized_path(diff_path) not in seen_diff_paths:
        diff_scans.append(DiffScan(diff_path, workspace_dir))

    base_files = [path for path in [saved_path, diff_path] if path]
    extra_repo_scans = sdd_repo_scans(ctx)
    markdown_paths = collect_agent_markdown_paths(
        workspace_dir,
        diff_scans=diff_scans,
        include_head_commit=include_head_commit,
        existing_files=base_files,
        artifacts_dir=state.current_artifacts_dir,
        extra_repo_scans=extra_repo_scans,
    )
    markdown_source_count = len(markdown_paths)
    markdown_pdf_paths = render_markdown_pdfs(ctx, state, markdown_paths)
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


def enforce_artifact_retention() -> None:
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


def commit_records_from_step_output(
    step_output: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not step_output:
        return []
    records = step_output.get("meta_commits")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def normalized_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def sdd_repo_scans(ctx: AgentExecContext) -> list[Any]:
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

    base_sha = metadata_str(ctx.agent_meta, "sdd_base_sha")
    if base_sha is None:
        base_sha = metadata_str(
            read_transcript_agent_meta(ctx.artifacts_dir),
            "sdd_base_sha",
        )
    agent_name = ctx.agent_name
    if agent_name is None:
        agent_name = metadata_str(
            read_transcript_agent_meta(ctx.artifacts_dir),
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
