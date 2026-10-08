"""Shared constants and types for agent-scope sweeping.

The sweep engine lives in :mod:`sase.agent._scope_sweep_core`, the runner's
own-scope teardown in :mod:`sase.agent._scope_sweep_own`, and the orphaned-scope
reaper backstop in :mod:`sase.agent._scope_sweep_reap`. This module holds the
constants and dataclasses those stages share. Names are public (no leading
underscore) so the stages can import them without crossing the private-import
boundary; the modules themselves stay private so only the
:mod:`sase.agent.scope_sweep` facade is public.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Unit prefix for agent runner scopes (see ``agent/launch_spawn.py``).
AGENT_SCOPE_UNIT_PREFIX = "sase-agent"
#: Runner script basename identifying the live runner process.
RUNNER_SCRIPT_NAME = "run_agent_runner.py"

#: Default spare patterns (matched with ``re.search`` against comm or argv).
DEFAULT_SPARE_PROCESS_PATTERNS: tuple[str, ...] = (
    "^ssh-agent$",
    "^gpg-agent$",
    "^tmux: server$",
    r"^ssh: .*\[mux\]$",
)


@dataclass(frozen=True)
class ScopeMember:
    """One live process found in a scope's ``cgroup.procs``."""

    pid: int
    ppid: int
    comm: str
    argv: tuple[str, ...]
    identity: str


@dataclass(frozen=True)
class ScopeSweepPlan:
    """Pure selection result: what a sweep would signal."""

    targets: tuple[ScopeMember, ...]
    spared: tuple[ScopeMember, ...]
    protected: tuple[ScopeMember, ...]
    spare_patterns: tuple[str, ...] = ()
    protect_root_pid: int | None = None


@dataclass(frozen=True)
class ScopeSweepResult:
    """Outcome of :func:`sase.agent._scope_sweep_core.execute_scope_sweep`."""

    unit: str
    terminated: tuple[ScopeMember, ...]
    survivors: tuple[ScopeMember, ...]
    rounds: int


@dataclass(frozen=True)
class AgentScope:
    """One ``sase-agent-*.scope`` directory found under the user manager."""

    unit: str
    path: Path
    created_ns: int | None


@dataclass(frozen=True)
class ReapedScope:
    """Per-scope detail recorded for a reapable orphaned scope."""

    unit: str
    agent_name: str | None
    targets: int
    terminated: int
    entries: tuple[str, ...]


@dataclass(frozen=True)
class ReapResult:
    """Outcome of :func:`sase.agent._scope_sweep_reap.reap_orphaned_agent_scopes`."""

    scanned: int
    live: int
    skipped_young: int
    empty: int
    spared_only: int
    reaped: tuple[ReapedScope, ...]
    terminated: int
    errors: int
    reason: str | None = None

    @property
    def reaped_scopes(self) -> int:
        """Number of reapable scopes found."""
        return len(self.reaped)


__all__ = [
    "AGENT_SCOPE_UNIT_PREFIX",
    "DEFAULT_SPARE_PROCESS_PATTERNS",
    "RUNNER_SCRIPT_NAME",
    "AgentScope",
    "ReapResult",
    "ReapedScope",
    "ScopeMember",
    "ScopeSweepPlan",
    "ScopeSweepResult",
]
