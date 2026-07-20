"""Systemd timer management for periodic axe healing."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .process import canonical_axe_start_command


DEFAULT_ENSURE_CADENCE_SECONDS = 5 * 60
_ENSURE_SERVICE = "sase-axe-ensure.service"
_ENSURE_TIMER = "sase-axe-ensure.timer"


@dataclass(frozen=True)
class _EnsureTimerResult:
    """Outcome of installing or uninstalling the user systemd timer."""

    succeeded: bool
    changed: bool
    message: str


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
