"""Plan and display metadata propagation helpers for family rows."""

from ._agent_status_family_core import (
    child_launch_time,
    is_natively_recognized_plan_root,
    is_plan_chain_family_member,
    is_root_plan_workflow,
)
from .agent import Agent


def copy_missing_plan_metadata(target: Agent, source: Agent) -> None:
    """Backfill associated-plan state without replacing child-owned values."""
    if target.archived_plan_path is None:
        target.archived_plan_path = source.archived_plan_path
    if target.sdd_plan_path is None:
        target.sdd_plan_path = source.sdd_plan_path
    if target.epic_plan_ref is None:
        target.epic_plan_ref = source.epic_plan_ref
    if target.plan_committed is None:
        target.plan_committed = source.plan_committed
    if target.plan_action is None:
        target.plan_action = source.plan_action
    if target.plan_path is None:
        target.plan_path = source.plan_path
    if target.epic_bead_id is None:
        target.epic_bead_id = source.epic_bead_id
    if target.phase_bead_id is None:
        target.phase_bead_id = source.phase_bead_id


def pull_plan_metadata_from_family_members(
    children_by_parent: dict[str, list[Agent]],
    parent_by_suffix: dict[str, Agent],
) -> None:
    """Backfill a derived plan-family root's flavor from its planner member.

    Native plan-chain roots keep their pre-existing metadata untouched. Their
    artifact directory is the planner's own, so pulling member metadata onto
    them is unnecessary and can alter established question-first behavior.
    ``plan_times`` is deliberately not propagated because borrowed timestamps
    would change the logical planner child's status.
    """
    for parent_timestamp, children in children_by_parent.items():
        parent = parent_by_suffix.get(parent_timestamp)
        if (
            parent is None
            or not is_root_plan_workflow(parent)
            or is_natively_recognized_plan_root(parent)
        ):
            continue
        members = sorted(
            (child for child in children if is_plan_chain_family_member(child)),
            key=child_launch_time,
            reverse=True,
        )
        for member in members:
            copy_missing_plan_metadata(parent, member)


def copy_missing_display_metadata(parent: Agent, child: Agent) -> None:
    """Backfill root display/runtime metadata from a mirrored child."""
    if parent.model is None and child.model is not None:
        parent.model = child.model
    if parent.llm_provider is None and child.llm_provider is not None:
        parent.llm_provider = child.llm_provider
    if parent.vcs_provider is None and child.vcs_provider is not None:
        parent.vcs_provider = child.vcs_provider
    if parent.workspace_num is None and child.workspace_num is not None:
        parent.workspace_num = child.workspace_num
    if parent.workspace_dir is None and child.workspace_dir is not None:
        parent.workspace_dir = child.workspace_dir
    if parent.status_bucket is None and child.status_bucket is not None:
        parent.status_bucket = child.status_bucket
    if child.is_monitor:
        if parent.monitor_start_status is None:
            parent.monitor_start_status = child.monitor_start_status
        if parent.monitor_stop_status is None:
            parent.monitor_stop_status = child.monitor_stop_status
        if parent.monitor_state is None:
            parent.monitor_state = child.monitor_state
    if child.is_gate:
        if parent.gate_start_status is None:
            parent.gate_start_status = child.gate_start_status
        if parent.gate_stop_status is None:
            parent.gate_stop_status = child.gate_stop_status
        if parent.gate_state is None:
            parent.gate_state = child.gate_state
        if parent.gate_accent is None:
            parent.gate_accent = child.gate_accent
    copy_missing_plan_metadata(parent, child)
