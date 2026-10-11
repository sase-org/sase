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

    if getattr(agent, "_archive_read_only", False):
        del stale_threshold_seconds
        retained: list[str] = []
        seen: set[str] = set()
        for info in agent_commit_diffs(agent):
            path = getattr(info, "diff_path", None)
            if path and path not in seen:
                seen.add(path)
                retained.append(path)
        for path in list(agent.all_files or ()):
            if path not in seen:
                seen.add(path)
                retained.append(path)
        if retained:
            file_panel.set_file_list(retained, start_index=0)
            return True
        return False
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
    if agent.is_clan_container or agent.is_named_proc:
        file_panel.show_empty()
        return False
    if agent.is_workflow_child and agent.step_type in ("bash", "python"):
        file_panel.show_empty()
        return False
    loaded = _dispatch_file_view(
        file_panel, agent, stale_threshold_seconds=stale_threshold_seconds
    )
    if not loaded:
        if getattr(agent, "_archive_read_only", False):
            from ..models.agent_archive_reader import (
                ARCHIVE_MISSING_FILES,
                titled_archive_card,
            )

            updater = getattr(file_panel, "_update_body", None) or getattr(
                file_panel, "update", None
            )
            if callable(updater):
                try:
                    updater(titled_archive_card(ARCHIVE_MISSING_FILES))
                    return False
                except Exception:
                    pass
        file_panel.show_empty()
    return loaded
