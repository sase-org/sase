"""Shared type declarations for the agent panel-refresh mixins."""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from ...models.agent_groups import GroupingMode
from ._display_helpers import TabName

if TYPE_CHECKING:
    from rich.text import Text

    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panel_index import AgentPanelIndex
    from ...models.agent_panels import AgentPanelGroup, PanelKey
    from ...widgets import AgentList
    from ..navigation.jump_hints import PanelJumpTarget


class PanelRefreshStateMixin:
    """Runtime state and cross-module contracts for panel refresh helpers."""

    current_idx: int
    current_attempt_number: int | None
    current_tab: TabName
    _agents: list[Agent]
    _fold_counts: dict[str, tuple[int, int]]
    _marked_agents: set[tuple[AgentType, str, str | None]]
    _group_fold_registry: AgentGroupFoldRegistry
    _grouping_mode: GroupingMode
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool
    _collapsed_panel_keys: set[PanelKey]
    _expanded_panel_keys: set[PanelKey]

    def _occupancy_keys_with_rows(self) -> set[PanelKey]:
        """Return occupancy keys that currently have rendered rows."""
        raise NotImplementedError

    def _retire_session_mounted_identities(
        self, identities: Collection[tuple[AgentType, str, str | None]]
    ) -> set[PanelKey]:
        """Retire session-sticky keys whose last identity was explicitly removed."""
        raise NotImplementedError

    def _sorted_widget_panel_keys(
        self,
        occupancy_keys: list[PanelKey],
        *,
        occupancy_with_rows: set[PanelKey],
    ) -> list[PanelKey]:
        """Return occupancy ∪ sticky keys in canonical visual order."""
        raise NotImplementedError

    def _agent_panel_index(self) -> AgentPanelIndex:
        """Return the memoized panel index supplied by the display mixin."""
        raise NotImplementedError

    def _panel_keys_per_agent(self) -> list[PanelKey]:
        """Return the panel key for every agent in display order."""
        raise NotImplementedError

    def _agent_panel_title(
        self,
        key: PanelKey,
        panel_agents: list[Agent],
        *,
        merge_tribe_panels: bool,
        panel_jump_hints: dict[PanelJumpTarget, str] | None = None,
        isolation_restore_marked: bool = False,
        fold_restore_marked_count: int = 0,
    ) -> Text:
        """Build a panel title using the active transient hints."""
        raise NotImplementedError

    @staticmethod
    def _set_agent_panel_title(widget: AgentList, title: Text) -> None:
        """Update a panel widget's border title."""
        raise NotImplementedError

    def _apply_panel_heights(self, container: object, widgets: list[AgentList]) -> None:
        """Apply dynamic heights to the rendered panel widgets."""
        raise NotImplementedError

    def _settle_agent_list_container_width(
        self, container: object, widgets: list[AgentList]
    ) -> None:
        """Size the agent-list column to the painted panels' requested widths."""
        raise NotImplementedError

    def _focus_focused_panel_widget(self) -> None:
        """Transfer Textual focus to the active panel widget."""
        raise NotImplementedError
