"""Pure service-health derivation for the Services footer pill.

Takes the already-cached :class:`ServiceStatusSnapshot`; never touches disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._service_severity import (
    proc_clean_exit,
    service_host_severity,
    service_proc_severity,
)

if TYPE_CHECKING:
    from sase.service.status import ServiceStatusProc, ServiceStatusSnapshot


@dataclass(frozen=True)
class ServiceHealth:
    """Roll-up of host and counted-proc health."""

    running: int
    desired: int
    healthy: bool
    summary: str = ""
    known: bool = True


def _is_counted(proc: ServiceStatusProc) -> bool:
    if not proc.enablement.enabled:
        return False
    return proc.desired == "running" or not proc.available


def _proc_problem(proc: ServiceStatusProc) -> str | None:
    if not proc.available:
        return f"{proc.name} unavailable"
    severity = service_proc_severity(
        proc.state,
        proc.desired,
        available=proc.available,
        enabled=proc.enablement.enabled,
        clean_exit=proc_clean_exit(proc),
    )
    if severity in ("fail", "warn"):
        return f"{proc.name} {proc.state or 'not running'}"
    return None


def derive_service_health(snapshot: ServiceStatusSnapshot | None) -> ServiceHealth:
    """Return the health roll-up for ``snapshot`` (unknown when unreadable)."""
    if snapshot is None:
        return ServiceHealth(0, 0, False, "service status unavailable", False)
    counted = [proc for proc in snapshot.procs if _is_counted(proc)]
    running = sum(1 for proc in counted if proc.state == "running")
    summary = ""
    host_state = snapshot.host.state
    if host_state == "running" or service_host_severity(host_state) == "warn":
        summary = ""
    elif host_state == "stale":
        summary = "host stale"
    else:
        summary = "host stopped"
    if not summary:
        for proc in counted:
            problem = _proc_problem(proc)
            if problem is not None:
                summary = problem
                break
    return ServiceHealth(running, len(counted), not summary, summary)
