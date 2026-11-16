"""Monitor-specific effects for the Agent Hijack stop transaction."""

from __future__ import annotations

from dataclasses import dataclass

from sase.agent.hijack._stop_models import HijackTarget, StopDeps


@dataclass(frozen=True, slots=True)
class _MonitorStopResult:
    """Whether the exact monitor supervisor reached a proven terminal state."""

    success: bool
    survivors: tuple[int, ...] = ()
    error: str | None = None
    identity_error: bool = False
    monitor_record: object | None = None


def stop_monitor_target(target: HijackTarget, *, deps: StopDeps) -> _MonitorStopResult:
    """Stop *target* through its canonical monitor adapter.

    Resolution uses the durable monitor ID and artifacts generation. The
    supervisor identity is checked again in ``stop_monitor`` immediately
    before the signal, so a stale index row or recycled PID cannot redirect
    the stop to another process.
    """
    from sase.monitor.identity import process_identity
    from sase.monitor.store import (
        MonitorStopBlockedError,
        MonitorStopIdentityError,
        read_monitor_marker,
        stop_monitor,
    )

    try:
        if not target.monitor_id:
            raise MonitorStopIdentityError("monitor target has no durable monitor ID")
        current = read_monitor_marker(target.project_name, target.artifacts_dir)
        if current is None:
            raise MonitorStopIdentityError("monitor markers could not be resolved")
        if (
            current.monitor_id != target.monitor_id
            or current.artifacts_dir != target.artifacts_dir
            or current.timestamp != target.artifacts_timestamp
            or current.pid != target.pid
        ):
            raise MonitorStopIdentityError(
                "durable monitor ID, member, generation, or supervisor changed"
            )

        expected_identity = (
            target.monitor_supervisor_identity
            or current.supervisor_identity
            or (process_identity(current.pid) if current.pid is not None else "")
        )
        if not expected_identity:
            raise MonitorStopIdentityError(
                "monitor supervisor identity is unavailable; nothing was signalled"
            )
        if (
            current.supervisor_identity
            and current.supervisor_identity != expected_identity
        ):
            raise MonitorStopIdentityError(
                "monitor supervisor identity changed; nothing was signalled"
            )

        stopper = deps.stop_monitor or stop_monitor
        stopped = stopper(
            current,
            expected_supervisor_identity=expected_identity,
            wait_for_supervisor_exit=True,
        )
    except MonitorStopBlockedError as exc:
        pid = current.pid if current is not None else target.pid
        return _MonitorStopResult(
            success=False,
            survivors=(pid,) if pid is not None else (),
            error=str(exc),
            monitor_record=current,
        )
    except MonitorStopIdentityError as exc:
        return _MonitorStopResult(
            success=False,
            error=str(exc),
            identity_error=True,
        )
    except Exception as exc:  # noqa: BLE001 - monitor custody remains pinned.
        return _MonitorStopResult(
            success=False,
            error=f"monitor stop failed: {exc}",
        )
    if (
        stopped.monitor_id != target.monitor_id
        or stopped.artifacts_dir != target.artifacts_dir
        or stopped.timestamp != target.artifacts_timestamp
        or stopped.pid != target.pid
    ):
        return _MonitorStopResult(
            success=False,
            error="monitor identity changed while stopping; custody retained",
            identity_error=True,
            monitor_record=stopped,
        )
    if stopped.monitor_state == "running":
        pid = stopped.pid
        return _MonitorStopResult(
            success=False,
            survivors=(pid,) if pid is not None else (),
            error="monitor command or supervisor remained running after stop",
            monitor_record=stopped,
        )
    return _MonitorStopResult(success=True, monitor_record=stopped)


__all__ = ["stop_monitor_target"]
