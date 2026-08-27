"""Notification polling and display methods for the ace TUI app.

This module is the compatibility entry point for notification behavior. The
implementation lives in smaller focused mixins nearby.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._notification_deadlines import AgentNotificationDeadlineMixin
from ._notification_modal_flow import AgentNotificationModalMixin
from ._notification_polling import AgentNotificationPollingMixin
from ._notification_provider import AgentNotificationProviderMixin
from ._notification_plan_reconciliation import AgentNotificationPlanReconciliationMixin
from ._notification_unread_projection import AgentNotificationUnreadMixin
from ._notification_utils import (
    TabName,
    active_completion_agent_keys as _active_completion_agent_keys,
    unread_notification_buckets as _unread_notification_buckets,
)

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType
    from ._types import PlanFeedbackContext


class AgentNotificationMixin(
    AgentNotificationProviderMixin,
    AgentNotificationUnreadMixin,
    AgentNotificationPlanReconciliationMixin,
    AgentNotificationPollingMixin,
    AgentNotificationDeadlineMixin,
    AgentNotificationModalMixin,
):
    """Mixin providing notification polling and display methods.

    Type hints below declare attributes that are defined at runtime by AceApp.
    """

    _last_unread_ids: set[str]
    _delivered_notification_activity_cursors: set[tuple[str, str]]
    current_idx: int
    current_tab: TabName
    hide_non_run_agents: bool
    _agents: list[Agent]
    _hidden_count: int
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _plan_feedback_context: PlanFeedbackContext | None
    _agent_info_metrics_cache: tuple[Any, ...] | None


__all__ = [
    "AgentNotificationMixin",
    "TabName",
    "_active_completion_agent_keys",
    "_unread_notification_buckets",
]
