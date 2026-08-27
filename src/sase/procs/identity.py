"""Boot-aware process identity for the detached proc supervisor.

A persisted pid can be recycled after reboot or after the original process
exits, so stop and reconciliation pair the pid with the kernel boot id and
start-tick count before trusting it.
"""

from __future__ import annotations

from sase.ace.hooks.processes import is_process_running
from sase.core.process_identity import (
    identity_from_previous_boot,
    process_identity_matches,
    process_identity_token,
)


def supervisor_identity_token(pid: int) -> str:
    """Return the durable supervisor token stored as ``Proc.supervisor_id``."""
    identity = process_identity_token(pid)
    return identity if identity else f"pid-{pid}"


def _recorded_process_identity(supervisor_id: str | None) -> str | None:
    """Return the ``/proc`` identity encoded in *supervisor_id*, if any."""
    if not supervisor_id or supervisor_id.startswith("pid-"):
        return None
    return supervisor_id


def supervisor_is_alive(pid: int | None, supervisor_id: str | None) -> bool:
    """Return whether *pid* is still the recorded supervisor process."""
    if pid is None or not is_process_running(pid):
        return False
    recorded = _recorded_process_identity(supervisor_id)
    return process_identity_matches(pid, recorded)


def supervisor_from_previous_boot(supervisor_id: str | None) -> bool:
    """Return whether *supervisor_id* names a process from a prior boot."""
    return identity_from_previous_boot(_recorded_process_identity(supervisor_id))


__all__ = [
    "supervisor_from_previous_boot",
    "supervisor_identity_token",
    "supervisor_is_alive",
]
