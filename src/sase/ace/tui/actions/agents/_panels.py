"""Agent detail panel viewing, navigation, and tmux actions for the ace TUI app."""

from __future__ import annotations

import signal
from collections.abc import Callable
from types import FrameType
from typing import TYPE_CHECKING, Any

from ._panel_artifact_files import AgentPanelArtifactFileMixin
from ._panel_detail import AgentPanelDetailMixin
from ._panel_navigation import AgentPanelNavigationMixin
from ._panel_tmux import AgentPanelTmuxMixin
from ._panel_types import TabName

if TYPE_CHECKING:
    from ...graphics import TmuxPaneDecorationState
    from ...models import Agent
    from ...models.agent_panels import AgentPanelGroup


class AgentPanelsMixin(
    AgentPanelArtifactFileMixin,
    AgentPanelNavigationMixin,
    AgentPanelDetailMixin,
    AgentPanelTmuxMixin,
):
    """Mixin providing agent detail panel viewing, navigation, and tmux actions.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    current_tab: TabName
    current_idx: int
    current_attempt_number: int | None
    _panel_group: AgentPanelGroup
    _current_group_key: tuple[str, ...] | None
    _agent_panels_grouped: bool
    _agents: list[Agent]
    _artifact_file_tmux_pane_id: str | None
    _artifact_file_tmux_decoration_state: TmuxPaneDecorationState | None
    _artifact_file_viewer_previous_sigusr1_handler: (
        signal.Handlers | int | Callable[[int, FrameType | None], Any] | None
    )
