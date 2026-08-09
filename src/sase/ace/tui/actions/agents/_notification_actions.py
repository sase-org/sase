"""Notification action handlers for the ace TUI app.

Re-exports from split submodules for backwards compatibility.
"""

from ._notification_handlers import (
    handle_jump_to_agent as handle_jump_to_agent,
    handle_jump_to_patch as handle_jump_to_patch,
    handle_jump_to_mentor_review as handle_jump_to_mentor_review,
    handle_memory_review as handle_memory_review,
    handle_tmux as handle_tmux,
    handle_view_error_report as handle_view_error_report,
    handle_view_report as handle_view_report,
)
from ._notification_modals import (
    handle_custom_gate as handle_custom_gate,
    handle_hitl as handle_hitl,
    handle_launch_approval as handle_launch_approval,
    handle_plan_approval as handle_plan_approval,
    handle_user_question as handle_user_question,
    open_user_question_modal_from_marker as open_user_question_modal_from_marker,
    persist_plan_approved as persist_plan_approved,
)
from ._notification_navigation import (
    find_agent_for_notification as find_agent_for_notification,
    get_meta_changespec_name as get_meta_changespec_name,
    get_meta_patch_name as get_meta_patch_name,
    navigate_to_agent_tab as navigate_to_agent_tab,
    navigate_to_patch_tab as navigate_to_patch_tab,
)

__all__ = [
    "find_agent_for_notification",
    "get_meta_changespec_name",
    "get_meta_patch_name",
    "handle_hitl",
    "handle_custom_gate",
    "handle_jump_to_agent",
    "handle_jump_to_patch",
    "handle_jump_to_mentor_review",
    "handle_launch_approval",
    "handle_memory_review",
    "handle_plan_approval",
    "handle_tmux",
    "handle_user_question",
    "handle_view_error_report",
    "handle_view_report",
    "navigate_to_agent_tab",
    "navigate_to_patch_tab",
    "open_user_question_modal_from_marker",
    "persist_plan_approved",
]
