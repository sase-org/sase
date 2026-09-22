"""Private runtime records for the foreground service host."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from sase.service.config import ServiceProcConfig
from sase.service.restart import ServiceRestartDecision, ServiceRestartHistory
from sase.service.status import ServiceProcLastExit


@dataclass
class RunningProc:
    """A direct child currently supervised by the service host."""

    entry: ServiceProcConfig
    signature: str
    process: subprocess.Popen[bytes]
    proc_id: str
    supervisor_id: str
    started_at: float
    stop_requested: bool = False
    restart_history: ServiceRestartHistory = field(
        default_factory=ServiceRestartHistory
    )
    restart_decision: ServiceRestartDecision | None = None
    last_exit: ServiceProcLastExit | None = None
    restarts: int = 0


@dataclass
class PendingRestart:
    """A child awaiting its configured restart delay."""

    entry: ServiceProcConfig
    signature: str
    restart_at: float
    history: ServiceRestartHistory
    decision: ServiceRestartDecision
    restarts: int
    last_exit: ServiceProcLastExit | None


@dataclass
class GivenUp:
    """A proc the restart policy gave up on, parked until revived."""

    signature: str
    decision: ServiceRestartDecision
    last_exit: ServiceProcLastExit | None
    restarts: int
    given_up_at: float
