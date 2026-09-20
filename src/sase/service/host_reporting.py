"""Status snapshot construction for the foreground service host."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping

from sase.ace.hooks.processes import is_process_running
from sase.service.config import ServiceConfigComposition
from sase.service.host_models import PendingRestart, RunningProc
from sase.service.host_support import package_version, read_reported_status
from sase.service.paths import service_proc_output_log_path
from sase.service.state import (
    ServiceHostRecord,
    ServiceStateSnapshot,
    read_service_state,
)
from sase.service.config import load_service_config
from sase.service.status import (
    ServiceHostObservation,
    ServiceProcLastExit,
    ServiceProcObservation,
    build_service_status,
    write_service_status,
)
from sase.service.restart import ServiceRestartDecision


def write_current_host_status(
    host: object,
    config: ServiceConfigComposition | None = None,
    state: ServiceStateSnapshot | None = None,
) -> None:
    """Write a snapshot from a host's current private runtime records."""
    composition = load_service_config() if config is None else config
    state_snapshot = read_service_state() if state is None else state
    _write_host_status(
        composition,
        state_snapshot,
        boot_id=host._boot_id,  # type: ignore[attr-defined]
        started_at=host._started_at,  # type: ignore[attr-defined]
        unit=host._unit,  # type: ignore[attr-defined]
        children=host._children,  # type: ignore[attr-defined]
        pending_restarts=host._pending,  # type: ignore[attr-defined]
        last_exits=host._last_exits,  # type: ignore[attr-defined]
        restart_decisions=host._restart_decisions,  # type: ignore[attr-defined]
    )


def _write_host_status(
    composition: ServiceConfigComposition,
    state_snapshot: ServiceStateSnapshot,
    *,
    boot_id: str,
    started_at: float,
    unit: str | None,
    children: Mapping[str, RunningProc],
    pending_restarts: Mapping[str, PendingRestart],
    last_exits: Mapping[str, ServiceProcLastExit],
    restart_decisions: Mapping[str, ServiceRestartDecision],
) -> None:
    observations = [
        _observation(name, running, last_exits, restart_decisions)
        for name, running in children.items()
    ]
    for name, pending in pending_restarts.items():
        if name not in children:
            observations.append(
                ServiceProcObservation(
                    name=name,
                    alive=False,
                    last_exit=pending.last_exit,
                    restart=pending.decision,
                    restarts=pending.restarts,
                    log_path=str(service_proc_output_log_path(name)),
                )
            )
    snapshot = build_service_status(
        composition,
        state_snapshot,
        ServiceHostObservation(
            record=ServiceHostRecord(
                pid=os.getpid(),
                boot_id=boot_id,
                started_at=started_at,
                heartbeat_at=time.time(),
                mode="foreground",
                unit=unit,
                sase_version=package_version(),
            ),
            lock_held=True,
            pid_alive=True,
        ),
        observations,
    )
    write_service_status(snapshot)


def _observation(
    name: str,
    running: RunningProc,
    last_exits: Mapping[str, ServiceProcLastExit],
    restart_decisions: Mapping[str, ServiceRestartDecision],
) -> ServiceProcObservation:
    return ServiceProcObservation(
        name=name,
        pid=running.process.pid if is_process_running(running.process.pid) else None,
        alive=running.process.poll() is None,
        proc_id=running.proc_id,
        started_at=running.started_at,
        last_exit=running.last_exit or last_exits.get(name),
        restart=running.restart_decision or restart_decisions.get(name),
        restarts=running.restarts,
        reported=read_reported_status(name),
        log_path=str(service_proc_output_log_path(name)),
    )
