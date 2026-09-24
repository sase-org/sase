"""Legacy Files dispatch shared by the flag-off tree and deck panels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._agent_detail_helpers import _ACTIVE_STATUSES

if TYPE_CHECKING:
    from ..models.agent import Agent
    from .file_panel import AgentFilePanel


def _dispatch_file_view(
    file_panel: AgentFilePanel,
    agent: Agent,
    *,
    stale_threshold_seconds: int = 10,
) -> bool:
    """Run the legacy Files branch; return False when there is no content."""
    from .prompt_panel._agent_commits import agent_commit_diffs

    if agent.status in _ACTIVE_STATUSES:
        file_panel.update_display(
            agent, stale_threshold_seconds=stale_threshold_seconds
        )
        return True
    if agent_commit_diffs(agent):
        file_panel.update_display(
            agent, stale_threshold_seconds=stale_threshold_seconds
        )
        return True
    if files := agent.all_files:
        file_panel.set_file_list(files, start_index=0)
        return True
    if agent.workspace_num is not None and not agent.fleet_origin_alias:
        file_panel.update_display(
            agent, stale_threshold_seconds=stale_threshold_seconds
        )
        return True
    return False


def load_deck_file_view(
    file_panel: AgentFilePanel,
    agent: Agent,
    *,
    attempt_number: int | None,
    stale_threshold_seconds: int = 10,
) -> bool:
    """Load a deck Files view; empty kinds show empty and return False."""
    if attempt_number is not None:
        file_panel.show_empty()
        return False
    if agent.is_clan_container or agent.is_proc_shell:
        file_panel.show_empty()
        return False
    if agent.is_workflow_child and agent.step_type in ("bash", "python"):
        file_panel.show_empty()
        return False
    loaded = _dispatch_file_view(
        file_panel, agent, stale_threshold_seconds=stale_threshold_seconds
    )
    if not loaded:
        file_panel.show_empty()
    return loaded
