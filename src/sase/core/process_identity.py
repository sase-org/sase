"""Boot-aware process identity helpers for persisted PIDs.

A PID alone is not durable: Linux can reuse it after a process exits, and
thread IDs share the same numeric namespace. These helpers pair a PID with
kernel boot/start-time evidence when ``/proc`` is available, while preserving
legacy bare-PID behavior on platforms where that evidence cannot be read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
import subprocess
from pathlib import Path

_PROC_ROOT = Path("/proc")
_SUBPROCESS_POPEN = subprocess.Popen


def _current_boot_id() -> str:
    """Return the current kernel boot id, or ``""`` when unavailable."""
    try:
        return (
            (_PROC_ROOT / "sys/kernel/random/boot_id")
            .read_text(encoding="utf-8")
            .strip()
        )
    except OSError:
        if _can_use_darwin_fallback():
            return _darwin_boot_id()
        return ""


def process_identity_token(pid: int) -> str:
    """Return ``"<boot_id>:<start_ticks>"`` for *pid*, or ``""`` without ``/proc``."""
    try:
        stat = (_PROC_ROOT / str(pid) / "stat").read_text(encoding="utf-8")
    except OSError:
        if _can_use_darwin_fallback():
            start_ticks = _darwin_process_start_ticks(pid)
            if start_ticks is not None:
                return f"{_current_boot_id()}:{start_ticks}"
        return ""
    close_paren = stat.rfind(")")
    if close_paren < 0:
        return ""
    # The tail starts at field 3 (state); process start time is field 22.
    fields = stat[close_paren + 1 :].split()
    try:
        start_ticks = int(fields[19])
    except (IndexError, ValueError):
        return ""
    return f"{_current_boot_id()}:{start_ticks}"


def _recorded_identity_is_verifiable(recorded: object) -> bool:
    if not isinstance(recorded, str) or not recorded:
        return False
    boot_id, separator, start_ticks = recorded.partition(":")
    if not separator:
        return False
    try:
        int(start_ticks)
    except ValueError:
        return False
    # An empty boot-id component is still useful legacy evidence: older callers
    # produced this shape when start ticks were readable but boot id was not.
    return boot_id == "" or bool(boot_id)


def process_identity_matches(pid: int, recorded: object) -> bool:
    """Return whether *pid* still matches a recorded identity token.

    Missing, malformed, or currently unreadable identity evidence preserves the
    legacy behavior and returns ``True``. Only a definite recorded/current token
    mismatch returns ``False``.
    """
    if not _recorded_identity_is_verifiable(recorded):
        return True
    current = process_identity_token(pid)
    if not current:
        return True
    return current == recorded


def identity_from_previous_boot(recorded: object) -> bool:
    """Return whether a recorded identity token names a previous kernel boot."""
    if not _recorded_identity_is_verifiable(recorded):
        return False
    boot_id = str(recorded).partition(":")[0]
    current = _current_boot_id()
    return bool(boot_id and current and boot_id != current)


def pid_is_thread(pid: int) -> bool:
    """Return whether *pid* is currently a thread ID rather than a process ID."""
    try:
        status = (_PROC_ROOT / str(pid) / "status").read_text(encoding="utf-8")
    except OSError:
        return False
    values: dict[str, int] = {}
    for line in status.splitlines():
        key, separator, value = line.partition(":")
        if not separator or key not in {"Tgid", "Pid"}:
            continue
        try:
            values[key] = int(value.strip().split()[0])
        except (IndexError, ValueError):
            return False
    tgid = values.get("Tgid")
    pid_value = values.get("Pid")
    return tgid is not None and pid_value is not None and tgid != pid_value


def current_boot_time_utc() -> datetime | None:
    """Return the current boot time in UTC, derived from ``/proc/uptime``."""
    try:
        uptime_text = (_PROC_ROOT / "uptime").read_text(encoding="utf-8")
        uptime_seconds = float(uptime_text.split()[0])
    except (IndexError, OSError, ValueError):
        if _can_use_darwin_fallback():
            boot_seconds = _darwin_boot_seconds()
            if boot_seconds is not None:
                return datetime.fromtimestamp(boot_seconds, UTC)
        return None
    return datetime.now(UTC) - timedelta(seconds=uptime_seconds)


def _can_use_darwin_fallback() -> bool:
    return _PROC_ROOT == Path("/proc") and not _PROC_ROOT.exists()


def _darwin_boot_id() -> str:
    boot_seconds = _darwin_boot_seconds()
    return f"darwin-{boot_seconds}" if boot_seconds is not None else ""


def _darwin_boot_seconds() -> int | None:
    result = _run_text_command(["sysctl", "-n", "kern.boottime"])
    if result is None:
        return None
    returncode, stdout = result
    if returncode != 0:
        return None
    match = re.search(r"sec = (\d+)", stdout)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _darwin_process_start_ticks(pid: int) -> int | None:
    result = _run_text_command(["ps", "-o", "lstart=", "-p", str(pid)])
    if result is None:
        return None
    returncode, stdout = result
    if returncode != 0:
        return None
    raw = stdout.strip()
    if not raw:
        return None
    try:
        started = datetime.strptime(raw, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    return int(started.timestamp())


def _run_text_command(argv: list[str]) -> tuple[int, str] | None:
    try:
        process = _SUBPROCESS_POPEN(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, _stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return None
    except Exception:  # noqa: BLE001 - process identity is best-effort metadata
        return None
    return process.returncode, stdout


__all__ = [
    "current_boot_time_utc",
    "identity_from_previous_boot",
    "pid_is_thread",
    "process_identity_matches",
    "process_identity_token",
]
