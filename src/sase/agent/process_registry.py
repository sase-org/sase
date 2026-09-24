"""Registry of SASE-owned processes that tree termination must not treat as leaks.

An agent's process tree can legitimately contain processes that SASE tracks on
their own: a proc-shell or monitor supervisor the agent started, or a freshly
launched sibling agent still parented to the launcher. Terminating the tree
must stop a supervisor through its canonical stop, so the store record settles
instead of being orphaned as "running", and must leave other agents alone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial


@dataclass(frozen=True)
class RegisteredSupervisor:
    """A registered supervisor and the pids that belong to it."""

    label: str
    pids: frozenset[int]
    stop: Callable[[], object]


@dataclass(frozen=True)
class ProcessRegistry:
    """Supervisors to stop canonically and pids that must never be signalled."""

    supervisors: tuple[RegisteredSupervisor, ...] = ()
    protected_pids: frozenset[int] = frozenset()


def read_process_registry(root_pid: int) -> ProcessRegistry | None:
    """Read the durable registry, or ``None`` when it cannot be read.

    An unreadable registry means a leaked process cannot be told apart from a
    detached supervisor or a sibling agent, so callers must not signal
    anything that only the registry could vouch for.
    """
    try:
        from sase.agent.running_listing import list_running_agents
        from sase.procs.models import ACTIVE_PROC_STATUSES, TUI_PROC_KIND
        from sase.procs.runner import kill_proc
        from sase.procs.store import read_procs

        agents = list_running_agents(index_freshness="revalidate")
        procs = read_procs(status=ACTIVE_PROC_STATUSES)
    except Exception:
        return None

    supervisors: list[RegisteredSupervisor] = []
    supervisor_pids: set[int] = set()
    protected: set[int] = set()
    proc_ids = {proc.proc_id for proc in procs}
    for proc in procs:
        pids = frozenset(pid for pid in (proc.pid, proc.pgid) if pid)
        if not pids:
            continue
        if proc.kind == TUI_PROC_KIND:
            # TUI-owned procs can only be stopped by their owning TUI.
            protected |= pids
            continue
        supervisors.append(
            RegisteredSupervisor(
                f"proc {proc.proc_id}", pids, partial(kill_proc, proc.proc_id)
            )
        )
        supervisor_pids |= pids

    for agent in agents:
        if agent.pid is None or agent.pid == root_pid:
            continue
        if agent.monitor_id and agent.monitor_state == "running":
            if agent.monitor_id in proc_ids:
                continue  # already covered by its proc-store row above
            stop = _legacy_monitor_stop(agent.project, agent.artifacts_dir)
            if stop is not None:
                pids = frozenset({agent.pid})
                supervisors.append(
                    RegisteredSupervisor(f"monitor {agent.monitor_id}", pids, stop)
                )
                supervisor_pids |= pids
                continue
        protected.add(agent.pid)

    return ProcessRegistry(
        supervisors=tuple(supervisors),
        protected_pids=frozenset(protected - supervisor_pids),
    )


def _legacy_monitor_stop(
    project: str, artifacts_dir: str | None
) -> Callable[[], object] | None:
    if not artifacts_dir:
        return None

    def _stop() -> object:
        from sase.monitor.store import read_monitor_marker, stop_monitor

        record = read_monitor_marker(project, artifacts_dir)
        return stop_monitor(record) if record is not None else None

    return _stop


__all__ = [
    "ProcessRegistry",
    "RegisteredSupervisor",
    "read_process_registry",
]
