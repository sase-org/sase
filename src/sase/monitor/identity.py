"""Durable process identity for the monitor supervisor and its child.

A bare pid can be recycled by the OS once the process it named has exited,
so a signal aimed at a persisted pid can land on an unrelated process.
:func:`process_identity` pairs a pid with its boot id and start-tick count,
mirroring :func:`sase.axe.maintenance._process_identity`, so
:func:`supervisor_is_alive` can tell a live supervisor from a different
process that happens to reuse the same pid.
"""

from __future__ import annotations

from sase.ace.hooks.processes import is_process_running
from sase.core.process_identity import process_identity_token


def process_identity(pid: int) -> str:
    """Return a ``"<boot_id>:<start_ticks>"`` identity string for *pid*.

    Returns ``""`` when identity evidence is unavailable for *pid*, so callers
    fall back to a bare liveness check.
    """
    return process_identity_token(pid)


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
