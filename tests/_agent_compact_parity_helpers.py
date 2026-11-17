"""Shared parity helpers for compact row-constructor tests."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.models.agent import Agent

# Explicitly deferred detail fields: the full row carries them, the
# compact row keeps the ``Agent`` default until selected-record hydration
# (the workflow-cutover phase) restores them.
DEFERRED_ATTRS = ("response_path", "error_traceback", "monitor_command")

# Compared list/filter/action facts. ``finalizer`` and ``owner`` are
# normalized by _facts(); everything else compares with ==.
COMPARED_ATTRS = (
    "status",
    "cl_name",
    "project_file",
    "workflow",
    "raw_suffix",
    "start_time",
    "workspace_num",
    "workspace_dir",
    "model",
    "llm_provider",
    "vcs_provider",
    "agent_name",
    "hidden",
    "approve",
    "error_message",
    "plan_path",
    "archived_plan_path",
    "diff_path",
    "step_output",
    "bug",
    "cl_num",
    "agent_session",
    "agent_session_role",
    "agent_session_parallel",
    "tribe",
    "agent_tab",
    "role_suffix",
    "plan_chain_root",
    "plan_action",
    "plan_committed",
    "auto_approve_plan_action",
    "waiting_for",
    "waiting_for_beads",
    "waiting_for_hoods",
    "wait_for_epics_of",
    "wait_duration",
    "wait_until",
    "queue_capacity",
    "queue_capacity_explicit",
    "queue_capacity_multiplier",
    "wait_priority",
    "wait_priority_explicit",
    "queue_weight",
    "queue_weight_explicit",
    "queue_weight_invalid",
    "queue_weight_error",
    "slot_requested_at",
    "run_start_time",
    "stop_time",
    "wait_start_time",
    "retry_of_timestamp",
    "retry_attempt",
    "retry_chain_root_timestamp",
    "retried_as_timestamp",
    "retry_error_category",
    "retry_terminal",
    "retry_times",
    "plan_times",
    "feedback_times",
    "questions_times",
    "epic_time",
    "feedback_plan_paths",
    "epic_bead_id",
    "phase_bead_id",
    "created_epic_ids",
    "parent_timestamp",
    "question_request_path",
    "question_response_path",
    "question_session_id",
    "source_machine",
    "agent_clan",
    "agent_clan_generation",
    "clan_tribe",
    "clan_summary",
    "sdd_plan_path",
    "epic_plan_ref",
    "output_path",
    "recovery_state",
    "recovery_reason",
    "recovery_reason_text",
    "recovery_episode_id",
    "recovery_requested_at",
    "recovery_updated_at",
    "recovery_stale_pending",
    "hijack_expired",
    "hijack_id",
    "runner_slot_yielded",
    "monitor_id",
    "monitor_state",
    "monitor_stop_status",
    "monitor_exit_code",
    "monitor_followup_outcome",
    "monitor_followup_error",
    "monitor_followup_agent",
    "monitor_host_completion_status",
    "gate_id",
    "gate_kind",
    "gate_state",
    "gate_stop_status",
    "gate_followup_outcome",
    "workspace_retention",
    "reverted",
    "linked_repos",
    "output_variables",
    "runner_is_live",
    "pid",
    "process_identity",
    "runner_claim_owner_key",
    "status_bucket",
)

# Note: ``extra_files`` is deliberately absent above. Deferred media lists
# make it differ by design; the completed-row test asserts that split
# explicitly instead of folding it into the shared facts.


def _facts(agent: Agent) -> dict[str, Any]:
    facts = {name: getattr(agent, name) for name in COMPARED_ATTRS}
    facts["instruction_bundle_files"] = list(agent.instruction_bundle_files)
    summary = agent.finalizer_status
    facts["finalizer"] = (
        None
        if summary is None
        else (
            summary.phase,
            summary.status,
            summary.updated_at,
            summary.instance_count,
            tuple((i.id, i.status, i.op, i.step) for i in summary.instances),
        )
    )
    owner = agent.imported_source_owner
    facts["owner"] = None if owner is None else (owner.username, owner.machine_name)
    return facts


def _assert_parity(full: Agent | None, compact: Agent | None) -> None:
    assert (full is None) == (compact is None)
    assert full is not None and compact is not None
    assert _facts(full) == _facts(compact)
    for attr in DEFERRED_ATTRS:
        assert getattr(compact, attr) in (None, False), attr
    # Full-path rows carry whichever shape the query asked for; compact
    # rows are always list-shaped with the artifact dir for hydration.
    assert full.record_shape in ("full", "list")
    assert compact.record_shape == "list"
    assert compact.index_record_dir == full.index_record_dir
