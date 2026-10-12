"""Core agent display and interaction methods for sase's TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ._agent_enter_action import AgentEnterActionMixin
from ._approve import AgentApproveMixin
from ._patch_navigation import AgentPatchNavigationMixin
from ._display import AgentDisplayMixin
from ._filter_actions import AgentFilterActionsMixin
from ._filter_bar_session import AgentsFilterBarSessionMixin
from ._deck_persistence import AgentDeckPersistenceMixin
from ._fold_persistence import AgentFoldPersistenceMixin
from ._folding import AgentFoldingMixin
from ._fleet import AgentFleetMixin
from ._grouping import AgentGroupingMixin
from ._kill_action import AgentKillMixin
from ._remote_attention import RemoteAttentionMixin
from ._remote_content import AgentRemoteContentMixin
from ._remote_lifecycle import AgentRemoteLifecycleMixin
from ._removal_tombstones import AgentRemovalTombstonesMixin
from ._killing import AgentKillingMixin
from ._loading import AgentLoadingMixin
from ._marking import AgentMarkingMixin
from ._metadata_pager import AgentMetadataPagerMixin
from ._metadata_search import AgentMetadataSearchMixin
from ._navigation_order import AgentNavigationOrderMixin
from ._notifications import AgentNotificationMixin
from ._panels import AgentPanelsMixin
from ._panel_hint_folding import AgentPanelHintFoldingMixin
from ._query_persistence import AgentQueryPersistenceMixin
from ._revert import AgentRevertMixin
from ._revive import AgentRevivalMixin
from ._tool_run_actions import ToolRunActionsMixin
from ._selection import AgentSelectionMixin
from ._agent_tab_jump import AgentTabJumpMixin
from ._agent_tabs import AgentTabsMixin
from ._tab_scope import AgentTabScopeMixin
from ._tribe_assignment import AgentTribeAssignmentMixin
from ._unread import AgentUnreadMixin
from ._wait_resume import AgentWaitResumeMixin
from ._workflow_hitl import AgentWorkflowHITLMixin
from ...models.agent_status import (
    is_stopped_agent_status,
    is_unread_completed_status,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_panels import AgentPanelGroup
    from ...models.fold_state import FoldStateManager
    from ...util.debounce import DetailPanelDebouncer
    from sase.core.agent_group_archive_wire import SavedAgentGroupWire

# Import Patch unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....patch import Patch

# Re-export constants for backwards compatibility (imported by other modules)
from ._loading import DISMISSABLE_STATUSES

# Type alias for tab names
TabName = Literal["artifacts", "agents", "services"]


class _AgentArchiveColumnMixin:
    """Textual message handlers for the Archive column widgets.

    Handlers defer to the column code so the Inbox-only startup path never
    imports it. Cheap Inbox probes live in ``_display_helpers``.
    """

    def on_archive_list_cursor_moved(self, event: Any) -> None:
        from ._archive_column_nav import archive_cursor_from_widget

        archive_cursor_from_widget(self, event.key)

    def on_archive_list_item_activated(self, event: Any) -> None:
        from ._archive_column_nav import archive_activate_key

        archive_activate_key(self, event.key)

    def on_archive_pulse_activated(self, event: Any) -> None:
        from ._archive_column_nav import archive_activate_pulse

        archive_activate_pulse(self)

    def _activate_agents_archive_shelf(self) -> None:
        from ._archive_shelf import activate_archive_shelf

        activate_archive_shelf(self)

    def action_open_agents_archive(self) -> None:
        """Open Agents Archive, switching to Agents when needed."""
        from ...models.agent_archive_view import agents_archive_view_enabled
        from ._archive_view import open_agents_archive_view
        from ._display_helpers import agents_archive_is_active

        if not agents_archive_view_enabled():
            return
        opening = not agents_archive_is_active(self)
        capture = getattr(self, "_current_link_trail_origin", None)
        origin = capture() if opening and callable(capture) else None
        if getattr(self, "current_tab", None) != "agents":
            save_position = getattr(self, "_save_current_tab_position", None)
            if callable(save_position):
                save_position()
            switch = getattr(self, "_switch_to_tab", None)
            if callable(switch):
                switch("agents")
        open_agents_archive_view(self)
        if opening:
            record = getattr(self, "_record_link_trail", None)
            if origin is not None and callable(record):
                record(origin)
            notify = getattr(self, "notify", None)
            if callable(notify):
                notify(
                    "Opened the Archive — dismissed runs open read-only · ctrl+o back",
                    severity="information",
                )

    def action_back_to_agents_inbox(self) -> None:
        """Return from Archive to the parked Inbox."""
        from ._archive_view import close_agents_archive_view
        from ._display_helpers import agents_archive_is_active

        if agents_archive_is_active(self):
            if getattr(self, "current_tab", None) != "agents":
                save_position = getattr(self, "_save_current_tab_position", None)
                if callable(save_position):
                    save_position()
                switch = getattr(self, "_switch_to_tab", None)
                if callable(switch):
                    switch("agents")
            close_agents_archive_view(self)

    def action_toggle_agents_archive(self) -> None:
        """Open Archive from another tab, or toggle the Agents view in place."""
        from ...models.agent_archive_view import agents_archive_view_enabled
        from ._archive_view import close_agents_archive_view, open_agents_archive_view
        from ._display_helpers import agents_archive_is_active

        if not agents_archive_view_enabled():
            return
        if getattr(self, "current_tab", None) != "agents":
            self.action_open_agents_archive()
        elif agents_archive_is_active(self):
            close_agents_archive_view(self)
        else:
            open_agents_archive_view(self)


class AgentsMixinCore(
    _AgentArchiveColumnMixin,
    AgentMetadataPagerMixin,
    AgentMetadataSearchMixin,
    AgentApproveMixin,
    AgentDeckPersistenceMixin,
    AgentFoldPersistenceMixin,
    AgentPanelHintFoldingMixin,
    AgentFoldingMixin,
    AgentGroupingMixin,
    AgentRemovalTombstonesMixin,
    AgentFleetMixin,
    AgentRemoteLifecycleMixin,
    RemoteAttentionMixin,
    AgentRemoteContentMixin,
    AgentKillMixin,
    AgentMarkingMixin,
    AgentTribeAssignmentMixin,
    AgentWaitResumeMixin,
    AgentPanelsMixin,
    AgentWorkflowHITLMixin,
    AgentNavigationOrderMixin,
    AgentSelectionMixin,
    AgentTabScopeMixin,
    AgentTabsMixin,
    AgentTabJumpMixin,
    AgentUnreadMixin,
    AgentEnterActionMixin,
    AgentPatchNavigationMixin,
    AgentQueryPersistenceMixin,
    AgentFilterActionsMixin,
    AgentsFilterBarSessionMixin,
    AgentNotificationMixin,
    AgentKillingMixin,
    AgentRevertMixin,
    AgentRevivalMixin,
    ToolRunActionsMixin,
    AgentLoadingMixin,
    AgentDisplayMixin,
):
    """Core mixin providing agent loading, display, and user interaction methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # Patch state
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    refresh_interval: int
    hide_non_run_agents: bool
    _countdown_remaining: int
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _agents_last_idx: int
    _has_always_visible: bool
    _hidden_count: int

    # Fold state for workflow steps
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]

    # Group fold + tribe-driven panel collection (see startup.py for full
    # documentation).
    _group_fold_registry: AgentGroupFoldRegistry
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool

    # Agent completion tracking for notifications
    _pending_attention_count: int
    _last_unread_ids: set[str]
    _delivered_notification_activity_cursors: set[tuple[str, str]]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _pending_bulk_read_agent_ids: set[tuple[AgentType, str, str | None]] | None
    _pending_bulk_read_armed_at: float | None
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _recent_dismissed_agent_groups: list[SavedAgentGroupWire]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    # Transient status overrides for optimistic response state.
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
    _kill_persistence_inflight: set[tuple[AgentType, str, str | None]]

    # Agent search/filter query
    _agent_search_query: str
    _agent_search_query_seeded: bool
    _agent_search_query_seed_attempted: bool
    _agent_search_query_generation: int

    # Auto-hiding FilterBar editing session (sase-zf.4). See
    # ``AgentsFilterBarSessionMixin`` for the full state machine.
    _agents_filter_session_open: bool
    _agents_live_preview_query: str
    _agents_filter_query_error: str | None
    _agents_filter_match_count: tuple[int, int] | None
    _agents_committed_match_count: tuple[int, int] | None

    # Debouncer for j/k navigation detail panel updates
    _agent_detail_debouncer: DetailPanelDebouncer

    # Phase 2 j/k caches (initialized in StartupMixin._init_app_state).
    _nav_stops_cache: tuple[Any, ...] | None
