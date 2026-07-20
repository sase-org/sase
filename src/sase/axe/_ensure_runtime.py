"""Runtime state and bookkeeping helpers for axe healing."""

from __future__ import annotations

import fcntl
import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

import sase.axe.state as _state

from ._process_probe import get_pid_from_pid_files
from .desired_state import AxeDesiredState
from .lifecycle_journal import (
    lifecycle_journal_path,
    read_recent_successful_starts,
)


_ENSURE_FAILURE_NOTIFICATION_MARKER = "ensure_failure_notification.json"
_ENSURE_STORM_NOTIFICATION_MARKER = "ensure_storm_notification.json"


def published_orchestrator_running() -> bool:
    """Return whether axe has published a live orchestrator PID."""
    return get_pid_from_pid_files() is not None


def _ensure_lock_path() -> Path:
    return _state.axe_state_dir() / "ensure.lock"


def _ensure_marker_path() -> Path:
    return _state.axe_state_dir() / "ensure.json"


def _failure_notification_marker_path() -> Path:
    return _state.axe_state_dir() / _ENSURE_FAILURE_NOTIFICATION_MARKER


def _storm_notification_marker_path() -> Path:
    return _state.axe_state_dir() / _ENSURE_STORM_NOTIFICATION_MARKER


def acquire_axe_ensure_lock(*, blocking: bool = False) -> TextIO | None:
    """Acquire the host-wide lock that serializes axe ensure with stop."""
    path = _ensure_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+", encoding="utf-8")
    try:
        flags = fcntl.LOCK_EX
        if not blocking:
            flags |= fcntl.LOCK_NB
        fcntl.flock(lock_file.fileno(), flags)
    except BlockingIOError:
        lock_file.close()
        return None
    except OSError:
        lock_file.close()
        raise
    return lock_file


def release_axe_ensure_lock(lock_file: TextIO) -> None:
    """Release a lock returned by :func:`acquire_axe_ensure_lock`."""
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def rate_limit_active(now: float, rate_limit_seconds: float) -> bool:
    if rate_limit_seconds <= 0:
        return False
    try:
        data = json.loads(_ensure_marker_path().read_text(encoding="utf-8"))
        checked_at = float(data["checked_at_epoch"])
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
    ):
        return False
    return 0 <= now - checked_at < rate_limit_seconds


def write_rate_limit_marker(now: float, *, source: str) -> None:
    _state.atomic_write_json(
        _ensure_marker_path(),
        {"checked_at_epoch": now, "source": source},
    )


def maybe_notify_ensure_failure(
    message: str,
    *,
    now: float,
    source: str,
    notify_failure_fn: Callable[[str, str], str] | None,
    rate_limit_seconds: float,
) -> str | None:
    if _failure_notification_rate_limit_active(now, rate_limit_seconds):
        return None
    if notify_failure_fn is None:
        from sase.notifications.senders import notify_axe_ensure_failed

        notify_failure_fn = notify_axe_ensure_failed
    try:
        notification_id = notify_failure_fn(message, source)
    except Exception:  # noqa: BLE001 - failure reporting must stay best-effort.
        return None
    _state.atomic_write_json(
        _failure_notification_marker_path(),
        {
            "notified_at_epoch": now,
            "source": source,
            "message": message,
            "notification_id": notification_id,
        },
    )
    return notification_id


def _failure_notification_rate_limit_active(
    now: float,
    rate_limit_seconds: float,
) -> bool:
    if rate_limit_seconds <= 0:
        return False
    try:
        data = json.loads(
            _failure_notification_marker_path().read_text(encoding="utf-8")
        )
        notified_at = float(data["notified_at_epoch"])
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
    ):
        return False
    return 0 <= now - notified_at < rate_limit_seconds


def clear_failure_notification_marker() -> None:
    try:
        _failure_notification_marker_path().unlink(missing_ok=True)
    except OSError:
        pass


def recent_starts_for_damper(
    *,
    now: float,
    window_seconds: float,
) -> list[dict[str, object]]:
    try:
        return read_recent_successful_starts(
            now=now,
            window_seconds=window_seconds,
        )
    except Exception:  # noqa: BLE001 - unavailable audit data must not break ensure.
        return []


def recent_start_sources(records: list[dict[str, object]]) -> list[str]:
    sources: list[str] = []
    for record in records:
        source = record.get("source")
        if isinstance(source, str) and source and source not in sources:
            sources.append(source)
    return sources


def _restart_storm_signature(records: list[dict[str, object]]) -> str:
    contributing_starts = [
        {
            "timestamp_epoch": record.get("timestamp_epoch"),
            "source": record.get("source"),
            "orchestrator_pid": record.get("orchestrator_pid"),
        }
        for record in records
    ]
    payload = json.dumps(
        contributing_starts,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def maybe_notify_restart_storm(
    records: list[dict[str, object]],
    *,
    sources: list[str],
    now: float,
    notify_storm_fn: Callable[[list[str], str], str] | None,
) -> str | None:
    signature = _restart_storm_signature(records)
    marker = _state.read_json(_storm_notification_marker_path())
    if isinstance(marker, dict) and marker.get("signature") == signature:
        return None

    # Persist the signature first so a notification backend failure cannot
    # turn every ensure poll into another alert attempt for the same episode.
    _state.atomic_write_json(
        _storm_notification_marker_path(),
        {
            "signature": signature,
            "notified_at_epoch": now,
            "sources": sources,
        },
    )
    if notify_storm_fn is None:
        from sase.notifications.senders import notify_axe_restart_storm

        notify_storm_fn = notify_axe_restart_storm
    try:
        notification_id = notify_storm_fn(sources, str(lifecycle_journal_path()))
    except Exception:  # noqa: BLE001 - damping must hold without notification I/O.
        return None
    _state.atomic_write_json(
        _storm_notification_marker_path(),
        {
            "signature": signature,
            "notified_at_epoch": now,
            "sources": sources,
            "notification_id": notification_id,
        },
    )
    return notification_id


def estimated_downtime_seconds(
    desired_state: AxeDesiredState | None,
    *,
    now: float,
) -> float | None:
    activity_epochs: list[float] = []
    if desired_state is not None:
        desired_epoch = _parse_timestamp(desired_state.timestamp)
        if desired_epoch is not None:
            activity_epochs.append(desired_epoch)

    jack_root = _state.jack_state_dir()
    try:
        status_paths = tuple(jack_root.glob("*/status.json"))
    except OSError:
        status_paths = ()
    for status_path in status_paths:
        try:
            data = json.loads(status_path.read_text(encoding="utf-8"))
            last_cycle = data.get("last_cycle")
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(last_cycle, str):
            last_cycle_epoch = _parse_timestamp(last_cycle)
            if last_cycle_epoch is not None:
                activity_epochs.append(last_cycle_epoch)

    if not activity_epochs:
        return None
    return max(0.0, now - max(activity_epochs))


def _parse_timestamp(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (OverflowError, ValueError):
        return None
