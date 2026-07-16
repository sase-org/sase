"""Core agent display and interaction methods for the ace TUI app."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ._approve import AgentApproveMixin
from ._changespec_navigation import AgentChangespecNavigationMixin
from ._display import AgentDisplayMixin
from ._filter_actions import AgentFilterActionsMixin
from ._fold_persistence import AgentFoldPersistenceMixin
from ._folding import AgentFoldingMixin
from ._grouping import AgentGroupingMixin
from ._kill_action import AgentKillMixin
from ._killing import AgentKillingMixin
from ._loading import AgentLoadingMixin
from ._marking import AgentMarkingMixin
from ._navigation_order import AgentNavigationOrderMixin
from ._notifications import AgentNotificationMixin
from ._panels import AgentPanelsMixin
from ._panel_hint_folding import AgentPanelHintFoldingMixin
from ._revert import AgentRevertMixin
from ._revive import AgentRevivalMixin
from ._selection import AgentSelectionMixin
from ._tagging import AgentTaggingMixin
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

# Import ChangeSpec unconditionally since it's used as a type annotation
# in attribute declarations (not just in function signatures)
from ....changespec import ChangeSpec

# Re-export constants for backwards compatibility (imported by other modules)
from ._loading import DISMISSABLE_STATUSES

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]


class AgentsMixinCore(
    AgentApproveMixin,
    AgentFoldPersistenceMixin,
    AgentPanelHintFoldingMixin,
    AgentFoldingMixin,
    AgentGroupingMixin,
    AgentKillMixin,
    AgentMarkingMixin,
    AgentTaggingMixin,
    AgentWaitResumeMixin,
    AgentPanelsMixin,
    AgentWorkflowHITLMixin,
    AgentNavigationOrderMixin,
    AgentSelectionMixin,
    AgentUnreadMixin,
    AgentChangespecNavigationMixin,
    AgentFilterActionsMixin,
    AgentNotificationMixin,
    AgentKillingMixin,
    AgentRevertMixin,
    AgentRevivalMixin,
    AgentLoadingMixin,
    AgentDisplayMixin,
):
    """Core mixin providing agent loading, display, and user interaction methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    # ChangeSpec state
    changespecs: list[ChangeSpec]
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

    # Group fold + tag-driven panel collection (see startup.py for full
    # documentation).
    _group_fold_registry: AgentGroupFoldRegistry
    _current_group_key: tuple[str, ...] | None
    _panel_group: AgentPanelGroup
    _agent_panels_grouped: bool

    # Agent completion tracking for notifications
    _pending_attention_count: int
    _last_unread_ids: set[str]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agent_objects: list[Agent]
    _recent_dismissed_agent_groups: list[SavedAgentGroupWire]
    _marked_agents: set[tuple[AgentType, str, str | None]]

    # Agent status override system (for PLAN/PLAN APPROVED/QUESTION statuses)
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]
    _dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]]
    _kill_persistence_inflight: set[tuple[AgentType, str, str | None]]

    # Agent search/filter query
    _agent_search_query: str

    # Debouncer for j/k navigation detail panel updates
    _agent_detail_debouncer: DetailPanelDebouncer

    # Phase 2 j/k caches (initialized in StartupMixin._init_app_state).
    _nav_stops_cache: tuple[Any, ...] | None
