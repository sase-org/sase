"""Pure service-health derivation for the Services footer pill.

Takes the already-cached :class:`ServiceStatusSnapshot`; never touches disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.service.status import ServiceStatusProc, ServiceStatusSnapshot

_FAILED_STATES = frozenset({"failed", "error"})


@dataclass(frozen=True)
class ServiceHealth:
    """Roll-up of host and counted-proc health."""

    running: int
    desired: int
    healthy: bool
    summary: str = ""


def _is_counted(proc: ServiceStatusProc) -> bool:
    if not proc.enablement.enabled:
        return False
    return proc.desired == "running" or not proc.available


def _proc_problem(proc: ServiceStatusProc) -> str | None:
    if not proc.available:
        return f"{proc.name} unavailable"
    if proc.state in _FAILED_STATES:
        return f"{proc.name} {proc.state}"
    if proc.desired == "running" and proc.state != "running":
        return f"{proc.name} {proc.state or 'not running'}"
    return None


def derive_service_health(snapshot: ServiceStatusSnapshot | None) -> ServiceHealth:
    """Return the health roll-up for ``snapshot`` (healthy 0/0 when unknown)."""
    if snapshot is None:
        return ServiceHealth(0, 0, True)
    counted = [proc for proc in snapshot.procs if _is_counted(proc)]
    running = sum(1 for proc in counted if proc.state == "running")
    summary = ""
    if snapshot.host.state != "running":
        summary = "host stopped"
    else:
        for proc in counted:
            problem = _proc_problem(proc)
            if problem is not None:
                summary = problem
                break
    return ServiceHealth(running, len(counted), not summary, summary)
