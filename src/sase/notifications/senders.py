"""Convenience functions that construct and store notifications."""

from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sase.core.time import get_timezone
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import (
    append_notification,
    load_notifications,
    upsert_notification,
)
from sase.project_display_names import humanize_cl_name

if TYPE_CHECKING:
    from sase.llm_provider.usage_limit_config import UsageLimitDetection


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
    notification_id: str | None = None,
) -> None:
    """Send a notification when a workflow finishes."""
    files = list(extra_files or [])
    n = Notification(
        id=notification_id or str(uuid4()),
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


def notify_axe_error_digest(record: dict) -> None:
    """Send a grouped digest notification for one rotated error interval.

    *record* is a pending digest record from
    :func:`sase.axe.state.rotate_error_interval`.
    """
    from sase.axe.error_digest import (
        digest_dedup_key,
        digest_notification_note,
        error_digest_dir,
        render_error_digest,
    )
    from sase.core.atomic_json import write_text_atomic

    payload = record
    groups = payload.get("groups")
    if int(payload.get("total") or 0) <= 0 and not (
        isinstance(groups, list) and groups
    ):
        return
    digest_dir = error_digest_dir()
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_name = payload.get("digest_name")
    if not isinstance(digest_name, str) or not digest_name:
        digest_name = (
            f"digest_{datetime.now(get_timezone()).strftime('%Y%m%d_%H%M%S')}.txt"
        )
    digest_file = digest_dir / digest_name
    write_text_atomic(digest_file, render_error_digest(payload))
    interval_id = payload.get("interval_id")
    dedup_key = (
        digest_dedup_key(interval_id)
        if isinstance(interval_id, str) and interval_id
        else None
    )
    note = digest_notification_note(payload)
    n = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="axe",
        notes=[note],
        files=[str(digest_file)],
        action="ViewErrorReport",
        action_data={"error_report_path": str(digest_file)},
        dedup_key=dedup_key,
    )
    if dedup_key:
        try:
            already = any(
                row.sender == "axe" and row.dedup_key == dedup_key
                for row in load_notifications(include_dismissed=True)
            )
        except Exception:  # noqa: BLE001 - fail open and upsert
            already = False
        if already:
            return
        upsert_notification(n, plus_one_note=note)
        return
    append_notification(n)


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


def notify_provider_usage_limit_disabled(
    detection: "UsageLimitDetection",
    *,
    agent_name: str | None = None,
    model: str | None = None,
    drain_notes: Sequence[str] | None = None,
) -> str:
    """Send a notification when a provider is auto-disabled for a usage limit.

    Called once per disable window: the caller only invokes this after
    actually writing a new :class:`TemporaryProviderDisable`, never when an
    already-active disable was left untouched, so this is naturally
    deduplicated per window without any bookkeeping here.

    *drain_notes*, when given, are one or two pre-rendered lines describing
    what a provider drain relaunched and left alone (see
    ``sase.agents._drain_render.usage_limit_drain_report_notes``). Passing
    them makes this the single enriched notification for a disable window
    that also drained; the caller that submitted the drain sends none of
    its own.
    """
    from sase.llm_provider.registry import get_llm_metadata_payload
    from sase.llm_provider.retry_config import truncate_error_snippet

    provider = detection.provider
    providers_meta = get_llm_metadata_payload().get("providers", {})
    provider_meta = (
        providers_meta.get(provider) if isinstance(providers_meta, dict) else None
    )
    display_name = (
        provider_meta.get("display_name") if isinstance(provider_meta, dict) else None
    ) or provider

    duration_text = _format_duration(detection.disable_seconds)
    notes = [
        f"{display_name} disabled for {duration_text} — {detection.matched_pattern}"
    ]

    if detection.expires_at is not None:
        re_enable = _format_reenable_time(detection.expires_at)
        if detection.used_reset_hint:
            notes.append(f"Re-enables at {re_enable}, as reported by the provider.")
        elif detection.reset_source == "usage_window":
            notes.append(f"Re-enables at {re_enable}, based on collected usage data.")
        else:
            notes.append(f"Re-enables at {re_enable}.")
    else:
        notes.append("Disabled until cleared.")

    if agent_name and model:
        notes.append(f"Triggered by agent {agent_name} on {model}.")
    elif agent_name:
        notes.append(f"Triggered by agent {agent_name}.")
    elif model:
        notes.append(f"Triggered on model {model}.")

    if drain_notes:
        notes.extend(drain_notes)

    notes.append(f'Provider said: "{truncate_error_snippet(detection.raw_message)}"')
    notes.append("Launches now route to the next enabled provider in each alias.")

    notification_id = str(uuid4())
    n = Notification(
        id=notification_id,
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="llm.usage_limit",
        icon="⛔",
        notes=notes,
        action="OpenLaunchControl",
        action_data={"provider": provider},
        tags=normalize_notification_tags(["llm", "usage-limit", provider]),
    )
    append_notification(n)
    return notification_id


def _format_reenable_time(epoch: float) -> str:
    dt = datetime.fromtimestamp(epoch, tz=get_timezone())
    clock = dt.strftime("%I:%M %p").lstrip("0")
    tzname = dt.tzname() or ""
    day = dt.strftime("%a %b %-d")
    return f"{clock} {tzname} ({day})".strip()
