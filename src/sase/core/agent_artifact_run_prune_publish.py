"""Episode-scoped publishing of ACE-run prune preview notifications."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sase.chops import ChopReport
from sase.config import get_artifact_retention_trash_grace_days
from sase.core.agent_artifact_run_prune_review import (
    build_review,
    encode_run_prune_review,
    human_size,
    preview_fingerprint,
    project_label_or_unavailable,
    snapshot_dir,
    write_snapshot,
)
from sase.core.agent_artifact_run_retention import AceRunRetentionPlan
from sase.core.time import get_timezone
from sase.notification_gates.durability import file_lock
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import (
    load_notifications,
    mark_many_dismissed,
    upsert_notification,
)
from sase.project_display_names import load_project_ref_display_snapshot

PREVIEW_DEDUP_PREFIX = "artifact_run_prune:"
_NOTIFICATION_SENDER = "axe"
_NOTIFICATION_TAGS = ("artifact-retention", "ace-run", "preview")
_PREVIEW_COMMAND = "sase artifact prune-runs"
_LAST_PREVIEW_KEY = "last_preview_dedup_key"
_PUBLISH_LOCK_NAME = ".publish.lock"
_EPISODE_HEX_LEN = 8

PublishAction = Literal["created", "plus_oned", "retired", "none"]


@dataclass(frozen=True)
class _RunPrunePublishOutcome:
    """Result of publishing or retiring a run-prune preview."""

    fingerprint: str
    dedup_key: str | None
    notification_id: str | None
    action: PublishAction
    selected: int
    bytes: int
    unavailable_sources: tuple[str, ...]


def publish_run_prune_preview(plan: AceRunRetentionPlan) -> _RunPrunePublishOutcome:
    """Publish an inbox preview for *plan*, or retire live rows if none remain."""

    with _publish_lock():
        return _publish_locked(plan)


def end_run_prune_preview_episode() -> int:
    """Retire every live preview row and clear the last-preview key."""

    with _publish_lock():
        return _end_episode_locked()


def _publish_locked(plan: AceRunRetentionPlan) -> _RunPrunePublishOutcome:
    fingerprint = preview_fingerprint(plan)
    if not _should_notify(plan):
        retired = _end_episode_locked()
        return _outcome(
            plan,
            fingerprint=fingerprint,
            action="retired" if retired else "none",
        )

    timestamp = datetime.now(get_timezone()).isoformat()
    _, snapshot_path = write_snapshot(plan, captured_at=datetime.now(get_timezone()))
    review = build_review(plan, fingerprint=fingerprint)
    previous_key = _read_last_preview_key(snapshot_path.parent)
    dedup_key = _choose_dedup_key(fingerprint, previous_key)
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_NOTIFICATION_SENDER,
        icon="!" if plan.sources_unavailable else "🧹",
        color="#D14343" if plan.sources_unavailable else "#2F80ED",
        notes=_notification_notes(plan),
        tags=normalize_notification_tags(_NOTIFICATION_TAGS),
        action="ViewReport",
        action_data={
            "report_title": "ACE run pruning preview",
            "report": json.dumps(_preview_report(plan).to_dict(), sort_keys=True),
            "preview_command": _PREVIEW_COMMAND,
            "run_prune_review": encode_run_prune_review(review),
        },
        dedup_key=dedup_key,
    )
    upsert_outcome = upsert_notification(
        notification,
        plus_one_note=_plus_one_note(plan),
        plus_one_timestamp=timestamp,
        supersedes=previous_key if previous_key != dedup_key else None,
    )
    action: PublishAction = (
        "created" if upsert_outcome.action == "created" else "plus_oned"
    )
    if action == "created":
        stale_ids = [
            row.id for row in _live_preview_rows() if (row.dedup_key or "") != dedup_key
        ]
        if stale_ids:
            mark_many_dismissed(stale_ids)
    _write_last_preview_key(snapshot_path.parent, dedup_key)
    return _outcome(
        plan,
        fingerprint=fingerprint,
        action=action,
        dedup_key=dedup_key,
        notification_id=upsert_outcome.id or notification.id,
    )


def _end_episode_locked() -> int:
    rows = _live_preview_rows()
    retired = mark_many_dismissed(row.id for row in rows) if rows else 0
    _clear_last_preview_key(snapshot_dir())
    return retired


def _choose_dedup_key(fingerprint: str, previous_key: str | None) -> str:
    parsed = _parse_episode_key(previous_key)
    live = _live_preview_rows()
    if (
        parsed is not None
        and parsed[0] == fingerprint
        and all((row.dedup_key or "") == previous_key for row in live)
    ):
        assert previous_key is not None
        return previous_key
    return _mint_episode_key(fingerprint)


def _parse_episode_key(key: str | None) -> tuple[str, str] | None:
    if not key:
        return None
    parts = key.split(":")
    if len(parts) != 3 or f"{parts[0]}:" != PREVIEW_DEDUP_PREFIX:
        return None
    fingerprint, episode = parts[1], parts[2]
    if not fingerprint or not episode:
        return None
    return fingerprint, episode


def _mint_episode_key(fingerprint: str) -> str:
    return f"{PREVIEW_DEDUP_PREFIX}{fingerprint}:{uuid4().hex[:_EPISODE_HEX_LEN]}"


def _live_preview_rows() -> list[Notification]:
    rows = load_notifications(include_dismissed=False)
    return [
        row
        for row in rows
        if row.sender == _NOTIFICATION_SENDER
        and (row.dedup_key or "").startswith(PREVIEW_DEDUP_PREFIX)
    ]


def _should_notify(plan: AceRunRetentionPlan) -> bool:
    counts = plan.counts
    return bool(
        counts.selected or counts.empty_out_of_range_shards or plan.sources_unavailable
    )


def _notification_notes(plan: AceRunRetentionPlan) -> list[str]:
    counts = plan.counts
    if plan.sources_unavailable:
        return [
            "ACE run pruning is paused",
            (
                f"{len(plan.sources_unavailable)} protection sources are unreadable; "
                "nothing will be pruned until they recover."
            ),
            "Press Enter for details.",
        ]
    return [
        f"{human_size(plan.reclaimable_bytes)} of old ACE runs can be pruned",
        (
            f"{counts.selected:,} runs · {len(build_review(plan).projects)} projects · "
            f"older than {_month_label(build_review(plan).first_kept_month)} · "
            f"{counts.protected:,} protected"
        ),
        (
            "Press Enter to review — runs move to restorable trash for "
            f"{get_artifact_retention_trash_grace_days()} days."
        ),
    ]


def _plus_one_note(plan: AceRunRetentionPlan) -> str:
    if plan.sources_unavailable:
        return f"Still paused: {len(plan.sources_unavailable)} protection sources are unreadable."
    return (
        f"Still available: {human_size(plan.reclaimable_bytes)} across "
        f"{plan.counts.selected:,} runs."
    )


def _preview_report(plan: AceRunRetentionPlan) -> ChopReport:
    counts = plan.counts
    review = build_review(plan)
    display = load_project_ref_display_snapshot(projects_root=plan.policy.projects_root)
    report = ChopReport(title="ACE run pruning preview")
    if plan.sources_unavailable:
        report.headline("ACE run pruning is paused", tone="warn")
    else:
        report.headline(
            f"{counts.selected:,} old ACE runs · "
            f"{human_size(plan.reclaimable_bytes)} reclaimable",
            tone="info",
        )
    report.kv(
        {
            "Runs": f"{counts.selected:,}",
            "Reclaimable": human_size(plan.reclaimable_bytes),
            "Projects": str(len(review.projects)),
            "Protected": f"{counts.protected:,}",
            "Keeping": f"newest {plan.policy.keep_recent_months} months",
        }
    )
    if plan.sources_unavailable:
        report.heading("Protection Problems")
        report.bullets(tuple(plan.sources_unavailable[:12]), tone="warn", glyph="!")
    if review.projects:
        rows = report.rows(columns=("Project", "Runs", "Size", "Span"))
        for project in review.projects:
            rows.row(
                (
                    project_label_or_unavailable(display, project.project),
                    f"{project.runs:,}",
                    human_size(project.bytes),
                    f"{_format_timestamp(project.oldest)} – "
                    f"{_format_timestamp(project.newest)}",
                )
            )
    if plan.empty_out_of_range_shards:
        report.heading("Empty shards")
        rows = report.rows(columns=("Project", "Kind", "Path"))
        for shard in plan.empty_out_of_range_shards[:10]:
            shard_project = shard.project or "-"
            rows.row(
                (
                    project_label_or_unavailable(display, shard_project),
                    shard.kind,
                    shard.path,
                )
            )
    if plan.sources_unavailable:
        report.text("Press Enter for details.", tone="muted")
    else:
        report.text(
            (
                "Enter: review and move to trash (restorable "
                f"{get_artifact_retention_trash_grace_days()} days)"
            ),
            tone="muted",
        )
        report.text(f"CLI: {_PREVIEW_COMMAND} --apply", tone="muted")
    return report


def _read_last_preview_key(directory: Path) -> str | None:
    try:
        value = (directory / _LAST_PREVIEW_KEY).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _write_last_preview_key(directory: Path, value: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".preview-key.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / _LAST_PREVIEW_KEY)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _clear_last_preview_key(directory: Path) -> None:
    try:
        (directory / _LAST_PREVIEW_KEY).unlink()
    except FileNotFoundError:
        return


def _format_timestamp(timestamp: str) -> str:
    try:
        moment = datetime.strptime(timestamp[:8], "%Y%m%d")
    except ValueError:
        return timestamp
    return moment.strftime("%b %-d")


def _month_label(month: str) -> str:
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%b %Y")
    except ValueError:
        return month


def _outcome(
    plan: AceRunRetentionPlan,
    *,
    fingerprint: str,
    action: PublishAction,
    dedup_key: str | None = None,
    notification_id: str | None = None,
) -> _RunPrunePublishOutcome:
    return _RunPrunePublishOutcome(
        fingerprint=fingerprint,
        dedup_key=dedup_key,
        notification_id=notification_id,
        action=action,
        selected=plan.counts.selected,
        bytes=plan.reclaimable_bytes,
        unavailable_sources=tuple(plan.sources_unavailable),
    )


@contextmanager
def _publish_lock() -> Iterator[None]:
    with file_lock(snapshot_dir() / _PUBLISH_LOCK_NAME):
        yield


__all__ = [
    "PREVIEW_DEDUP_PREFIX",
    "end_run_prune_preview_episode",
    "publish_run_prune_preview",
]
