"""Boot-aware process identity for the detached proc supervisor.

A persisted pid can be recycled after reboot or after the original process
exits, so stop and reconciliation pair the pid with the kernel boot id and
start-tick count before trusting it.
"""

from __future__ import annotations

from pathlib import Path

from sase.ace.hooks.processes import is_process_running

_PROC_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


def _process_identity(pid: int) -> str:
    """Return ``"<boot_id>:<start_ticks>"`` for *pid*, or ``""`` without ``/proc``."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return ""
    close_paren = stat.rfind(")")
    if close_paren < 0:
        return ""
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


def _current_boot_id() -> str:
    """Return the current kernel boot id, or ``""`` when unavailable."""
    try:
        return _PROC_BOOT_ID_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def supervisor_identity_token(pid: int) -> str:
    """Return the durable supervisor token stored as ``Proc.supervisor_id``."""
    identity = _process_identity(pid)
    return identity if identity else f"pid-{pid}"


def _recorded_process_identity(supervisor_id: str | None) -> str | None:
    """Return the ``/proc`` identity encoded in *supervisor_id*, if any."""
    if not supervisor_id or supervisor_id.startswith("pid-"):
        return None
    return supervisor_id


def _recorded_boot_id(supervisor_id: str | None) -> str | None:
    """Return the boot-id component of a recorded supervisor token."""
    identity = _recorded_process_identity(supervisor_id)
    if not identity:
        return None
    boot_id, separator, _rest = identity.partition(":")
    if not separator:
        return None
    return boot_id or None


def supervisor_is_alive(pid: int | None, supervisor_id: str | None) -> bool:
    """Return whether *pid* is still the recorded supervisor process."""
    if pid is None or not is_process_running(pid):
        return False
    recorded = _recorded_process_identity(supervisor_id)
    if not recorded:
        return True
    current = _process_identity(pid)
    if not current:
        return True
    return current == recorded


def supervisor_from_previous_boot(supervisor_id: str | None) -> bool:
    """Return whether *supervisor_id* names a process from a prior boot."""
    recorded = _recorded_boot_id(supervisor_id)
    current = _current_boot_id()
    return bool(recorded and current and recorded != current)


__all__ = [
    "supervisor_from_previous_boot",
    "supervisor_identity_token",
    "supervisor_is_alive",
]
