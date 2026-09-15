"""Durable handoff for planner completion notifications during epic launch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_subdir
from sase.logs._bounded import log_file_lock

from sase.bead.epic_launch_handoff_io import (
    active_epic_launch_keys,
    age_seconds,
    epic_completion_key,
    read_epic_launch_argv,
    read_json_object,
    read_plan_file,
    restore_pending,
    utc_now,
    write_json_atomic,
)
from sase.bead.epic_launch_handoff_model import (
    EPIC_COMPLETION_GRACE_SECONDS,
    EPIC_COMPLETION_SETTLED_TTL_SECONDS,
    MONITOR_ARTIFACTS_ENV,
    CompletionNotificationPayload,
    DeferredCompletion,
    EpicCompletionSweepResult,
    MonitorCompletionPublishStatus,
)
from sase.bead.epic_launch_handoff_monitor import (
    monitor_settlement_payload,
    monitor_terminal_outcome,
)
from sase.bead.epic_launch_handoff_notifications import (
    completion_notification_id,
    notification_is_durable,
    stable_notification_id,
)
from sase.bead.epic_launch_handoff_payload import (
    fold_epic_launch_outcome,
    send_completion_payload,
    settlement_notification_action_data,
    unknown_outcome_payload,
)


_PathFactory = Callable[[str], tuple[Path, Path]]


def defer_epic_completion(
    artifacts_dir: str | Path | None,
    payload: CompletionNotificationPayload,
) -> bool:
    """Persist *payload* until epic launch settles.

    Returns ``True`` only when the notification was safely deferred. Any
    unusable identity or store failure returns ``False`` so the caller sends
    immediately.
    """
    return _defer_completion(artifacts_dir, payload, path_factory=_handoff_paths)


def defer_epic_completion_until_monitor_settlement(
    root_artifacts_dir: str | Path | None,
    monitor_artifacts_dir: str | Path | None,
    payload: CompletionNotificationPayload,
) -> bool:
    """Persist *payload* for the owning monitor to publish after settlement."""
    if monitor_artifacts_dir is None:
        return False
    retargeted = monitor_settlement_payload(
        root_artifacts_dir,
        monitor_artifacts_dir,
        payload,
    )
    return _defer_completion(
        monitor_artifacts_dir,
        retargeted,
        path_factory=_monitor_handoff_paths,
        notification_identity="monitor",
    )


def _defer_completion(
    artifacts_dir: str | Path | None,
    payload: CompletionNotificationPayload,
    *,
    path_factory: _PathFactory,
    notification_identity: str | None = None,
) -> bool:
    key = epic_completion_key(artifacts_dir)
    if key is None or artifacts_dir is None:
        return False
    pending_path, settled_path = path_factory(key)
    try:
        with log_file_lock(pending_path):
            if settled_path.exists():
                read_json_object(settled_path)
                settled_path.unlink()
                return False
            deferred = DeferredCompletion(
                key=key,
                artifacts_dir=str(artifacts_dir),
                created_at=utc_now(),
                plan_file=read_plan_file(artifacts_dir),
                payload=payload,
                resume_argv=tuple(read_epic_launch_argv(artifacts_dir) or ()),
                notification_id=(
                    stable_notification_id(key, payload, kind=notification_identity)
                    if notification_identity
                    else None
                ),
            )
            write_json_atomic(pending_path, deferred.to_dict())
        return True
    except Exception:
        return False


def claim_epic_completion(
    artifacts_dir: str | Path | None,
    *,
    outcome: Mapping[str, Any],
) -> DeferredCompletion | None:
    """Claim a deferred completion or leave a marker for a later runner."""
    return _claim_completion(
        artifacts_dir,
        outcome=outcome,
        path_factory=_handoff_paths,
    )


def publish_deferred_monitor_completion(
    artifacts_dir: str | Path | None,
    *,
    outcome: Mapping[str, Any],
) -> bool:
    """Publish one monitor-settlement completion payload, if one is pending."""
    return _publish_deferred_monitor_completion(artifacts_dir, outcome=outcome) in {
        "published",
        "already_published",
    }


def _publish_deferred_monitor_completion(
    artifacts_dir: str | Path | None,
    *,
    outcome: Mapping[str, Any],
) -> MonitorCompletionPublishStatus:
    key = epic_completion_key(artifacts_dir)
    if key is None:
        return "none"
    pending_path, settled_path = _monitor_handoff_paths(key)
    try:
        with log_file_lock(pending_path):
            if not pending_path.exists():
                if not settled_path.exists():
                    _write_settled_marker(
                        settled_path,
                        outcome,
                        notification_id=None,
                    )
                return "none"
            deferred = DeferredCompletion.from_dict(read_json_object(pending_path))
            notification_id = completion_notification_id(deferred, kind="monitor")
            if notification_is_durable(notification_id):
                _complete_monitor_publication(
                    pending_path,
                    settled_path,
                    outcome,
                    notification_id=notification_id,
                )
                return "already_published"
            try:
                send_completion_payload(
                    deferred.payload,
                    notification_id=notification_id,
                )
            except Exception:
                if notification_is_durable(notification_id):
                    _complete_monitor_publication(
                        pending_path,
                        settled_path,
                        outcome,
                        notification_id=notification_id,
                    )
                    return "already_published"
                return "failed"
            _complete_monitor_publication(
                pending_path,
                settled_path,
                outcome,
                notification_id=notification_id,
            )
            return "published"
    except Exception:
        return "failed"


def _claim_completion(
    artifacts_dir: str | Path | None,
    *,
    outcome: Mapping[str, Any],
    path_factory: _PathFactory,
) -> DeferredCompletion | None:
    key = epic_completion_key(artifacts_dir)
    if key is None:
        return None
    pending_path, settled_path = path_factory(key)
    try:
        with log_file_lock(pending_path):
            if pending_path.exists():
                deferred = DeferredCompletion.from_dict(read_json_object(pending_path))
                pending_path.unlink()
                return deferred
            settled = dict(outcome)
            settled.setdefault("settled_at", utc_now())
            write_json_atomic(settled_path, settled)
    except Exception:
        return None
    return None


def flush_orphaned_deferrals(
    *,
    now: datetime | None = None,
    grace_seconds: int = EPIC_COMPLETION_GRACE_SECONDS,
    settled_ttl_seconds: int = EPIC_COMPLETION_SETTLED_TTL_SECONDS,
) -> EpicCompletionSweepResult:
    """Flush old unowned deferrals and reap stale settle markers."""
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    active_keys = active_epic_launch_keys()
    store_dir = _epic_completion_store_dir()
    try:
        pending_paths = list(store_dir.glob("*.pending.json"))
        monitor_pending_paths = list(store_dir.glob("*.monitor-pending.json"))
        settled_paths = [
            *store_dir.glob("*.settled.json"),
            *store_dir.glob("*.monitor-settled.json"),
        ]
    except Exception:
        return EpicCompletionSweepResult(errors=1)

    result = EpicCompletionSweepResult()
    for pending_path in pending_paths:
        result = replace(result, pending_scanned=result.pending_scanned + 1)
        try:
            with log_file_lock(pending_path):
                if not pending_path.exists():
                    continue
                deferred = DeferredCompletion.from_dict(read_json_object(pending_path))
                age = age_seconds(deferred.created_at, reference)
                if age < grace_seconds:
                    result = replace(result, young=result.young + 1)
                    continue
                if deferred.key in active_keys:
                    result = replace(result, active=result.active + 1)
                    continue
                pending_path.unlink()
            payload = unknown_outcome_payload(deferred)
            try:
                send_completion_payload(payload)
            except Exception:
                restore_pending(pending_path, deferred)
                raise
            result = replace(result, flushed=result.flushed + 1)
        except Exception:
            result = replace(result, errors=result.errors + 1)

    for pending_path in monitor_pending_paths:
        result = replace(result, pending_scanned=result.pending_scanned + 1)
        try:
            with log_file_lock(pending_path):
                if not pending_path.exists():
                    continue
                deferred = DeferredCompletion.from_dict(read_json_object(pending_path))
                age = age_seconds(deferred.created_at, reference)
                if age < grace_seconds:
                    result = replace(result, young=result.young + 1)
                    continue
                monitor_outcome = monitor_terminal_outcome(deferred.artifacts_dir)
                if monitor_outcome is None:
                    result = replace(result, active=result.active + 1)
                    continue
            status = _publish_deferred_monitor_completion(
                deferred.artifacts_dir,
                outcome=monitor_outcome,
            )
            if status in {"published", "already_published"}:
                result = replace(result, flushed=result.flushed + 1)
            elif status == "failed":
                result = replace(result, errors=result.errors + 1)
        except Exception:
            result = replace(result, errors=result.errors + 1)

    for settled_path in settled_paths:
        pending_path = _pending_path_for_settled_marker(settled_path)
        try:
            with log_file_lock(pending_path):
                if not settled_path.exists():
                    continue
                settled = read_json_object(settled_path)
                settled_at = str(settled["settled_at"])
                if age_seconds(settled_at, reference) < settled_ttl_seconds:
                    continue
                settled_path.unlink()
            result = replace(
                result,
                settled_reaped=result.settled_reaped + 1,
            )
        except Exception:
            result = replace(result, errors=result.errors + 1)
    return result


def _epic_completion_store_dir() -> Path:
    return sase_subdir("notifications") / "epic_completions"


def _handoff_paths(key: str) -> tuple[Path, Path]:
    store_dir = _epic_completion_store_dir()
    return (
        store_dir / f"{key}.pending.json",
        store_dir / f"{key}.settled.json",
    )


def _monitor_handoff_paths(key: str) -> tuple[Path, Path]:
    store_dir = _epic_completion_store_dir()
    return (
        store_dir / f"{key}.monitor-pending.json",
        store_dir / f"{key}.monitor-settled.json",
    )


def _pending_path_for_settled_marker(settled_path: Path) -> Path:
    name = settled_path.name
    if name.endswith(".monitor-settled.json"):
        return settled_path.with_name(
            name.removesuffix(".monitor-settled.json") + ".monitor-pending.json"
        )
    return settled_path.with_name(name.removesuffix(".settled.json") + ".pending.json")


def _complete_monitor_publication(
    pending_path: Path,
    settled_path: Path,
    outcome: Mapping[str, Any],
    *,
    notification_id: str,
) -> None:
    _write_settled_marker(
        settled_path,
        outcome,
        notification_id=notification_id,
    )
    pending_path.unlink(missing_ok=True)


def _write_settled_marker(
    settled_path: Path,
    outcome: Mapping[str, Any],
    *,
    notification_id: str | None,
) -> None:
    settled = dict(outcome)
    settled.setdefault("settled_at", utc_now())
    if notification_id:
        settled["notification_id"] = notification_id
    write_json_atomic(settled_path, settled)


__all__ = [
    "CompletionNotificationPayload",
    "EPIC_COMPLETION_GRACE_SECONDS",
    "EPIC_COMPLETION_SETTLED_TTL_SECONDS",
    "MONITOR_ARTIFACTS_ENV",
    "claim_epic_completion",
    "defer_epic_completion",
    "defer_epic_completion_until_monitor_settlement",
    "flush_orphaned_deferrals",
    "fold_epic_launch_outcome",
    "publish_deferred_monitor_completion",
    "send_completion_payload",
    "settlement_notification_action_data",
]
