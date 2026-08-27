"""Snapshot/wire-backed agent metadata enrichment."""

from __future__ import annotations

from sase.core.agent_scan_wire import (
    AgentMetaWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.core.output_variable_values import coerce_var_map
from sase.core.runner_slots import DEFAULT_WAIT_PRIORITY
from sase.gate_shell.state import is_real_gate_member
from sase.monitor_state import is_monitor_member_role
from sase.sdd.plan_tiers import cached_plan_tier

from ._meta_enrichment_common import (
    ACTIVE_ENRICHMENT_STATUSES,
    apply_gate_meta,
    apply_monitor_meta,
    apply_workflow_child_identity_from_meta_wire,
    append_timestamp_values,
    is_main_workflow_agent_step,
    parent_timestamp_from_meta,
    parse_utc_to_local,
    parse_linked_repos,
    pending_question_status_for_request_path,
    plan_enrichment_status,
    refresh_agent_plan_path,
    wire_meta_has_wait_directive,
)
from ..agent import Agent


def enrich_agent_from_meta_wire(
    agent: Agent,
    meta: AgentMetaWire | None,
    waiting: WaitingMarkerWire | None,
    pending_question: PendingQuestionMarkerWire | None = None,
    *,
    plan_path_marker: str | None = None,
    workflow_child: bool = False,
) -> None:
    """Snapshot-aware mirror of :func:`enrich_agent_from_meta`.

    Mirrors every field assignment performed by the filesystem-backed
    helper so callers using a snapshot get identical Agent state. When
    *meta* is ``None`` the function is a no-op (matching the original's
    early-return when ``agent_meta.json`` is missing or unreadable).
    """
    if plan_path_marker:
        agent.archived_plan_path = plan_path_marker
        agent.plan_path = plan_path_marker

    if meta is None:
        refresh_agent_plan_path(agent)
        agent.refresh_raw_presented_agent_name()
        return

    agent.runner_slot_yielded = pending_question is not None

    if meta.status_bucket:
        agent.status_bucket = meta.status_bucket
    if meta.model:
        agent.model = meta.model
    if meta.llm_provider:
        agent.llm_provider = meta.llm_provider
    if meta.reasoning_effort:
        agent.reasoning_effort = meta.reasoning_effort
    if meta.model_alias:
        agent.model_alias = meta.model_alias
    if meta.vcs_provider:
        agent.vcs_provider = meta.vcs_provider
    if meta.workspace_dir:
        agent.workspace_dir = meta.workspace_dir
    if meta.plan_path:
        agent.archived_plan_path = meta.plan_path
    if meta.sdd_plan_path:
        agent.sdd_plan_path = meta.sdd_plan_path
    if meta.epic_plan_ref:
        agent.epic_plan_ref = meta.epic_plan_ref
    if meta.epic_bead_id:
        agent.epic_bead_id = meta.epic_bead_id
    if meta.phase_bead_id:
        agent.phase_bead_id = meta.phase_bead_id
    if agent.record_shape != "list":
        agent.linked_repos = parse_linked_repos(meta.linked_repos)
    if not agent.diff_path and meta.commit_diff_path:
        agent.diff_path = meta.commit_diff_path
    if not workflow_child and meta.name:
        agent.agent_name = meta.name
    if meta.tribe:
        agent.tribe = meta.tribe
    agent.output_variables = coerce_var_map(meta.output_variables)
    if meta.wait_for:
        agent.waiting_for = list(meta.wait_for)
    if meta.wait_for_beads:
        agent.waiting_for_beads = list(meta.wait_for_beads)
    auto_action = meta.auto_approve_plan_action or None
    meta_auto_approved = agent.approve or bool(meta.approve) or bool(auto_action)
    apply_meta_approve = not workflow_child or is_main_workflow_agent_step(agent)
    if apply_meta_approve and auto_action:
        agent.auto_approve_plan_action = auto_action
        agent.approve = True
    if meta.plan_action:
        agent.plan_action = meta.plan_action
    if meta.plan_committed is not None:
        agent.plan_committed = meta.plan_committed
    refresh_agent_plan_path(agent)
    if apply_meta_approve and meta.approve:
        agent.approve = True
    if meta.hidden:
        agent.hidden = True
    if not workflow_child and meta.role_suffix:
        agent.role_suffix = meta.role_suffix
    if not workflow_child:
        if meta.agent_family:
            agent.agent_family = meta.agent_family
        if meta.agent_family_role:
            agent.agent_family_role = meta.agent_family_role
        if meta.agent_clan:
            agent.agent_clan = meta.agent_clan
        if meta.agent_clan_generation:
            agent.agent_clan_generation = meta.agent_clan_generation
        if meta.clan_tribe:
            agent.clan_tribe = meta.clan_tribe
        if meta.clan_summary:
            agent.clan_summary = meta.clan_summary
        agent.agent_family_parallel = meta.agent_family_parallel
    if not workflow_child and meta.plan_chain_root:
        agent.plan_chain_root = True
    if workflow_child:
        apply_workflow_child_identity_from_meta_wire(agent, meta)
    if agent.parent_timestamp is None:
        parent_timestamp = parent_timestamp_from_meta(
            agent,
            meta.parent_timestamp,
            workflow_child=workflow_child,
        )
        if parent_timestamp is not None:
            agent.parent_timestamp = parent_timestamp
    if meta.workspace_num is not None and agent.workspace_num is None:
        agent.workspace_num = meta.workspace_num

    if meta.retry_of_timestamp:
        agent.retry_of_timestamp = meta.retry_of_timestamp
    if meta.retry_attempt is not None:
        agent.retry_attempt = meta.retry_attempt
    if meta.retry_chain_root_timestamp:
        agent.retry_chain_root_timestamp = meta.retry_chain_root_timestamp
    if meta.retried_as_timestamp:
        agent.retried_as_timestamp = meta.retried_as_timestamp
    if meta.retry_terminal:
        agent.retry_terminal = True
    if meta.retry_error_category:
        agent.retry_error_category = meta.retry_error_category

    append_timestamp_values(meta.plan_submitted_at, agent.plan_times)
    if meta.epic_started_at:
        try:
            agent.epic_time = parse_utc_to_local(meta.epic_started_at)
        except ValueError:
            pass
    feedback_times = append_timestamp_values(
        meta.feedback_submitted_at, agent.feedback_times
    )
    if meta.plan_path:
        for timestamp in feedback_times:
            agent.feedback_plan_paths[timestamp] = meta.plan_path
    append_timestamp_values(meta.questions_submitted_at, agent.questions_times)
    if meta.question_request_path:
        agent.question_request_path = meta.question_request_path
    if meta.question_response_path:
        agent.question_response_path = meta.question_response_path
    if meta.question_session_id:
        agent.question_session_id = meta.question_session_id
    for ts in meta.retry_started_at:
        try:
            agent.retry_times.append(parse_utc_to_local(ts))
        except ValueError:
            continue
    if meta.run_started_at:
        try:
            agent.run_start_time = parse_utc_to_local(meta.run_started_at)
            if agent.status == "STARTING":
                agent.status = "RUNNING"
        except ValueError:
            pass
    elif meta.wait_completed_at and agent.status == "STARTING":
        agent.status = "RUNNING"
    if meta.stopped_at:
        try:
            agent.stop_time = parse_utc_to_local(meta.stopped_at)
        except ValueError:
            pass

    if meta.wait_completed_at or (
        wire_meta_has_wait_directive(meta)
        and (
            agent.run_start_time is not None
            or agent.stop_time is not None
            or agent.status not in ACTIVE_ENRICHMENT_STATUSES
        )
    ):
        agent.wait_start_time = agent.start_time

    # waiting.json overrides active display states and updates wait fields.
    # The filesystem helper only consults waiting.json when agent_meta
    # was successfully read; mirror that gate by handling it after the
    # meta-driven assignments.
    if waiting is not None and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        agent.status = "WAITING"
        agent.wait_start_time = agent.start_time
        if waiting.waiting_for:
            agent.waiting_for = list(waiting.waiting_for)
        if waiting.wait_for_beads:
            agent.waiting_for_beads = list(waiting.wait_for_beads)
        if waiting.wait_duration is not None:
            agent.wait_duration = waiting.wait_duration
        if waiting.wait_until:
            agent.wait_until = waiting.wait_until
        agent.wait_runners = waiting.wait_runners
        agent.wait_runners_explicit = waiting.wait_runners_explicit
        agent.wait_priority = waiting.wait_priority
        agent.wait_priority_explicit = waiting.wait_priority_explicit or (
            waiting.wait_priority is not None
            and waiting.wait_priority != DEFAULT_WAIT_PRIORITY
        )
        agent.slot_requested_at = waiting.slot_requested_at

    if agent.wait_duration is None and meta.wait_duration is not None:
        agent.wait_duration = meta.wait_duration
    if agent.wait_until is None and meta.wait_until:
        agent.wait_until = meta.wait_until
    if (
        agent.wait_priority is None
        and type(meta.wait_priority) is int
        and meta.wait_priority >= 0
    ):
        agent.wait_priority = meta.wait_priority
        agent.wait_priority_explicit = True

    # pending_question.json: marker presence flips active rows to QUESTION, or
    # ANSWERED once the user's question_response.json has landed. A simultaneous
    # waiting marker wins because it means the answered root is queued to
    # reacquire its runner slot before resuming.
    if pending_question is not None and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        agent.status = pending_question_status_for_request_path(
            pending_question.request_path
        )

    if meta.plan and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        plan_submitted = bool(meta.plan_submitted_at)
        plan_status = plan_enrichment_status(
            plan_approved=meta.plan_approved,
            plan_action=meta.plan_action,
            plan_submitted=plan_submitted,
            auto_approved=meta_auto_approved,
            plan_tier=(
                cached_plan_tier(meta.plan_path)
                if plan_submitted and not meta.plan_approved and not meta_auto_approved
                else None
            ),
        )
        if plan_status is not None:
            agent.status = plan_status

    shell = meta.family_shell
    monitor_shell = shell if shell is not None and shell.kind == "monitor" else None
    monitor = monitor_shell.monitor if monitor_shell is not None else None
    gate_shell = shell if shell is not None and shell.kind == "gate" else None
    gate = gate_shell.gate if gate_shell is not None else None

    apply_monitor_meta(
        agent,
        monitor_id=monitor_shell.id if monitor_shell is not None else None,
        monitor_state=monitor_shell.state if monitor_shell is not None else None,
        monitor_command=monitor.command if monitor is not None else None,
        monitor_label=monitor_shell.label if monitor_shell is not None else None,
        monitor_start_status=(
            monitor_shell.start_status if monitor_shell is not None else None
        ),
        monitor_stop_status=(
            monitor_shell.stop_status if monitor_shell is not None else None
        ),
        monitor_exit_code=monitor.exit_code if monitor is not None else None,
        monitor_cwd=monitor.cwd if monitor is not None else None,
        monitor_reason=monitor_shell.reason if monitor_shell is not None else None,
        monitor_next_action=(
            monitor_shell.next_action if monitor_shell is not None else None
        ),
        monitor_timeout_seconds=(
            monitor_shell.timeout_seconds if monitor_shell is not None else None
        ),
        monitor_idle_timeout_seconds=(
            monitor.idle_timeout_seconds if monitor is not None else None
        ),
        monitor_output_truncated=(
            monitor_shell.output_truncated if monitor_shell is not None else None
        ),
        monitor_followup_outcome=(
            monitor_shell.followup_outcome if monitor_shell is not None else None
        ),
        monitor_followup_error=(
            monitor_shell.followup_error if monitor_shell is not None else None
        ),
        monitor_member=is_monitor_member_role(
            agent.agent_family_role,
            agent.role_suffix,
        ),
    )
    apply_gate_meta(
        agent,
        gate_id=gate_shell.id if gate_shell is not None else None,
        gate_kind=gate.kind if gate is not None else None,
        gate_state=gate_shell.state if gate_shell is not None else None,
        gate_start_status=(gate_shell.start_status if gate_shell is not None else None),
        gate_stop_status=gate_shell.stop_status if gate_shell is not None else None,
        gate_accent=gate.accent if gate is not None else None,
        gate_output_path=gate_shell.output_path if gate_shell is not None else None,
        gate_output_truncated=(
            gate_shell.output_truncated if gate_shell is not None else None
        ),
        gate_creator_agent=gate.creator_agent if gate is not None else None,
        gate_followup_agent=(
            gate_shell.followup_agent if gate_shell is not None else None
        ),
        gate_next_action=gate_shell.next_action if gate_shell is not None else None,
        gate_next_fork=gate.next_fork if gate is not None else None,
        gate_next_output=gate_shell.next_output if gate_shell is not None else None,
        gate_next_model=gate_shell.next_model if gate_shell is not None else None,
        gate_followup_outcome=(
            gate_shell.followup_outcome if gate_shell is not None else None
        ),
        gate_followup_error=(
            gate_shell.followup_error if gate_shell is not None else None
        ),
        gate_followup_degraded_reason=(
            gate_shell.followup_degraded_reason if gate_shell is not None else None
        ),
        gate_followup_prompt_path=(
            gate_shell.followup_prompt_path if gate_shell is not None else None
        ),
        gate_elapsed_seconds=(
            gate_shell.elapsed_seconds if gate_shell is not None else None
        ),
        gate_label=gate_shell.label if gate_shell is not None else None,
        gate_reason=gate_shell.reason if gate_shell is not None else None,
        gate_timeout_seconds=(
            gate_shell.timeout_seconds if gate_shell is not None else None
        ),
        gate_request_fingerprint=(
            gate_shell.request_fingerprint if gate_shell is not None else None
        ),
        gate_workspace_policy=gate.workspace_policy if gate is not None else None,
        gate_bundle_path=gate.bundle_path if gate is not None else None,
        gate_notification_id=gate.notification_id if gate is not None else None,
        gate_decision_path=gate.decision_path if gate is not None else None,
        gate_member=is_real_gate_member(
            agent.agent_family_role,
            gate_shell.id if gate_shell is not None else None,
        ),
    )

    agent.refresh_raw_presented_agent_name()
