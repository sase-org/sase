"""Idempotent axe healing and optional systemd watchdog installation."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ._ensure_runtime import (
    acquire_axe_ensure_lock as acquire_axe_ensure_lock,
    clear_failure_notification_marker as _clear_failure_notification_marker,
    estimated_downtime_seconds as _estimated_downtime_seconds,
    maybe_notify_ensure_failure as _maybe_notify_ensure_failure,
    maybe_notify_restart_storm as _maybe_notify_restart_storm,
    published_orchestrator_running as _published_orchestrator_running,
    rate_limit_active as _rate_limit_active,
    recent_start_sources as _recent_start_sources,
    recent_starts_for_damper as _recent_starts_for_damper,
    release_axe_ensure_lock as release_axe_ensure_lock,
    write_rate_limit_marker as _write_rate_limit_marker,
)
from ._ensure_timer import (
    DEFAULT_ENSURE_CADENCE_SECONDS,
    install_ensure_timer,
    uninstall_ensure_timer,
)
from ._process_start import start_axe_daemon_result
from ._process_types import AxeStartResult
from .desired_state import AxeDesiredState, read_desired_state
from .lifecycle_journal import lifecycle_journal_path
from .maintenance import clear_stale_maintenance


DEFAULT_ENSURE_FAILURE_NOTIFICATION_CADENCE_SECONDS = 30 * 60
DEFAULT_RESTART_STORM_THRESHOLD = 5
DEFAULT_RESTART_STORM_WINDOW_SECONDS = 30 * 60

EnsureStatus = Literal["failed", "healed", "healthy", "rate_limited", "stopped"]


@dataclass(frozen=True)
class _AxeEnsureResult:
    """Outcome of one idempotent axe health check."""

    status: EnsureStatus
    message: str
    pid: int | None = None
    downtime_seconds: float | None = None
    notification_id: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status != "failed"


def ensure_axe(
    *,
    rate_limit_seconds: float = 0,
    source: str = "axe ensure",
    now_fn: Callable[[], float] = time.time,
    desired_state_fn: Callable[[], AxeDesiredState | None] = read_desired_state,
    running_fn: Callable[[], bool] = _published_orchestrator_running,
    start_fn: Callable[..., AxeStartResult] = start_axe_daemon_result,
    notify_fn: Callable[[float | None, int], str] | None = None,
    notify_failure_fn: Callable[[str, str], str] | None = None,
    failure_notification_rate_limit_seconds: float = (
        DEFAULT_ENSURE_FAILURE_NOTIFICATION_CADENCE_SECONDS
    ),
    restart_storm_threshold: int = DEFAULT_RESTART_STORM_THRESHOLD,
    restart_storm_window_seconds: float = DEFAULT_RESTART_STORM_WINDOW_SECONDS,
    notify_storm_fn: Callable[[list[str], str], str] | None = None,
) -> _AxeEnsureResult:
    """Ensure axe matches its desired running state.

    A missing desired-state marker preserves the historical expectation that
    axe should be running.  An explicit ``stopped`` marker is authoritative.
    The optional rate limit is serialized host-wide so many waiting runners do
    not all probe or start axe during the same outage.
    """
    now = now_fn()
    try:
        lock_file = acquire_axe_ensure_lock()
    except OSError as exc:
        return _AxeEnsureResult(
            status="failed",
            message=f"Could not acquire the axe ensure lock: {exc}",
        )
    if lock_file is None:
        return _AxeEnsureResult(
            status="rate_limited",
            message="Another axe ensure check is already in progress.",
        )

    try:
        try:
            clear_stale_maintenance()
        except Exception:  # noqa: BLE001 - cleanup must not break healing.
            pass
        if _rate_limit_active(now, rate_limit_seconds):
            return _AxeEnsureResult(
                status="rate_limited",
                message="Axe ensure was checked recently; skipping this poll.",
            )
        _write_rate_limit_marker(now, source=source)

        desired_state = desired_state_fn()
        if desired_state is not None and desired_state.state == "stopped":
            _clear_failure_notification_marker()
            return _AxeEnsureResult(
                status="stopped",
                message=(
                    "Axe is explicitly stopped "
                    f"(source: {desired_state.source}); no healing needed."
                ),
            )
        if running_fn():
            _clear_failure_notification_marker()
            return _AxeEnsureResult(
                status="healthy",
                message="Axe is already running; no healing needed.",
            )

        downtime_seconds = _estimated_downtime_seconds(
            desired_state,
            now=now,
        )
        recent_starts = _recent_starts_for_damper(
            now=now,
            window_seconds=restart_storm_window_seconds,
        )
        if restart_storm_threshold > 0 and len(recent_starts) >= (
            restart_storm_threshold
        ):
            _clear_failure_notification_marker()
            sources = _recent_start_sources(recent_starts)
            storm_notification_id = _maybe_notify_restart_storm(
                recent_starts,
                sources=sources,
                now=now,
                notify_storm_fn=notify_storm_fn,
            )
            source_summary = ", ".join(sources) if sources else "unknown"
            return _AxeEnsureResult(
                status="rate_limited",
                message=(
                    "Axe healing was damped after "
                    f"{len(recent_starts)} successful starts within "
                    f"{int(max(0.0, restart_storm_window_seconds) // 60)} minutes "
                    f"(sources: {source_summary}). See {lifecycle_journal_path()}."
                ),
                downtime_seconds=downtime_seconds,
                notification_id=storm_notification_id,
            )
        try:
            started = start_fn(
                desired_state_source=source,
                record_desired_state=True,
            )
        except Exception as exc:  # noqa: BLE001 - healing must return an outcome.
            return _ensure_failure_result(
                message=f"Axe healing failed before startup completed: {exc}",
                downtime_seconds=downtime_seconds,
                now=now,
                source=source,
                notify_failure_fn=notify_failure_fn,
                notification_rate_limit_seconds=(
                    failure_notification_rate_limit_seconds
                ),
            )

        if not started.succeeded or started.pid is None:
            return _ensure_failure_result(
                message=started.message
                or "Axe healing failed to start the orchestrator.",
                pid=started.pid,
                downtime_seconds=downtime_seconds,
                now=now,
                source=source,
                notify_failure_fn=notify_failure_fn,
                notification_rate_limit_seconds=(
                    failure_notification_rate_limit_seconds
                ),
            )
        _clear_failure_notification_marker()
        if started.status == "already_running":
            return _AxeEnsureResult(
                status="healthy",
                message=started.message or "Axe was healed by another process.",
                pid=started.pid,
                downtime_seconds=downtime_seconds,
            )

        if notify_fn is None:
            from sase.notifications.senders import notify_axe_healed

            notify_fn = notify_axe_healed
        notification_id: str | None = None
        try:
            notification_id = notify_fn(downtime_seconds, started.pid)
        except Exception:  # noqa: BLE001 - a healed daemon is still success.
            pass
        return _AxeEnsureResult(
            status="healed",
            message=f"Axe was down and has been healed (pid {started.pid}).",
            pid=started.pid,
            downtime_seconds=downtime_seconds,
            notification_id=notification_id,
        )
    finally:
        release_axe_ensure_lock(lock_file)


def _ensure_failure_result(
    *,
    message: str,
    downtime_seconds: float | None,
    now: float,
    source: str,
    notify_failure_fn: Callable[[str, str], str] | None,
    notification_rate_limit_seconds: float,
    pid: int | None = None,
) -> _AxeEnsureResult:
    notification_id = _maybe_notify_ensure_failure(
        message,
        now=now,
        source=source,
        notify_failure_fn=notify_failure_fn,
        rate_limit_seconds=notification_rate_limit_seconds,
    )
    return _AxeEnsureResult(
        status="failed",
        message=message,
        pid=pid,
        downtime_seconds=downtime_seconds,
        notification_id=notification_id,
    )


__all__ = [
    "DEFAULT_ENSURE_CADENCE_SECONDS",
    "DEFAULT_ENSURE_FAILURE_NOTIFICATION_CADENCE_SECONDS",
    "DEFAULT_RESTART_STORM_THRESHOLD",
    "DEFAULT_RESTART_STORM_WINDOW_SECONDS",
    "acquire_axe_ensure_lock",
    "ensure_axe",
    "install_ensure_timer",
    "release_axe_ensure_lock",
    "uninstall_ensure_timer",
]
