"""Workflow relationship status overrides for TUI agents.

This module is a compatibility facade. The implementation is split across
adjacent ``_agent_status_*`` modules to keep each file small while preserving
the historical import path used by callers and tests.
"""

from ._agent_status_apply import apply_status_overrides as run_status_overrides
from ._agent_status_diff import (
    classify_diff_badges as _classify_diff_badges,
    classify_live_file_change_hint,
)
from ._agent_status_family import (
    APPROVED_PLAN_ACTIONS as _APPROVED_PLAN_ACTIONS,
    active_approved_plan_handoff_status as _active_approved_plan_handoff_status,
    agent_family_name as _agent_family_name,
    append_unique_timestamps as _append_unique_timestamps,
    child_launch_time as _child_launch_time,
    children_by_parent_timestamp as _children_by_parent_timestamp,
    copy_missing_display_metadata as _copy_missing_display_metadata,
    done_handoff_status as _done_handoff_status,
    ensure_synthetic_planner_children as _ensure_synthetic_planner_children,
    feedback_child_progressed_past_review as _feedback_child_progressed_past_review,
    has_family_followup_child as _has_family_followup_child,
    has_inherited_family_question as _has_inherited_family_question,
    has_unanswered_completed_question as _has_unanswered_completed_question,
    has_unreviewed_submitted_plan as _has_unreviewed_submitted_plan,
    is_awaiting_plan_review as _is_awaiting_plan_review,
    is_completed_epic_followup_child as _is_completed_epic_followup_child,
    is_completed_plan_handoff_child as _is_completed_plan_handoff_child,
    is_family_child as _is_family_child,
    is_main_workflow_agent_step as _is_main_workflow_agent_step,
    latest_non_workflow_child_launch_by_parent as _latest_non_workflow_child_launch_by_parent,
    merge_feedback_plan_paths as _merge_feedback_plan_paths,
    planner_child_status as _planner_child_status,
    root_child_suffix as _root_child_suffix,
    sync_planner_child_from_parent as _sync_planner_child_from_parent,
    is_root_plan_workflow,
)
from ._agent_status_roles import (
    agent_family_role as _agent_family_role,
    is_coder_agent as _is_coder_agent,
    is_coder_followup_suffix,
    is_feedback_agent as _is_feedback_agent,
    is_feedback_suffix,
)
from .agent import Agent


def apply_status_overrides(
    agents: list[Agent],
    workflow_agent_steps: list[Agent] | None = None,
    *,
    classify_diff_badges: bool = True,
) -> None:
    """Override statuses based on workflow relationships (mutates in place)."""
    run_status_overrides(
        agents,
        workflow_agent_steps,
        classify_diff_badges=classify_diff_badges,
        diff_badge_classifier=_classify_diff_badges,
    )
