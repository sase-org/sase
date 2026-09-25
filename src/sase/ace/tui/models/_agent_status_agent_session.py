"""Compatibility facade for agent-session status helpers.

The implementation is grouped by agent session topology, status policy, and planner
materialization in adjacent modules. This import path remains stable for
callers and tests that historically imported the combined helper module.
"""

from ._agent_status_agent_session_core import (
    PLAN_CHAIN_MEMBER_ROLES,
    stable_agent_session_name,
    append_unique_timestamps,
    child_launch_time,
    children_by_parent_timestamp,
    has_later_agent_session_continuation,
    is_agent_session_child,
    is_main_workflow_agent_step,
    is_root_plan_workflow,
    mark_derived_plan_agent_session_roots,
    merge_feedback_plan_paths,
    root_child_suffix,
)
from ._agent_status_agent_session_planner import (
    copy_missing_display_metadata,
    copy_missing_plan_metadata,
    pull_plan_metadata_from_agent_session_members,
)
from ._agent_status_agent_session_policy import (
    APPROVED_PLANNER_ACTIONS,
    PLANNER_AGENT_SESSION_ROLES,
    active_approved_plan_handoff_status,
    approved_followup_planner_status,
    done_handoff_status,
    is_answered_continuation_asker,
    is_answered_root_asker_step,
    is_completed_epic_followup_child,
    is_completed_plan_handoff_child,
)

__all__ = [
    "APPROVED_PLANNER_ACTIONS",
    "PLANNER_AGENT_SESSION_ROLES",
    "PLAN_CHAIN_MEMBER_ROLES",
    "active_approved_plan_handoff_status",
    "stable_agent_session_name",
    "append_unique_timestamps",
    "approved_followup_planner_status",
    "child_launch_time",
    "children_by_parent_timestamp",
    "copy_missing_display_metadata",
    "copy_missing_plan_metadata",
    "done_handoff_status",
    "has_later_agent_session_continuation",
    "is_answered_continuation_asker",
    "is_answered_root_asker_step",
    "is_completed_epic_followup_child",
    "is_completed_plan_handoff_child",
    "is_agent_session_child",
    "is_main_workflow_agent_step",
    "is_root_plan_workflow",
    "mark_derived_plan_agent_session_roots",
    "merge_feedback_plan_paths",
    "pull_plan_metadata_from_agent_session_members",
    "root_child_suffix",
]
