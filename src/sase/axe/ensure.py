"""Idempotent axe healing and optional systemd watchdog installation."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, TextIO

import sase.axe.state as _state

from .desired_state import AxeDesiredState, read_desired_state
from .process import canonical_axe_start_command, is_axe_running
from ._process_start import start_axe_daemon_result
from ._process_types import AxeStartResult


DEFAULT_ENSURE_CADENCE_SECONDS = 5 * 60
_ENSURE_SERVICE = "sase-axe-ensure.service"
_ENSURE_TIMER = "sase-axe-ensure.timer"

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


@dataclass(frozen=True)
class _EnsureTimerResult:
    """Outcome of installing or uninstalling the user systemd timer."""

    succeeded: bool
    changed: bool
    message: str


def ensure_axe(
    *,
    rate_limit_seconds: float = 0,
    source: str = "axe ensure",
    now_fn: Callable[[], float] = time.time,
    desired_state_fn: Callable[[], AxeDesiredState | None] = read_desired_state,
    running_fn: Callable[[], bool] = is_axe_running,
    start_fn: Callable[..., AxeStartResult] = start_axe_daemon_result,
    notify_fn: Callable[[float | None, int], str] | None = None,
) -> _AxeEnsureResult:
    """Ensure axe matches its desired running state.

    A missing desired-state marker preserves the historical expectation that
    axe should be running.  An explicit ``stopped`` marker is authoritative.
    The optional rate limit is serialized host-wide so many waiting runners do
    not all probe or start axe during the same outage.
    """
    now = now_fn()
    try:
        lock_file = _acquire_ensure_lock()
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
        if _rate_limit_active(now, rate_limit_seconds):
            return _AxeEnsureResult(
                status="rate_limited",
                message="Axe ensure was checked recently; skipping this poll.",
            )
        _write_rate_limit_marker(now, source=source)

        desired_state = desired_state_fn()
        if desired_state is not None and desired_state.state == "stopped":
            return _AxeEnsureResult(
                status="stopped",
                message=(
                    "Axe is explicitly stopped "
                    f"(source: {desired_state.source}); no healing needed."
                ),
            )
        if running_fn():
            return _AxeEnsureResult(
                status="healthy",
                message="Axe is already running; no healing needed.",
            )

        downtime_seconds = _estimated_downtime_seconds(desired_state, now=now)
        try:
            started = start_fn(
                desired_state_source=source,
                record_desired_state=True,
            )
        except Exception as exc:  # noqa: BLE001 - healing must return an outcome.
            return _AxeEnsureResult(
                status="failed",
                message=f"Axe healing failed before startup completed: {exc}",
                downtime_seconds=downtime_seconds,
            )

        if not started.succeeded or started.pid is None:
            return _AxeEnsureResult(
                status="failed",
                message=started.message
                or "Axe healing failed to start the orchestrator.",
                pid=started.pid,
                downtime_seconds=downtime_seconds,
            )
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
        _release_ensure_lock(lock_file)


def install_ensure_timer(
    *,
    executable: str | None = None,
    unit_dir: Path | None = None,
    systemctl: str | None = None,
    run_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> _EnsureTimerResult:
    """Install and start the opt-in user-level axe ensure timer."""
    executable = executable or canonical_axe_start_command()
    if executable is None:
        return _EnsureTimerResult(
            succeeded=False,
            changed=False,
            message="Could not find a stable `sase` executable for the timer.",
        )
    systemctl = systemctl or shutil.which("systemctl")
    if systemctl is None:
        return _EnsureTimerResult(
            succeeded=False,
            changed=False,
            message="Could not find `systemctl`; the ensure timer was not installed.",
        )

    resolved_unit_dir = unit_dir or _systemd_user_unit_dir()
    service_path = resolved_unit_dir / _ENSURE_SERVICE
    timer_path = resolved_unit_dir / _ENSURE_TIMER
    service = _service_unit(executable)
    timer = _timer_unit()
    changed = (
        _file_contents(service_path) != service or _file_contents(timer_path) != timer
    )
    try:
        resolved_unit_dir.mkdir(parents=True, exist_ok=True)
        service_path.write_text(service, encoding="utf-8")
        timer_path.write_text(timer, encoding="utf-8")
    except OSError as exc:
        return _EnsureTimerResult(
            succeeded=False,
            changed=False,
            message=f"Could not write axe ensure systemd units: {exc}",
        )

    error = _run_systemctl(
        systemctl,
        ("daemon-reload",),
        run_fn=run_fn,
    ) or _run_systemctl(
        systemctl,
        ("enable", "--now", _ENSURE_TIMER),
        run_fn=run_fn,
    )
    if error is not None:
        return _EnsureTimerResult(
            succeeded=False,
            changed=changed,
            message=f"Installed ensure units, but systemd activation failed: {error}",
        )
    return _EnsureTimerResult(
        succeeded=True,
        changed=changed,
        message=(f"Installed and started the axe ensure user timer ({timer_path})."),
    )


def uninstall_ensure_timer(
    *,
    unit_dir: Path | None = None,
    systemctl: str | None = None,
    run_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> _EnsureTimerResult:
    """Stop and remove the opt-in user-level axe ensure timer."""
    resolved_unit_dir = unit_dir or _systemd_user_unit_dir()
    paths = (
        resolved_unit_dir / _ENSURE_SERVICE,
        resolved_unit_dir / _ENSURE_TIMER,
    )
    changed = any(path.exists() for path in paths)
    systemctl = systemctl or shutil.which("systemctl")
    if systemctl is None and changed:
        return _EnsureTimerResult(
            succeeded=False,
            changed=False,
            message="Could not find `systemctl`; existing ensure units were not removed.",
        )

    if systemctl is not None:
        error = _run_systemctl(
            systemctl,
            ("disable", "--now", _ENSURE_TIMER),
            run_fn=run_fn,
            tolerate_failure=not changed,
        )
        if error is not None:
            return _EnsureTimerResult(
                succeeded=False,
                changed=False,
                message=f"Could not stop the axe ensure timer: {error}",
            )

    try:
        for path in paths:
            path.unlink(missing_ok=True)
    except OSError as exc:
        return _EnsureTimerResult(
            succeeded=False,
            changed=False,
            message=f"Could not remove axe ensure systemd units: {exc}",
        )

    if systemctl is not None:
        error = _run_systemctl(
            systemctl,
            ("daemon-reload",),
            run_fn=run_fn,
        )
        if error is not None:
            return _EnsureTimerResult(
                succeeded=False,
                changed=changed,
                message=f"Removed ensure units, but systemd reload failed: {error}",
            )
    return _EnsureTimerResult(
        succeeded=True,
        changed=changed,
        message=(
            "Stopped and removed the axe ensure user timer."
            if changed
            else "The axe ensure user timer is not installed."
        ),
    )


def _ensure_lock_path() -> Path:
    return _state.AXE_STATE_DIR / "ensure.lock"


def _ensure_marker_path() -> Path:
    return _state.AXE_STATE_DIR / "ensure.json"


def _acquire_ensure_lock() -> TextIO | None:
    path = _ensure_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_file = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    except OSError:
        lock_file.close()
        raise
    return lock_file


def _release_ensure_lock(lock_file: TextIO) -> None:
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


def _rate_limit_active(now: float, rate_limit_seconds: float) -> bool:
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


def _write_rate_limit_marker(now: float, *, source: str) -> None:
    _state.atomic_write_json(
        _ensure_marker_path(),
        {"checked_at_epoch": now, "source": source},
    )


def _estimated_downtime_seconds(
    desired_state: AxeDesiredState | None,
    *,
    now: float,
) -> float | None:
    activity_epochs: list[float] = []
    if desired_state is not None:
        desired_epoch = _parse_timestamp(desired_state.timestamp)
        if desired_epoch is not None:
            activity_epochs.append(desired_epoch)

    jack_root = _state.JACK_STATE_DIR
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


def _systemd_user_unit_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "systemd" / "user"


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _service_unit(executable: str) -> str:
    environment = ""
    sase_home = os.environ.get("SASE_HOME")
    if sase_home:
        environment = f"Environment=SASE_HOME={_systemd_quote(sase_home)}\n"
    return (
        "[Unit]\n"
        "Description=Ensure the SASE axe daemon matches its desired state\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"{environment}"
        f"ExecStart={_systemd_quote(executable)} axe ensure\n"
    )


def _timer_unit() -> str:
    cadence = f"{DEFAULT_ENSURE_CADENCE_SECONDS}s"
    return (
        "[Unit]\n"
        "Description=Periodically ensure the SASE axe daemon is healthy\n\n"
        "[Timer]\n"
        "OnBootSec=2min\n"
        f"OnUnitActiveSec={cadence}\n"
        "Persistent=true\n"
        f"Unit={_ENSURE_SERVICE}\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def _file_contents(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _run_systemctl(
    systemctl: str,
    arguments: tuple[str, ...],
    *,
    run_fn: Callable[..., subprocess.CompletedProcess[str]],
    tolerate_failure: bool = False,
) -> str | None:
    try:
        completed = run_fn(
            [systemctl, "--user", *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return str(exc)
    if completed.returncode == 0 or tolerate_failure:
        return None
    return completed.stderr.strip() or completed.stdout.strip() or "unknown error"


__all__ = [
    "DEFAULT_ENSURE_CADENCE_SECONDS",
    "ensure_axe",
    "install_ensure_timer",
    "uninstall_ensure_timer",
]
