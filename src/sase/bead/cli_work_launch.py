"""Agent launch routing for ``sase bead work``."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.agent.launch_types import AgentLaunchResult
    from sase.bead.work import VCSLaunchContext


def launch_bead_work_agents(
    query: str,
    *,
    segment_extra_env: tuple[dict[str, str], ...],
    expected_names: set[str],
    launch_context: VCSLaunchContext | None,
) -> list[AgentLaunchResult]:
    """Launch the rendered bead-work multi-prompt.

    When a VCS/Patch launch context was resolved (every segment carries an
    explicit ``#<workflow>:<ref>`` prefix), dispatch through the fast planned
    adapter that skips generic fan-out discovery. Otherwise fall back to the
    generic CWD launcher, which resolves project context from the workspace.
    """
    from sase.agent import launcher as _launcher

    if launch_context is None:
        return [
            _launcher.launch_agent_from_cwd(query, segment_extra_env=segment_extra_env)
        ]
    return _launcher.launch_planned_bead_work_agents(
        segments=query.split("\n---\n"),
        segment_extra_env=segment_extra_env,
        expected_names=expected_names,
        project_name=launch_context.project_name,
    )
