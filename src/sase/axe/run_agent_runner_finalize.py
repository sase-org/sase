"""Post-execution finalization helpers for ``run_agent_runner``.

Contains the bookkeeping that runs after the agent's execution loop:
exec-outcome classification, error done.json writing, Prometheus run
metrics + structured run log, and the user-completion notification.
"""

import json
import os
from typing import Any

from sase.axe.image_attachments import append_unique_paths
from sase.axe.run_agent_phases import build_done_marker, record_stop_time
from sase.telemetry.metrics import (
    AGENT_ACTIVE,
    AGENT_RUN_DURATION,
    AGENT_RUNS,
)


def classify_exec_success(*, success: bool, outcome: str) -> bool:
    """Map execution-loop outcomes to runner success semantics.

    Plan-rejected runs are reported as success because the user explicitly
    chose to abort — the runner itself didn't fail.
    """
    return success or outcome == "plan_rejected"


def write_error_done_marker(
    *,
    current_artifacts_dir: str,
    cl_name: str,
    project_file: str,
    timestamp: str,
    artifacts_timestamp: str,
    workspace_num: int,
    workspace_dir: str,
    output_path: str,
    agent_name: str | None,
    agent_model: str | None,
    agent_llm_provider: str | None,
    agent_vcs_provider: str | None,
    agent_hidden: bool,
    error: str,
    traceback_str: str,
) -> None:
    """Write a failed ``done.json`` so the TUI can display the error.

    Best-effort: swallows write failures so an exception in the error
    handler doesn't mask the original error.
    """
    try:
        error_done = build_done_marker(
            cl_name,
            project_file,
            timestamp,
            artifacts_timestamp,
            workspace_num,
            workspace_dir,
            output_path,
            "failed",
            agent_name=agent_name,
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
            agent_vcs_provider=agent_vcs_provider,
            agent_hidden=agent_hidden,
            error=error,
            traceback_str=traceback_str,
        )
        done_path = os.path.join(current_artifacts_dir, "done.json")
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(error_done, f, indent=2)
    except Exception:
        pass


def record_completion_metrics(
    *,
    success: bool,
    duration_seconds: float,
    agent_llm_provider: str | None,
    agent_model: str | None,
    workflow_name: str,
    project_name: str,
    cl_name: str,
    workspace_num: int,
    artifacts_dir: str,
    current_artifacts_dir: str,
    prompt: str,
) -> None:
    """Record Prometheus run metrics, stop time, and structured run log."""
    provider = agent_llm_provider or ""
    AGENT_RUNS.labels(
        llm_provider=provider,
        status="ok" if success else "error",
        workflow=workflow_name,
    ).inc()
    AGENT_RUN_DURATION.labels(llm_provider=provider, workflow=workflow_name).observe(
        duration_seconds
    )
    AGENT_ACTIVE.labels(llm_provider=provider, project=project_name).dec()

    record_stop_time(artifacts_dir, current_artifacts_dir)

    try:
        from sase.logs.run_log import log_agent_run

        log_agent_run(
            workflow=workflow_name,
            project=project_name,
            branch_or_workspace=cl_name,
            workspace_num=workspace_num,
            model=agent_model,
            llm_provider=agent_llm_provider,
            duration_seconds=duration_seconds,
            status="success" if success else "failed",
            artifacts_dir=current_artifacts_dir,
            prompt_preview=prompt[:100] if prompt else None,
        )
    except Exception:
        pass


def send_completion_notification(
    *,
    cl_name: str,
    artifacts_timestamp: str,
    workflow_name: str,
    success: bool,
    agent_hidden: bool,
    agent_name: str | None,
    agent_model: str | None,
    agent_llm_provider: str | None,
    error_summary: str | None,
    error_report_path: str | None,
    saved_path: str | None,
    diff_path: str | None,
    markdown_pdf_paths: list[str] | None = None,
    markdown_source_count: int | None = None,
    image_paths: list[str] | None = None,
    output_path: str,
    step_output: dict[str, Any] | None,
    prompt: str,
    outcome: str | None = None,
) -> None:
    from sase.attachments.markdown_pdf import MAX_MARKDOWN_PDF_ATTACHMENTS
    from sase.llm_provider.registry import format_provider_model_label
    from sase.notifications.senders import notify_workflow_complete

    if outcome == "plan_rejected":
        return

    extra_files = [p for p in [saved_path, diff_path] if p]

    # For failures: attach error report (first) and output log
    if not success:
        if error_report_path:
            extra_files.insert(0, error_report_path)
        if os.path.isfile(output_path):
            extra_files.append(output_path)
    extra_files.extend(append_unique_paths(markdown_pdf_paths or [], extra_files))
    extra_files.extend(append_unique_paths(image_paths or [], extra_files))

    agent_label = format_provider_model_label(agent_llm_provider, agent_model)

    # Build notes — include error summary for failures
    name_part = f" @{agent_name}" if agent_name else ""
    notes = [
        f"{agent_label}{name_part} {'completed' if success else 'failed'}: {workflow_name}"
    ]
    if not success and error_summary:
        notes.append(error_summary)
    if (
        markdown_source_count is not None
        and markdown_source_count > MAX_MARKDOWN_PDF_ATTACHMENTS
    ):
        notes.append(
            f"Edited {markdown_source_count} Markdown files; skipped PDF attachments "
            f"because the limit is {MAX_MARKDOWN_PDF_ATTACHMENTS}."
        )

    # For failures with an error report, use ViewErrorReport action
    # so <enter> opens the report in $EDITOR. Otherwise JumpToAgent.
    commit_message = (step_output or {}).get("meta_commit_message")
    pr_url = (step_output or {}).get("meta_pr_url")

    action: str
    action_data: dict[str, str]
    if not success and error_report_path:
        action = "ViewErrorReport"
        action_data = {
            "error_report_path": error_report_path,
            "cl_name": cl_name,
            "raw_suffix": artifacts_timestamp,
            **({"agent_name": agent_name} if agent_name else {}),
            **({"commit_message": commit_message} if commit_message else {}),
            **({"pr_url": pr_url} if pr_url else {}),
        }
    else:
        action = "JumpToAgent"
        action_data = {
            "cl_name": cl_name,
            "raw_suffix": artifacts_timestamp,
            **({"agent_name": agent_name} if agent_name else {}),
            **({"model": agent_model} if agent_model else {}),
            **({"llm_provider": agent_llm_provider} if agent_llm_provider else {}),
            "prompt": prompt,
            **({"commit_message": commit_message} if commit_message else {}),
            **({"pr_url": pr_url} if pr_url else {}),
        }

    notify_workflow_complete(
        sender="user-agent",
        cl_name=cl_name,
        success=success,
        notes=notes,
        action=action,
        action_data=action_data,
        extra_files=extra_files,
        silent=agent_hidden,
    )
