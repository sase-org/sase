"""Convenience functions that construct and store notifications."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import append_notification
from sase.project_display_names import humanize_cl_name


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


def notify_monitor_followup_dropped(
    cl_name: str | None,
    monitor_id: str,
    followup_error: str,
) -> str:
    """Send a durable alarm when a monitor's ``--next`` action did not launch.

    A dropped follow-up strands a lane — the composed instruction (which may
    be an entire remaining plan) is not running anywhere. This is raised as
    its own alarm-tagged notification, separate from the routine
    workflow-complete note, so it survives being read past as "just another
    finished monitor".
    """
    notification_id = str(uuid4())
    headline = "Monitor follow-up did not launch"
    if cl_name:
        headline = f"{headline} ({humanize_cl_name(cl_name)})"
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="monitor",
        icon="⚠",
        notes=[
            headline,
            followup_error,
            f"inspect with `sase monitor show {monitor_id} --all-lines`",
        ],
        tags=normalize_notification_tags(["monitor", "error"]),
    )
    append_notification(n)
    return notification_id


def notify_sync_result(
    status: str,
    cl_name: str,
    workspace_dir: str,
    project_file: str,
) -> None:
    """Send a notification after a sync action completes."""
    display_name = humanize_cl_name(cl_name)
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="sync",
        notes=[f"Sync {status} for {display_name}"],
        files=[project_file],
        action="JumpToChangeSpec",  # legacy notification action
        action_data={
            "patch_name": cl_name,
            "changespec_name": cl_name,
            "project_file": project_file,
        },
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
    """Send a notification when all mentors finish for a Patch entry.

    Fires once per (Patch, entry_id) when either every started mentor
    has reached a terminal status, or no mentor profiles matched.

    Args:
        cl_name: Patch name.
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
    display_name = humanize_cl_name(cl_name)
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender=sender,
        notes=[f"Mentors done for {display_name} entry {entry_id}", mentor_summary],
        files=[project_file],
        action="JumpToMentorReview",
        action_data={
            "patch_name": cl_name,
            "changespec_name": cl_name,
            "project_file": project_file,
            "stitch_id": entry_id,
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


def notify_axe_restart_failed(message: str, attempts: list[str]) -> str:
    """Send a durable notification for an exhausted axe restart."""
    notification_id = str(uuid4())
    notes = ["Axe restart failed", message]
    notes.extend(attempts)
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="axe",
        icon="⚠",
        notes=notes,
        tags=normalize_notification_tags(["axe", "restart", "error"]),
    )
    append_notification(n)
    return notification_id


def notify_axe_healed(downtime_seconds: float | None, pid: int) -> str:
    """Send a durable notification after ``sase axe ensure`` heals axe."""
    notification_id = str(uuid4())
    if downtime_seconds is None:
        downtime = "The apparent outage duration is unknown."
    else:
        downtime = f"Axe appeared down for {_format_duration(downtime_seconds)}."
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="axe",
        icon="🪓",
        notes=[
            "Axe self-healed",
            f"Started orchestrator pid {pid}.",
            downtime,
        ],
        tags=normalize_notification_tags(["axe", "healed"]),
    )
    append_notification(n)
    return notification_id


def notify_axe_lock_recovered(
    terminated_pid: int,
    started_pid: int | None,
) -> str:
    """Send an audit notification after recovering a wedged lifecycle lock."""
    notification_id = str(uuid4())
    notes = [
        "Axe recovered a wedged lifecycle lock",
        f"Terminated stale lock holder pid {terminated_pid}.",
    ]
    if started_pid is not None:
        notes.append(f"Started orchestrator pid {started_pid}.")
    else:
        notes.append("The follow-up orchestrator start did not succeed.")
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="axe",
        icon="🪓",
        notes=notes,
        tags=normalize_notification_tags(["axe", "healed", "lock-recovery"]),
    )
    append_notification(n)
    return notification_id


def notify_axe_ensure_failed(message: str, source: str) -> str:
    """Send a durable notification when an axe ensure attempt fails."""
    notification_id = str(uuid4())
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="axe",
        icon="⚠",
        notes=[
            "Axe self-healing failed",
            message,
            f"Source: {source}",
        ],
        tags=normalize_notification_tags(["axe", "ensure", "error"]),
    )
    append_notification(n)
    return notification_id


def notify_axe_restart_storm(sources: list[str], journal_path: str) -> str:
    """Send a durable notification when automatic axe healing is damped."""
    notification_id = str(uuid4())
    source_summary = ", ".join(sources) if sources else "unknown"
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="axe",
        icon="⚠",
        notes=[
            "Axe restart storm damped",
            f"Recent successful start sources: {source_summary}",
            f"Lifecycle journal: {journal_path}",
        ],
        files=[journal_path],
        tags=normalize_notification_tags(["axe", "ensure", "restart-storm"]),
    )
    append_notification(n)
    return notification_id


def _format_duration(seconds: float) -> str:
    rounded = max(0, int(seconds))
    if rounded < 60:
        return f"{rounded}s"
    minutes = rounded // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


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
