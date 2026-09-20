"""Process-launch and filesystem helpers for the service host."""

from __future__ import annotations

import functools
import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path
from typing import BinaryIO

from sase.service.config import ServiceProcConfig
from sase.service.executable import ResolvedLauncherArgv, resolve_launcher_argv
from sase.service.paths import service_proc_dir
from sase.service.status import ServiceProcReportedStatus
from sase.supervision import pump_output

STATUS_REPORT_MAX_BYTES = 32 * 1024


def entry_launch(entry: ServiceProcConfig) -> ResolvedLauncherArgv:
    """Return the spawn argv for ``entry`` and why its executable may not resolve.

    Builtin launchers and the ``/bin/sh -lc`` string form are returned as-is:
    the former already resolve their own executables and the latter is a shell
    line whose inner names the shell resolves.
    """
    launcher = entry.launcher
    if launcher is None:
        return ResolvedLauncherArgv(())
    if launcher.kind == "builtin":
        if launcher.builtin == "scheduler":
            return ResolvedLauncherArgv((*sase_command(), "scheduler", "run"))
        if launcher.builtin == "gateway":
            return ResolvedLauncherArgv(gateway_builtin_argv())
        return ResolvedLauncherArgv(())
    # Popen resolves a bare name against the child's env, so honor a PATH the
    # entry overrides; otherwise this is the host's own PATH.
    which_fn = functools.partial(
        shutil.which,
        path=os.path.expandvars(str(entry.env["PATH"]))
        if "PATH" in entry.env
        else None,
    )
    if launcher.argv:
        return resolve_launcher_argv(tuple(launcher.argv), which_fn=which_fn)
    if isinstance(launcher.command, str):
        return ResolvedLauncherArgv(("/bin/sh", "-lc", launcher.command))
    return resolve_launcher_argv(
        tuple(str(part) for part in launcher.command or ()), which_fn=which_fn
    )


def gateway_builtin_argv() -> tuple[str, ...]:
    from sase.integrations.mobile_gateway import prepare_mobile_gateway_service_launch

    return tuple(prepare_mobile_gateway_service_launch().argv)


def entry_env(entry: ServiceProcConfig, proc_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in entry.env.items():
        env[str(key)] = os.path.expandvars(str(value))
    env["SASE_SERVICE_PROC"] = entry.name
    env["SASE_SERVICE_PROC_DIR"] = str(proc_dir)
    env["SASE_SERVICE_PROC_STATUS"] = str(proc_dir / "status.json")
    return env


def entry_signature(entry: ServiceProcConfig) -> str:
    payload = {
        "after": entry.after,
        "available": entry.available,
        "cwd": entry.cwd,
        "env": entry.env,
        "launcher": None
        if entry.launcher is None
        else {
            "argv": entry.launcher.argv,
            "builtin": entry.launcher.builtin,
            "command": entry.launcher.command,
            "kind": entry.launcher.kind,
        },
        "log_max_bytes": entry.log_max_bytes,
        "mode": entry.mode,
        "restart": entry.restart,
        "stop_signal": entry.stop_signal,
        "stop_timeout_seconds": entry.stop_timeout_seconds,
        "success_exit_codes": entry.success_exit_codes,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def read_reported_status(name: str) -> ServiceProcReportedStatus | None:
    path = service_proc_dir(name) / "status.json"
    try:
        if path.stat().st_size > STATUS_REPORT_MAX_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    summary = str(payload.get("summary") or "").strip()
    state = str(payload.get("state") or "").strip()
    if not summary or not state:
        return None
    try:
        updated_at = float(payload.get("updated_at") or path.stat().st_mtime)
    except (TypeError, ValueError, OSError):
        updated_at = time.time()
    return ServiceProcReportedStatus(
        summary=summary[:200], state=state[:64], updated_at=updated_at
    )


def pump_service_output(stream: BinaryIO, log_path: Path, max_bytes: int) -> None:
    pump_output(stream, lambda chunk: append_bounded_log(log_path, chunk, max_bytes))


def append_bounded_log(path: Path, chunk: bytes, max_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(chunk)
    if max_bytes <= 0:
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size <= max_bytes:
        return
    with path.open("rb") as handle:
        handle.seek(max(0, size - max_bytes))
        data = handle.read()
    with path.open("wb") as handle:
        handle.write(data)


def signal_number(name: str) -> int:
    if name.isdigit():
        return int(name)
    normalized = name if name.startswith("SIG") else f"SIG{name}"
    return int(getattr(signal, normalized, signal.SIGTERM))


def terminal_status(exit_code: int | None, success_exit_codes: tuple[int, ...]) -> str:
    if exit_code == 0 or (exit_code is not None and exit_code in success_exit_codes):
        return "success"
    return "error"


def process_group(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return None


def sase_command() -> tuple[str, ...]:
    invoked = Path(sys.argv[0])
    if invoked.name == "sase" and invoked.exists():
        return (str(invoked),)
    found = shutil.which("sase")
    if found is not None:
        return (found,)
    return (sys.executable, "-m", "sase")


def package_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("sase")
    except Exception:
        return None


def handover_scheduler() -> bool:
    try:
        from sase.axe.lock import is_lifecycle_lock_held
        from sase.axe.process import stop_axe_daemon_result

        if not is_lifecycle_lock_held():
            return True
        result = stop_axe_daemon_result(record_desired_state=False, timeout=10.0)
        if result.error is not None or result.failed_pids:
            return False
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not is_lifecycle_lock_held():
                return True
            time.sleep(0.1)
        return False
    except Exception:
        return False
