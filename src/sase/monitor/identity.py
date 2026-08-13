"""Durable process identity for the monitor supervisor and its child.

A bare pid can be recycled by the OS once the process it named has exited,
so a signal aimed at a persisted pid can land on an unrelated process.
:func:`process_identity` pairs a pid with its boot id and start-tick count,
mirroring :func:`sase.axe.maintenance._process_identity`, so
:func:`supervisor_is_alive` can tell a live supervisor from a different
process that happens to reuse the same pid.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.hooks.processes import is_process_running

_PROC_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def process_identity(pid: int) -> str:
    """Return a ``"<boot_id>:<start_ticks>"`` identity string for *pid*.

    Returns ``""`` when ``/proc`` is unavailable (e.g. macOS) or *pid*'s
    stat cannot be read, so callers fall back to a bare liveness check.
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
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
    try:
        boot_id = _PROC_BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        boot_id = ""
    return f"{boot_id}:{start_ticks}"


def supervisor_is_alive(pid: int | None, recorded_identity: str | None) -> bool:
    """Return whether *pid* is alive and still the recorded supervisor.

    A live pid whose current identity does not match *recorded_identity*
    has been recycled by the OS for an unrelated process and must be
    treated as dead. A platform without ``/proc`` support (no identity
    available for the live pid) falls back to the bare liveness check,
    matching the current behavior on platforms like macOS.
    """
    if pid is None or not is_process_running(pid):
        return False
    if not recorded_identity:
        return True
    current_identity = process_identity(pid)
    if not current_identity:
        return True
    return current_identity == recorded_identity


__all__ = ["process_identity", "supervisor_is_alive"]
