"""Compatibility facade for agent-family status helpers.

The implementation is grouped by family topology, status policy, and planner
materialization in adjacent modules. This import path remains stable for
callers and tests that historically imported the combined helper module.
"""

from ._agent_status_family_core import (
    PLAN_CHAIN_MEMBER_ROLES,
    agent_family_name,
    append_unique_timestamps,
    child_launch_time,
    children_by_parent_timestamp,
    has_later_family_continuation,
    is_family_child,
    is_main_workflow_agent_step,
    is_root_plan_workflow,
    mark_derived_plan_family_roots,
    merge_feedback_plan_paths,
    root_child_suffix,
)
from ._agent_status_family_planner import (
    copy_missing_display_metadata,
    copy_missing_plan_metadata,
    pull_plan_metadata_from_family_members,
)
from ._agent_status_family_policy import (
    APPROVED_PLANNER_ACTIONS,
    PLANNER_FAMILY_ROLES,
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
    "PLANNER_FAMILY_ROLES",
    "PLAN_CHAIN_MEMBER_ROLES",
    "active_approved_plan_handoff_status",
    "agent_family_name",
    "append_unique_timestamps",
    "approved_followup_planner_status",
    "child_launch_time",
    "children_by_parent_timestamp",
    "copy_missing_display_metadata",
    "copy_missing_plan_metadata",
    "done_handoff_status",
    "has_later_family_continuation",
    "is_answered_continuation_asker",
    "is_answered_root_asker_step",
    "is_completed_epic_followup_child",
    "is_completed_plan_handoff_child",
    "is_family_child",
    "is_main_workflow_agent_step",
    "is_root_plan_workflow",
    "mark_derived_plan_family_roots",
    "merge_feedback_plan_paths",
    "pull_plan_metadata_from_family_members",
    "root_child_suffix",
]
