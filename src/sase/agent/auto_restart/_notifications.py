"""Notification publishing for automatic agent restarts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.auto_restart._notify_report import (
    COLOR,
    ICON,
    SENDER,
    build_episode_report,
    display_episode,
    episode_report_path,
    episode_records,
    is_relaunched,
    refresh_episode_report,
    signature_text,
    verdict_of,
    witnesses_of,
)


def _episode_dedup_key(episode_id: str) -> str:
    """Return the upsert dedup key for one update episode."""
    return f"agent-auto-restart:{episode_id}"


def _timestamp() -> str:
    from datetime import datetime

    from sase.core.time import get_timezone

    return datetime.now(get_timezone()).isoformat()


def _episode_notes(episode_id: str, records: list[Any]) -> list[str]:
    """Build the episode row notes honoring the copy rules.

    ``notes[0]`` is the calm title (never "fail"/"error"); exception text
    appears only in note 2 or later.
    """
    display = display_episode(episode_id)
    relaunched = [r for r in records if is_relaunched(r)]
    count = len(relaunched)
    if count == 1:
        name = str(getattr(relaunched[0].record, "agent_name", "") or "1 agent")
        title = f"↻ Restarted {name} after sase update {display}"
        lowered = title.lower()
        if "fail" in lowered or "error" in lowered:
            title = f"↻ Restarted 1 agent after sase update {display}"
        notes = [title]
    else:
        notes = [f"↻ Restarted {count} agents after sase update {display}"]

    symbols = sorted(
        {
            str(w["file_proof"].get("symbol", ""))
            for r in records
            for w in [witnesses_of(r)]
            if isinstance(w.get("file_proof"), dict)
            and str(w["file_proof"].get("symbol") or "")
        }
    )
    if symbols:
        notes.append(
            "sase changed while they waited: their in-memory code asked the new "
            f"files for {symbols[0]}, which no longer matched what they imported."
        )
    else:
        notes.append(
            "sase changed while they waited, and the new code no longer matched "
            "what they had imported."
        )

    by_project: dict[str, list[str]] = {}
    for stored in relaunched:
        project = str(getattr(stored.record, "project", "") or "sase")
        name = str(getattr(stored.record, "agent_name", "") or "?")
        by_project.setdefault(project, []).append(f"{name} · {signature_text(stored)}")
    for project in sorted(by_project):
        names = ", ".join(sorted(by_project[project]))
        notes.append(f"• {names} ({project}) — relaunched under the same names")

    pre_provider = all(
        str(verdict_of(r).get("phase_class") or "") == "pre_provider"
        for r in relaunched
    )
    if relaunched and pre_provider:
        refreshed = any(
            isinstance(witnesses_of(r).get("refresh_log_line"), dict)
            for r in relaunched
        )
        if refreshed:
            notes.append(
                f"Nothing was lost: all {count} broke while refreshing after "
                "%wait, before their model turn."
            )
        else:
            notes.append(
                f"Nothing was lost: all {count} broke before their model turn."
            )
    notes.append(
        "Each agent gets one automatic restart. If one breaks again you will "
        "get a normal failure notice and sase will not retry it."
    )
    return notes


def _episode_tags(records: list[Any]) -> list[str]:
    from sase.notifications.models import normalize_notification_tags

    tiers = sorted(
        {
            str(verdict_of(r).get("tier") or "")
            for r in records
            if str(verdict_of(r).get("tier") or "")
        }
    )
    tier_tag = tiers[0] if tiers else "update-skew"
    return normalize_notification_tags(["sase-update", "auto-restart", tier_tag])


def _episode_evidence_files(records: list[Any]) -> list[str]:
    """Collect preserved evidence paths for one episode's records."""
    files: list[str] = []
    for stored in records:
        evidence = getattr(stored.record, "evidence_dir", None)
        if evidence and str(evidence) not in files:
            files.append(str(evidence))
            report = Path(str(evidence)) / "error_report.md"
            try:
                if report.is_file() and str(report) not in files:
                    files.insert(len(files) - 1, str(report))
            except OSError:
                pass
    return files[:20]


def _resolve_dedup_key(episode_id: str) -> str:
    """Return the live dedup key, rolling over dismissed episodes.

    When the episode row (or its latest ``#N`` continuation) was dismissed,
    the next restart opens a new ``<episode>#N`` row instead of reviving the
    dismissed one. A restart is never invisible.
    """
    from sase.notifications.store import load_notifications

    base = _episode_dedup_key(episode_id)
    try:
        rows = load_notifications(include_dismissed=True)
    except Exception:
        return base
    owned = [
        r for r in rows if r.sender == SENDER and (r.dedup_key or "").startswith(base)
    ]
    if not owned:
        return base

    def _suffix(key: str) -> int:
        rest = key[len(base) :]
        if not rest:
            return 1
        if rest.startswith("#") and rest[1:].isdigit():
            return int(rest[1:])
        return 0

    numbered = [(_suffix(r.dedup_key or ""), r) for r in owned]
    numbered = [(n, r) for n, r in numbered if n > 0]
    if not numbered:
        return base
    top_n, top_row = max(numbered, key=lambda item: item[0])
    if not top_row.dismissed:
        return top_row.dedup_key or base
    return f"{base}#{top_n + 1}"


def _refresh_row_content(dedup_key: str, episode_id: str) -> None:
    """Refresh the episode row's notes and inline snapshot in place.

    Uses the reconcile path, which leaves delivery cursors untouched, so
    the refresh never re-toasts or re-pushes.
    """
    from sase.notifications.models import Notification
    from sase.notifications.store import load_notifications, reconcile_notification_rows

    try:
        rows = load_notifications(include_dismissed=True)
    except Exception:
        return
    current = next(
        (r for r in rows if r.sender == SENDER and r.dedup_key == dedup_key),
        None,
    )
    if current is None or current.dismissed:
        return
    records = episode_records(episode_id)
    notes = _episode_notes(episode_id, records)
    action_data = dict(current.action_data)
    path = episode_report_path(episode_id)
    action_data["report_path"] = str(path)
    action_data["report_title"] = notes[0][:64]
    try:
        snapshot = build_episode_report(episode_id, records)
        action_data["report"] = json.dumps(snapshot)
    except Exception:
        pass
    refreshed = Notification(
        id=current.id,
        timestamp=current.timestamp,
        sender=current.sender,
        icon=current.icon,
        color=current.color,
        notes=notes,
        files=list(current.files),
        tags=list(current.tags),
        action=current.action,
        action_data=action_data,
        read=current.read,
        dismissed=current.dismissed,
        silent=current.silent,
        muted=current.muted,
        snooze_until=current.snooze_until,
        resurfaced_at=current.resurfaced_at,
        plus_ones=list(current.plus_ones),
        plus_ones_dropped=current.plus_ones_dropped,
        dedup_key=current.dedup_key,
    )
    try:
        reconcile_notification_rows([refreshed])
    except Exception:
        pass


def _guarded_upsert(notification: Any, *, plus_one_note: str) -> Any:
    """Upsert one notification; skip silently when the store is unavailable."""
    from sase.core.state_write_guard import best_effort_test_state_write_allowed
    from sase.notifications.store import notifications_file_path, upsert_notification

    try:
        path = notifications_file_path()
    except Exception:
        return None
    try:
        if not best_effort_test_state_write_allowed(
            path, category="auto-restart-notifications"
        ):
            return None
    except Exception:
        pass
    try:
        return upsert_notification(
            notification,
            plus_one_note=plus_one_note,
            plus_one_timestamp=notification.timestamp,
        )
    except Exception:
        return None


def publish_relaunch(
    *,
    episode_id: str,
    agent_name: str,
    update_ref: str,
    reason_text: str,
    evidence_files: list[str] | None = None,
) -> Any:
    """Upsert the episode row for one relaunch (plus-one within it).

    The first relaunch in an episode creates the row (and its single
    information toast); later relaunches append one ``+1`` note each and
    refresh the title, notes, and inline report snapshot in place without
    moving delivery cursors.
    """
    from sase.notifications.models import Notification

    ref = update_ref or display_episode(episode_id)
    dedup_key = _resolve_dedup_key(episode_id)
    records = episode_records(episode_id)
    notes = (
        _episode_notes(episode_id, records)
        if records
        else [f"↻ Restarted {agent_name} after sase update {ref}"]
    )
    files = list(evidence_files or []) or _episode_evidence_files(records)
    path = episode_report_path(episode_id)
    action_data = {"report_path": str(path), "report_title": notes[0][:64]}
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=SENDER,
        icon=ICON,
        color=COLOR,
        notes=notes,
        files=files,
        tags=_episode_tags(records),
        action="ViewReport",
        action_data=action_data,
        dedup_key=dedup_key,
    )
    outcome = _guarded_upsert(notification, plus_one_note=f"Restarted {agent_name}")
    try:
        refresh_episode_report(episode_id)
    except Exception:
        pass
    try:
        _refresh_row_content(dedup_key, episode_id)
    except Exception:
        pass
    return outcome


def publish_escalation(
    *,
    agent_name: str,
    title: str,
    detail: str,
    episode_id: str | None = None,
    kind: str = "decline",
    artifacts_dir: str | None = None,
) -> Any:
    """Post one loud error-severity escalation.

    ``kind="storm"`` posts as ``agent.auto-restart`` with ``ViewErrorReport``
    so it lands in the Errors bucket at error severity. Every other kind
    re-surfaces the agent's own failure notification (``sender=user-agent``)
    with the escalation sentence appended, per the escalation spec. Callers
    may still pass an explicit title/detail; storm copy is built here so all
    storm rows read identically.
    """
    if kind != "storm":
        return resurface_failure(
            agent_name=agent_name,
            reason_text=f"{title} {detail}".strip(),
            artifacts_dir=artifacts_dir,
        )
    from sase.notifications.models import Notification, normalize_notification_tags

    storm_title = title or (
        f"Auto-restart paused: agents kept breaking during episode "
        f"{display_episode(episode_id or 'unknown')} — this looks like a real "
        "bug, not an update race."
    )
    notes = [storm_title]
    if detail:
        notes.append(detail)
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender=SENDER,
        icon=ICON,
        color=COLOR,
        notes=notes,
        tags=normalize_notification_tags(["sase-update", "auto-restart", "error"]),
        action="ViewErrorReport",
        dedup_key=(
            f"{_episode_dedup_key(episode_id)}:{agent_name}:storm"
            if episode_id
            else f"agent-auto-restart:{agent_name}:storm"
        ),
    )
    outcome = _guarded_upsert(notification, plus_one_note=storm_title)
    if episode_id:
        try:
            refresh_episode_report(episode_id)
        except Exception:
            pass
    return outcome


def resurface_failure(
    *,
    agent_name: str,
    reason_text: str,
    artifacts_dir: str | None = None,
) -> Any:
    """Make the original failure visible again with one explanatory note.

    Rebuilds the standard failure notification (``sender=user-agent``,
    ``ViewErrorReport``, Errors bucket) from ``done.json`` and
    ``error_report.md`` when the row is missing; never swallows the failure.
    """
    from sase.notifications.models import Notification, normalize_notification_tags

    notes = [f"{agent_name} failed and was not restarted automatically."]
    if reason_text:
        notes.append(reason_text)
    files: list[str] = []
    if artifacts_dir:
        report = Path(artifacts_dir) / "error_report.md"
        try:
            if report.is_file():
                files.append(str(report))
        except OSError:
            pass
    notification = Notification(
        id=str(uuid4()),
        timestamp=_timestamp(),
        sender="user-agent",
        notes=notes,
        files=files,
        tags=normalize_notification_tags(["auto-restart", "resurfaced"]),
        action="ViewErrorReport",
        dedup_key=f"agent-auto-restart-resurfaced:{agent_name}",
    )
    return _guarded_upsert(
        notification, plus_one_note=f"{agent_name} still needs attention"
    )
