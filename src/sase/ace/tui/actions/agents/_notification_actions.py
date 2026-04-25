"""Notification action handlers for the ace TUI app.

Re-exports from split submodules for backwards compatibility.
"""

from ._notification_handlers import (
    handle_jump_to_agent as handle_jump_to_agent,
    handle_jump_to_changespec as handle_jump_to_changespec,
    handle_jump_to_mentor_review as handle_jump_to_mentor_review,
    handle_tmux as handle_tmux,
    handle_view_error_report as handle_view_error_report,
)
from ._notification_modals import (
    handle_hitl as handle_hitl,
    handle_plan_approval as handle_plan_approval,
    handle_user_question as handle_user_question,
    persist_plan_approved as persist_plan_approved,
)
from ._notification_navigation import (
    find_agent_for_notification as find_agent_for_notification,
    get_meta_changespec_name as get_meta_changespec_name,
    navigate_to_agent_tab as navigate_to_agent_tab,
    navigate_to_changespec_tab as navigate_to_changespec_tab,
)

__all__ = [
    "find_agent_for_notification",
    "get_meta_changespec_name",
    "handle_hitl",
    "handle_jump_to_agent",
    "handle_jump_to_changespec",
    "handle_jump_to_mentor_review",
    "handle_plan_approval",
    "handle_tmux",
    "handle_user_question",
    "handle_view_error_report",
    "navigate_to_agent_tab",
    "navigate_to_changespec_tab",
    "persist_plan_approved",
]
