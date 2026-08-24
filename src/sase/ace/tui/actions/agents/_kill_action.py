"""Agent kill and cleanup actions for the ace TUI app.

This module remains the compatibility entry point for :class:`AgentKillMixin`.
Implementation lives in focused mixins so each file stays small.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from ._kill_action_flow import AgentKillActionFlowMixin
from ._kill_cleanup_clan import AgentCleanupClanMixin
from ._kill_cleanup_panel import AgentCleanupPanelMixin
from ._kill_cleanup_selection import AgentCleanupSelectionMixin
from ._monitor_stop_flow import MonitorStopActionFlowMixin
from ._proc_shell_dismiss import ProcShellDismissMixin
from sase.project_display_names import humanize_cl_name as humanize_cl_name

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

# Type alias retained for callers that import it from this module.
TabName = Literal["artifacts", "agents", "axe"]


class AgentKillMixin(
    AgentCleanupPanelMixin,
    AgentCleanupClanMixin,
    AgentCleanupSelectionMixin,
    ProcShellDismissMixin,
    MonitorStopActionFlowMixin,
    AgentKillActionFlowMixin,
):
    """Mixin providing agent kill, dismiss, and cleanup-selection actions."""

    current_tab: TabName
    current_idx: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _current_group_key: tuple[str, ...] | None


__all__ = ["AgentKillMixin", "TabName", "humanize_cl_name"]
