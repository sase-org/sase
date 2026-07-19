"""Convenience functions that construct and store notifications."""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import append_notification


def notify_memory_proposed(proposal: Any) -> str:
    """Send a notification for a pending long-term memory proposal."""
    notification_id = str(uuid4())
    evidence_count = len(getattr(proposal, "evidence", ()) or ())
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="memory.proposed",
        notes=[
            f"Memory proposal ready: {proposal.title}",
            f"{proposal.author_name} proposed {proposal.target_path}",
            f"{evidence_count} evidence item(s)",
        ],
        files=_memory_proposal_evidence_files(proposal),
        action="memory_review",
        action_data={"proposal_id": proposal.proposal_id},
        tags=normalize_notification_tags(["memory"]),
    )
    append_notification(n)
    return notification_id


def _memory_proposal_evidence_files(proposal: Any) -> list[str]:
    files: list[str] = []
    for evidence in getattr(proposal, "evidence", ()) or ():
        resolved_path = getattr(evidence, "resolved_path", None)
        if isinstance(resolved_path, str) and resolved_path:
            files.append(resolved_path)
    return files


def notify_workflow_complete(
    sender: str,
    cl_name: str | None,
    success: bool,
    notes: list[str],
    action: str | None = None,
    action_data: dict[str, str] | None = None,
    extra_files: list[str] | None = None,
    silent: bool = False,
    tags: list[str] | None = None,
) -> None:
    """Send a notification when a workflow finishes."""
    files = list(extra_files or [])
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        notes=notes,
        files=files,
        action=action,
        action_data=action_data or {},
        silent=silent,
        tags=normalize_notification_tags(tags),
    )
    append_notification(n)


def notify_sync_result(
    status: str,
    cl_name: str,
    workspace_dir: str,
    project_file: str,
) -> None:
    """Send a notification after a sync action completes."""
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="sync",
        notes=[f"Sync {status} for {cl_name}"],
        files=[project_file],
        action="JumpToChangeSpec",
        action_data={"changespec_name": cl_name, "project_file": project_file},
    )
    append_notification(n)


def notify_mentors_complete(
    cl_name: str,
    project_file: str,
    entry_id: str,
    mentor_summary: str,
    has_comments: bool,
    sender: str = "mentors",
) -> None:
    """Send a notification when all mentors finish for a ChangeSpec entry.

    Fires once per (ChangeSpec, entry_id) when either every started mentor
    has reached a terminal status, or no mentor profiles matched.

    Args:
        cl_name: ChangeSpec name.
        project_file: Path to the ``.gp`` project file.
        entry_id: COMMITS entry ID this notification refers to.
        mentor_summary: Human-readable one-line summary, e.g.
            ``"3/3 mentors finished (1 commented)"`` or
            ``"no mentor profiles matched"``.
        has_comments: Whether at least one mentor produced review comments.
            Reflected in notes only — the action handler re-reads truth
            from disk at action time.
        sender: Notification sender label.
    """
    del has_comments  # Reflected in mentor_summary; truth re-read at action time.
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        notes=[f"Mentors done for {cl_name} entry {entry_id}", mentor_summary],
        files=[project_file],
        action="JumpToMentorReview",
        action_data={
            "changespec_name": cl_name,
            "project_file": project_file,
            "entry_id": entry_id,
        },
    )
    append_notification(n)


def notify_axe_error_digest(
    errors: list[dict],
) -> None:
    """Send a digest notification summarising recent axe errors."""
    digest_dir = sase_subdir("axe") / "error_digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_file = (
        digest_dir
        / f"digest_{datetime.now(get_timezone()).strftime('%Y%m%d_%H%M%S')}.txt"
    )
    lines: list[str] = []
    for i, err in enumerate(errors, 1):
        lines.append(f"{'=' * 60}")
        lines.append(f"Error {i}/{len(errors)}")
        lines.append(f"  Time:       {err.get('timestamp', 'unknown')}")
        lines.append(f"  Lumberjack: {err.get('lumberjack', 'unknown')}")
        lines.append(f"  Job:        {err.get('job', 'unknown')}")
        lines.append(f"  Error:      {err.get('error', 'unknown')}")
        tb = err.get("traceback", "")
        if tb:
            lines.append("  Traceback:")
            for tb_line in tb.splitlines():
                lines.append(f"    {tb_line}")
        lines.append("")
    digest_file.write_text("\n".join(lines))

    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="axe",
        notes=[f"{len(errors)} error(s) in the last hour"],
        files=[str(digest_file)],
        action="ViewErrorReport",
        action_data={"error_report_path": str(digest_file)},
    )
    append_notification(n)


def notify_hitl_request(
    step_name: str,
    workflow_name: str,
    artifacts_dir: str,
) -> None:
    """Send a notification when a HITL prompt is waiting for user input."""
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="hitl",
        notes=[f"HITL waiting: step '{step_name}' in {workflow_name}"],
        action="HITL",
        action_data={"artifacts_dir": artifacts_dir},
    )
    append_notification(n)
