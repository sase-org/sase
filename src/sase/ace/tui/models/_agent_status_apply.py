"""Status override orchestration for TUI agents."""

from collections.abc import Callable
from datetime import datetime

from sase.agent.status_buckets import (
    FEEDBACK_STATUS,
    is_pending_plan_review_status,
)
from sase.plan_chain import canonical_plan_chain_suffix

from ._agent_status_diff import classify_diff_badges as classify_persisted_diff_badges
from ._agent_clan import aggregate_clan_status
from ._agent_status_family import (
    active_approved_plan_handoff_status,
    append_unique_timestamps,
    approved_followup_planner_status,
    child_launch_time,
    children_by_parent_timestamp,
    copy_missing_display_metadata,
    copy_missing_plan_metadata,
    done_handoff_status,
    ensure_synthetic_planner_children,
    feedback_child_progressed_past_review,
    has_inherited_family_question,
    has_unanswered_completed_question,
    has_unreviewed_submitted_plan,
    is_answered_continuation_asker,
    is_answered_root_asker_step,
    is_awaiting_plan_review,
    is_completed_epic_followup_child,
    is_completed_plan_handoff_child,
    is_family_child,
    is_main_workflow_agent_step,
    is_root_plan_workflow,
    latest_non_workflow_child_launch_by_parent,
    merge_feedback_plan_paths,
    pending_plan_status_for_agent,
    root_child_suffix,
    superseded_by_feedback_round,
    sync_planner_child_from_parent,
)
from ._agent_status_roles import agent_family_role, is_coder_agent, is_feedback_agent
from .agent import Agent, AgentType
from .agent_family_members import agent_row_is_in_flight


DiffBadgeClassifier = Callable[[list[Agent]], None]


def _mirror_root_from_child(parent: Agent, child: Agent) -> None:
    """Copy the visible root status/metadata from a selected logical child."""
    parent.status = child.status
    copy_missing_display_metadata(parent, child)


def _is_active_root_mirror_candidate(parent: Agent, agent: Agent) -> bool:
    """Return whether *agent* represents active work for root mirroring."""
    if not agent_row_is_in_flight(agent):
        return False
    if (
        agent is not parent
        and agent.raw_suffix is None
        and canonical_plan_chain_suffix(agent.role_suffix) == root_child_suffix(parent)
    ):
        return False
    return True


def apply_status_overrides(
    agents: list[Agent],
    workflow_agent_steps: list[Agent] | None = None,
    *,
    classify_diff_badges: bool = True,
    diff_badge_classifier: DiffBadgeClassifier | None = None,
) -> None:
    """Override statuses based on workflow relationships (mutates in place).

    Agent-family roots act as containers: their visible status mirrors the
    newest planner/feedback/question/code child.  The pass still propagates
    child timestamps, diff paths, and meta_* fields back to the root for the
    detail panel.

    Compatibility behavior for non-family agents remains:
    - DONE -> QUESTION: agent submitted a question that was never answered
    - DONE -> PLAN: agent submitted a plan that was never reviewed
    """
    all_agents = [*agents, *(workflow_agent_steps or [])]
    for agent in all_agents:
        agent.followup_agents.clear()
        agent.wait_display_source = None

    completed_statuses = {"DONE", "FAILED", "FAILED (RETRIED)", "PLAN REJECTED"}

    parent_by_suffix: dict[str, Agent] = {}
    for agent in all_agents:
        if agent.raw_suffix and not agent.is_child_row:
            parent_by_suffix[agent.raw_suffix] = agent

    ensure_synthetic_planner_children(agents, all_agents, parent_by_suffix)
    children_by_parent = children_by_parent_timestamp(all_agents)
    for parent_timestamp, children in children_by_parent.items():
        parent = parent_by_suffix.get(parent_timestamp)
        if parent is None:
            continue
        for child in children:
            copy_missing_plan_metadata(child, parent)
    latest_child_launch_by_parent = latest_non_workflow_child_launch_by_parent(
        children_by_parent
    )

    # Propagate timestamps from feedback round children (.2, .3, ...) to parent
    # so the metadata panel shows one entry per proposal/feedback/question round.
    for agent in all_agents:
        if (
            agent.is_family_member_child
            and agent.parent_timestamp is not None
            and is_feedback_agent(agent)
        ):
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                if agent.plan_times:
                    append_unique_timestamps(parent.plan_times, agent.plan_times)
                if agent.feedback_times:
                    append_unique_timestamps(
                        parent.feedback_times, agent.feedback_times
                    )
                    merge_feedback_plan_paths(parent, agent)
                if agent.questions_times:
                    append_unique_timestamps(
                        parent.questions_times, agent.questions_times
                    )
                if agent.question_request_path:
                    parent.question_request_path = agent.question_request_path
                if agent.question_response_path:
                    parent.question_response_path = agent.question_response_path
                if agent.question_session_id:
                    parent.question_session_id = agent.question_session_id

    # Active workflow step child -> parent is running a step, not planning.
    for agent in all_agents:
        if agent.is_workflow_step_child and agent.parent_timestamp:
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent and agent.status not in completed_statuses:
                if is_pending_plan_review_status(parent.status):
                    parent.status = "RUNNING"

    # Pre-compute which agents have follow-up children so unanswered questions
    # can distinguish "waiting for user" from "answered and continued".
    parents_with_followup: set[str] = set()
    for parent_timestamp, children in children_by_parent.items():
        if any(child.is_family_member_child for child in children):
            parents_with_followup.add(parent_timestamp)

    for agent in all_agents:
        if (
            agent.is_workflow_step_child
            and agent.parent_timestamp
            and is_main_workflow_agent_step(agent)
        ):
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if (
                parent
                and is_root_plan_workflow(parent)
                and canonical_plan_chain_suffix(agent.role_suffix)
                == root_child_suffix(parent)
            ):
                sync_planner_child_from_parent(
                    parent, agent, all_agents, children_by_parent
                )
            elif parent is None:
                approved_status = approved_followup_planner_status(agent)
                if approved_status is not None:
                    agent.status = approved_status
        elif (
            agent.is_family_member_child
            and agent.raw_suffix is None
            and agent.parent_timestamp
        ):
            # Synthetic planner rows survive repeated in-memory normalization.
            # Refresh them from the root just like concrete main-agent steps so
            # newly reloaded durable metadata can advance their semantic state.
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if (
                parent
                and is_root_plan_workflow(parent)
                and canonical_plan_chain_suffix(agent.role_suffix)
                == root_child_suffix(parent)
            ):
                sync_planner_child_from_parent(
                    parent, agent, all_agents, children_by_parent
                )
        elif (
            not agent.agent_family_parallel
            and is_feedback_agent(agent)
            and agent.status in {"DONE", "RUNNING"}
            and is_awaiting_plan_review(agent)
        ):
            agent.status = (
                "DONE"
                if feedback_child_progressed_past_review(
                    agent,
                    all_agents,
                    children_by_parent,
                    latest_child_launch_by_parent,
                )
                else pending_plan_status_for_agent(agent)
            )

    for agent in all_agents:
        if agent.is_family_member_child and agent.parent_timestamp is not None:
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                role = agent_family_role(agent)
                approved_status = (
                    approved_followup_planner_status(agent)
                    if agent.status == "DONE" and is_root_plan_workflow(parent)
                    else None
                )
                if approved_status is not None:
                    agent.status = approved_status
                if has_unanswered_completed_question(
                    agent, parents_with_followup
                ) and not has_inherited_family_question(agent, parent_by_suffix):
                    agent.status = "QUESTION"

                # Propagate meta_* fields from follow-up child to parent
                # so the metadata panel shows dynamic variables (e.g. Commit
                # Message) on the main workflow entry too.
                if agent.step_output and isinstance(agent.step_output, dict):
                    meta_fields = {
                        k: v
                        for k, v in agent.step_output.items()
                        if k.startswith("meta_") and v
                    }
                    if meta_fields:
                        if parent.step_output is None:
                            parent.step_output = {}
                        parent.step_output.update(meta_fields)

                # Propagate code_time from coder follow-up to parent so
                # the metadata panel shows when the coder was launched.
                if is_coder_agent(agent):
                    parent.code_time = agent.run_start_time or agent.start_time
                if role == "epic":
                    parent.epic_time = (
                        agent.epic_time or agent.run_start_time or agent.start_time
                    )

                # Propagate diff_path from follow-up child to parent so the
                # file panel can display the code diff (more relevant than
                # the planner's own diff). Planner rows only fill a missing
                # parent diff; synthetic planner rows copy the parent diff and
                # must not clobber a coder diff propagated earlier in the pass.
                if agent.diff_path and (role != "plan" or not parent.diff_path):
                    parent.diff_path = agent.diff_path

    # Override DONE -> QUESTION for agents whose last question was never answered.
    # A persisted question_response_path means the row resumed after user input;
    # pending_question.json remains the active-row signal before completion.
    for agent in all_agents:
        if has_unanswered_completed_question(
            agent, parents_with_followup
        ) and not has_inherited_family_question(agent, parent_by_suffix):
            agent.status = "QUESTION"

    # A completed question continuation with a persisted response and a newer
    # sibling already handed off to the next continuation.
    for agent in all_agents:
        if is_answered_continuation_asker(
            agent, children_by_parent
        ) or is_answered_root_asker_step(agent, parent_by_suffix, children_by_parent):
            agent.status = "ANSWERED"
            agent.stop_time = max(agent.questions_times)

    # Override DONE -> PLAN for rows whose submitted plan still awaits manual
    # review. This mirrors the QUESTION catch-all and covers planner entries
    # that fall through suffix-gated workflow-step/feedback branches above.
    for agent in all_agents:
        if has_unreviewed_submitted_plan(
            agent,
            all_agents,
            children_by_parent,
            latest_child_launch_by_parent,
        ):
            agent.status = pending_plan_status_for_agent(agent)

    # Active family code handoff rows display the coder-specific working state
    # while the implementation agent runs. Normalize before root mirroring so
    # the family root mirrors WORKING PLAN / WORKING TALE instead of raw RUNNING.
    for agent in all_agents:
        if not agent.is_family_member_child or agent.parent_timestamp is None:
            continue
        parent = parent_by_suffix.get(agent.parent_timestamp)
        if parent and is_root_plan_workflow(parent):
            handoff_status = active_approved_plan_handoff_status(parent, agent)
            if handoff_status:
                agent.status = handoff_status

    # Completed family handoff rows are semantic terminal states rather than
    # plain DONE. Do this after QUESTION normalization so unanswered rows keep
    # their blocked status, and before root mirroring so the root sees it.
    for agent in all_agents:
        if not agent.is_family_member_child or agent.parent_timestamp is None:
            continue
        parent = parent_by_suffix.get(agent.parent_timestamp)
        if not (parent and is_root_plan_workflow(parent)):
            continue
        if is_completed_epic_followup_child(agent):
            agent.status = "EPIC CREATED"
        elif is_completed_plan_handoff_child(agent):
            agent.status = done_handoff_status(parent, agent)

    # Planner rounds superseded by a later planner-family round were resolved
    # by user feedback, not approval. Apply this late so it wins over sticky
    # approved-plan status, but before roots mirror their newest child.
    for agent in all_agents:
        if superseded_by_feedback_round(agent, children_by_parent):
            agent.status = FEEDBACK_STATUS

    # Attach all follow-up agents to their parent's followup_agents list.
    for agent in all_agents:
        if agent.is_family_member_child and agent.parent_timestamp is not None:
            parent = parent_by_suffix.get(agent.parent_timestamp)
            if parent:
                parent.followup_agents.append(agent)

    # Sort follow-up agents chronologically (oldest first).
    for agent in all_agents:
        if agent.followup_agents:
            agent.followup_agents.sort(key=lambda a: a.start_time or datetime.min)

    # Agent-family roots summarize live child activity first. Plan-workflow
    # roots keep the historical newest-child fallback when no child is active
    # or queued; plain-agent roots keep their own terminal status in that case.
    for parent in parent_by_suffix.values():
        if not parent.raw_suffix:
            continue
        children = [
            child
            for child in children_by_parent.get(parent.raw_suffix, [])
            if child is not parent and is_family_child(child, parent)
        ]
        if not children:
            continue

        parallel_members = [child for child in children if child.agent_family_parallel]
        if parallel_members:
            aggregate_status = aggregate_clan_status(
                [parent.status, *(member.status for member in parallel_members)]
            )
            if aggregate_status is not None:
                parent.status = aggregate_status
            if parent.status in {"WAITING", "QUEUED"}:
                waiting_members = [
                    member
                    for member in parallel_members
                    if member.status in {"WAITING", "QUEUED"}
                ]
                if waiting_members:
                    next_waiting = min(waiting_members, key=child_launch_time)
                    parent.wait_display_source = next_waiting
                    copy_missing_display_metadata(parent, next_waiting)
            continue

        # A live outer runner waiting in provider backoff outranks the failed
        # serial child attempt that it is about to retry. Keep the child
        # evidence intact while ensuring repeated normalization (including
        # after an artifact-delta merge) cannot overwrite the root projection.
        if parent.runner_is_live and parent.retry_status == "retrying":
            parent.status = "RETRYING"
            continue

        is_plan_root = is_root_plan_workflow(parent)
        candidates = list(children)
        if not is_plan_root and parent.agent_type == AgentType.RUNNING:
            candidates.append(parent)

        active = [
            agent
            for agent in candidates
            if _is_active_root_mirror_candidate(parent, agent)
        ]
        if active:
            newest_active = max(active, key=child_launch_time)
            if newest_active is not parent:
                _mirror_root_from_child(parent, newest_active)
            continue

        waiting = [
            agent for agent in candidates if agent.status in {"WAITING", "QUEUED"}
        ]
        if waiting:
            next_waiting = min(waiting, key=child_launch_time)
            if next_waiting is not parent:
                parent.status = next_waiting.status
                parent.wait_display_source = next_waiting
                copy_missing_display_metadata(parent, next_waiting)
            continue

        if is_plan_root:
            newest = max(children, key=child_launch_time)
            _mirror_root_from_child(parent, newest)

    # Spawn-on-retry: build the retry-chain linkage. Each retry child has a
    # backward pointer (retry_of_timestamp) to its immediate parent; we
    # reverse-index that into the parent's retry_chain_siblings list so the
    # TUI can render the chain from either direction.
    by_suffix: dict[str, Agent] = {}
    for agent in all_agents:
        if agent.raw_suffix and not agent.is_child_row:
            by_suffix[agent.raw_suffix] = agent
    for agent in all_agents:
        if agent.retry_of_timestamp:
            parent = by_suffix.get(agent.retry_of_timestamp)
            if parent is not None:
                parent.retry_chain_siblings.append(agent)
    for agent in all_agents:
        if agent.retry_chain_siblings:
            agent.retry_chain_siblings.sort(
                key=lambda a: a.retry_attempt or 0,
            )

    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    machine_identity = AgentIdentitySnapshot.current()
    for agent in all_agents:
        agent.refresh_presented_agent_name(machine_identity)

    if classify_diff_badges:
        classifier = diff_badge_classifier or classify_persisted_diff_badges
        classifier(all_agents)
