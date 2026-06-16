"""High-level launch entry points that resolve context from the current CWD."""

from __future__ import annotations

from collections.abc import Sequence

from sase.agent.launch_cwd_agents import launch_agents_from_cwd_impl
from sase.agent.launch_cwd_bead_work import launch_planned_bead_work_agents
from sase.agent.launch_cwd_common import resolve_known_project_vcs_launch_ref
from sase.agent.launch_types import AgentLaunchResult

__all__ = [
    "launch_agent_from_cwd",
    "launch_agents_from_cwd",
    "launch_planned_bead_work_agents",
    "resolve_known_project_vcs_launch_ref",
]


def launch_agents_from_cwd(
    query: str,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    timestamp: str | None = None,
) -> list[AgentLaunchResult]:
    """Resolve project context from CWD and launch background agents."""
    return launch_agents_from_cwd_impl(
        query,
        extra_env=extra_env,
        segment_extra_env=segment_extra_env,
        timestamp=timestamp,
        recursive_launch_agents_from_cwd=launch_agents_from_cwd,
    )


def launch_agent_from_cwd(
    query: str,
    extra_env: dict[str, str] | None = None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
    timestamp: str | None = None,
) -> AgentLaunchResult:
    """Resolve project context from CWD and launch a background agent.

    This compatibility wrapper keeps the historical API returning the first
    launch result while ``launch_agents_from_cwd()`` exposes full fan-out.
    """
    results = launch_agents_from_cwd(
        query,
        extra_env=extra_env,
        segment_extra_env=segment_extra_env,
        timestamp=timestamp,
    )
    if not results:
        raise RuntimeError("agent launch produced no results")
    return results[0]
