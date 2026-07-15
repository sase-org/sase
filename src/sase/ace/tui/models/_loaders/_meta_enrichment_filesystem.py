"""Filesystem-backed agent metadata enrichment."""

from __future__ import annotations

import json
from pathlib import Path

from ._json_cache import load_json_cached
from ._meta_enrichment_common import (
    ACTIVE_ENRICHMENT_STATUSES,
    apply_custom_role_display_labels,
    append_timestamp_field,
    apply_workflow_child_identity_from_meta,
    has_plan_submission_marker,
    is_main_workflow_agent_step,
    meta_has_wait_directive,
    parent_timestamp_from_meta,
    parse_utc_to_local,
    parse_linked_repos,
    pending_question_status_from_marker,
    plan_enrichment_status,
    refresh_agent_plan_path,
    string_output_variables,
    valid_meta_tag,
)
from ..agent import Agent


def enrich_agent_from_meta(
    agent: Agent,
    artifacts_dir: str | None,
    *,
    workflow_child: bool = False,
) -> None:
    """Read agent_meta.json and populate model/vcs_provider fields.

    Args:
        agent: The Agent to enrich (modified in place).
        artifacts_dir: Path to the artifacts directory, or None.
    """
    if not artifacts_dir:
        return

    # The marker is lower priority than direct agent metadata but higher than
    # a done-marker path already placed on the model by completed loaders.
    plan_path_marker = Path(artifacts_dir) / "plan_path.json"
    try:
        plan_path_data = load_json_cached(plan_path_marker)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        plan_path_data = None
    if isinstance(plan_path_data, dict):
        marker_plan_path = plan_path_data.get("plan_path")
        if isinstance(marker_plan_path, str) and marker_plan_path:
            agent.archived_plan_path = marker_plan_path
            agent.plan_path = marker_plan_path

    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        data = load_json_cached(meta_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        refresh_agent_plan_path(agent)
        return

    if not isinstance(data, dict):
        refresh_agent_plan_path(agent)
        return

    if data.get("model"):
        agent.model = data["model"]
    if data.get("llm_provider"):
        agent.llm_provider = data["llm_provider"]
    if data.get("reasoning_effort"):
        agent.reasoning_effort = data["reasoning_effort"]
    if data.get("vcs_provider"):
        agent.vcs_provider = data["vcs_provider"]
    if data.get("workspace_dir"):
        agent.workspace_dir = data["workspace_dir"]
    raw_archived_plan_path = data.get("plan_path")
    if isinstance(raw_archived_plan_path, str) and raw_archived_plan_path:
        agent.archived_plan_path = raw_archived_plan_path
    raw_sdd_plan_path = data.get("sdd_plan_path")
    if isinstance(raw_sdd_plan_path, str) and raw_sdd_plan_path:
        agent.sdd_plan_path = raw_sdd_plan_path
    raw_epic_bead_id = data.get("epic_bead_id")
    if isinstance(raw_epic_bead_id, str) and raw_epic_bead_id:
        agent.epic_bead_id = raw_epic_bead_id
    raw_phase_bead_id = data.get("phase_bead_id")
    if isinstance(raw_phase_bead_id, str) and raw_phase_bead_id:
        agent.phase_bead_id = raw_phase_bead_id
    if "linked_repos" in data:
        agent.linked_repos = parse_linked_repos(data.get("linked_repos"))
    commit_diff_path = data.get("commit_diff_path")
    if not agent.diff_path and isinstance(commit_diff_path, str) and commit_diff_path:
        agent.diff_path = commit_diff_path
    if not workflow_child and data.get("name"):
        agent.agent_name = data["name"]
    meta_tag = valid_meta_tag(data.get("tag"))
    if meta_tag:
        agent.tag = meta_tag
    if "output_variables" in data:
        agent.output_variables = string_output_variables(data.get("output_variables"))
    if data.get("wait_for"):
        agent.waiting_for = data["wait_for"]
    raw_auto_action = data.get("auto_approve_plan_action")
    auto_action = (
        raw_auto_action
        if isinstance(raw_auto_action, str) and raw_auto_action
        else None
    )
    meta_auto_approved = agent.approve or bool(data.get("approve")) or bool(auto_action)
    apply_meta_approve = not workflow_child or is_main_workflow_agent_step(agent)
    if apply_meta_approve and auto_action:
        agent.auto_approve_plan_action = auto_action
        agent.approve = True
    raw_plan_action = data.get("plan_action")
    if isinstance(raw_plan_action, str) and raw_plan_action:
        agent.plan_action = raw_plan_action
    raw_plan_committed = data.get("plan_committed")
    if type(raw_plan_committed) is bool:
        agent.plan_committed = raw_plan_committed
    refresh_agent_plan_path(agent)
    if apply_meta_approve and data.get("approve"):
        agent.approve = True
    if data.get("hidden"):
        agent.hidden = True
    if not workflow_child and data.get("role_suffix"):
        agent.role_suffix = data["role_suffix"]
    if not workflow_child and data.get("agent_family"):
        agent.agent_family = data["agent_family"]
    if not workflow_child and data.get("agent_family_role"):
        agent.agent_family_role = data["agent_family_role"]
    if not workflow_child and data.get("plan_chain_root"):
        agent.plan_chain_root = True
    apply_custom_role_display_labels(agent, data.get("agent_family_custom_role"))
    if workflow_child:
        apply_workflow_child_identity_from_meta(agent, data)
    if agent.parent_timestamp is None:
        parent_timestamp = parent_timestamp_from_meta(
            agent,
            data.get("parent_timestamp"),
            workflow_child=workflow_child,
        )
        if parent_timestamp is not None:
            agent.parent_timestamp = parent_timestamp
    if data.get("workspace_num") is not None and agent.workspace_num is None:
        try:
            agent.workspace_num = int(data["workspace_num"])
        except (ValueError, TypeError):
            pass

    # Retry-chain lineage (spawn-on-retry)
    if data.get("retry_of_timestamp"):
        agent.retry_of_timestamp = data["retry_of_timestamp"]
    raw_retry_attempt = data.get("retry_attempt")
    if isinstance(raw_retry_attempt, int):
        agent.retry_attempt = raw_retry_attempt
    if data.get("retry_chain_root_timestamp"):
        agent.retry_chain_root_timestamp = data["retry_chain_root_timestamp"]
    if data.get("retried_as_timestamp"):
        agent.retried_as_timestamp = data["retried_as_timestamp"]
    if data.get("retry_terminal"):
        agent.retry_terminal = bool(data["retry_terminal"])
    if data.get("retry_error_category"):
        agent.retry_error_category = data["retry_error_category"]

    # Parse plan_submitted_at (when plan was submitted for review)
    append_timestamp_field(data.get("plan_submitted_at"), agent.plan_times)

    # Parse epic_started_at (host kickoff, or a legacy creation follow-up)
    epic_started_at = data.get("epic_started_at")
    if isinstance(epic_started_at, str):
        try:
            agent.epic_time = parse_utc_to_local(epic_started_at)
        except ValueError:
            pass

    # Parse feedback_submitted_at (when feedback was given on the plan)
    feedback_times = append_timestamp_field(
        data.get("feedback_submitted_at"), agent.feedback_times
    )
    plan_path = data.get("plan_path")
    if isinstance(plan_path, str) and plan_path:
        for timestamp in feedback_times:
            agent.feedback_plan_paths[timestamp] = plan_path

    # Parse questions_submitted_at (when agent submitted questions)
    append_timestamp_field(data.get("questions_submitted_at"), agent.questions_times)
    if isinstance(data.get("question_request_path"), str):
        agent.question_request_path = data["question_request_path"]
    if isinstance(data.get("question_response_path"), str):
        agent.question_response_path = data["question_response_path"]
    if isinstance(data.get("question_session_id"), str):
        agent.question_session_id = data["question_session_id"]

    # Parse retry_started_at (list of timestamps, one per retry/fallback)
    retry_started_at = data.get("retry_started_at")
    if isinstance(retry_started_at, list):
        for ts in retry_started_at:
            if isinstance(ts, str):
                try:
                    agent.retry_times.append(parse_utc_to_local(ts))
                except ValueError:
                    pass

    # Parse run_started_at (actual start time after waiting period)
    run_started_at = data.get("run_started_at")
    wait_completed_at = data.get("wait_completed_at")
    if isinstance(run_started_at, str):
        try:
            agent.run_start_time = parse_utc_to_local(run_started_at)
            if agent.status == "STARTING":
                agent.status = "RUNNING"
        except ValueError:
            pass
    elif isinstance(wait_completed_at, str) and agent.status == "STARTING":
        agent.status = "RUNNING"

    # Parse stopped_at (completion time for DONE/FAILED agents)
    stopped_at = data.get("stopped_at")
    if isinstance(stopped_at, str):
        try:
            agent.stop_time = parse_utc_to_local(stopped_at)
        except ValueError:
            pass

    if isinstance(wait_completed_at, str) or (
        meta_has_wait_directive(data)
        and (
            agent.run_start_time is not None
            or agent.stop_time is not None
            or agent.status not in ACTIVE_ENRICHMENT_STATUSES
        )
    ):
        agent.wait_start_time = agent.start_time

    # Check for waiting.json to set WAITING status (takes precedence over PLAN
    # since the agent can't plan until its dependencies are resolved)
    waiting_path = Path(artifacts_dir) / "waiting.json"
    if waiting_path.exists() and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        agent.status = "WAITING"
        agent.wait_start_time = agent.start_time
        # waiting.json may contain an updated waiting_for list (e.g. from the TUI
        # "w" keymap), which takes precedence over agent_meta.json's wait_for.
        try:
            with open(waiting_path, encoding="utf-8") as f:
                waiting_data = json.load(f)
            if isinstance(waiting_data, dict):
                if waiting_data.get("waiting_for"):
                    agent.waiting_for = waiting_data["waiting_for"]
                # Read wait_duration from waiting.json (preferred source)
                raw_dur = waiting_data.get("wait_duration")
                if raw_dur is not None:
                    try:
                        agent.wait_duration = float(raw_dur)
                    except (ValueError, TypeError):
                        pass
                # Read wait_until from waiting.json
                raw_until = waiting_data.get("wait_until")
                if isinstance(raw_until, str) and raw_until:
                    agent.wait_until = raw_until
                raw_runners = waiting_data.get("wait_runners")
                if type(raw_runners) is int and raw_runners >= 0:
                    agent.wait_runners = raw_runners
                agent.wait_runners_explicit = (
                    waiting_data.get("wait_runners_explicit") is True
                )
                raw_requested_at = waiting_data.get("slot_requested_at")
                if isinstance(raw_requested_at, str) and raw_requested_at:
                    agent.slot_requested_at = raw_requested_at
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: read wait_duration from agent_meta.json if not set from waiting.json
    if agent.wait_duration is None:
        raw_dur = data.get("wait_duration")
        if raw_dur is not None:
            try:
                agent.wait_duration = float(raw_dur)
            except (ValueError, TypeError):
                pass

    # Fallback: read wait_until from agent_meta.json if not set from waiting.json
    if agent.wait_until is None:
        raw_until = data.get("wait_until")
        if isinstance(raw_until, str) and raw_until:
            agent.wait_until = raw_until

    # Check for pending_question.json to set QUESTION/ANSWERED status. The
    # marker is written by handle_questions_flow() before the response-wait
    # poll loop and retained until a root has reacquired its runner slot. Its
    # presence is therefore the authoritative slot-yield signal, independent of
    # the notification's dismissed/read state. A simultaneous waiting marker
    # wins after the answer because the root is queued to resume.
    pending_question_path = Path(artifacts_dir) / "pending_question.json"
    pending_question_exists = pending_question_path.exists()
    agent.runner_slot_yielded = pending_question_exists
    if pending_question_exists and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        agent.status = pending_question_status_from_marker(pending_question_path)

    # Set plan review / approval statuses for agents whose agent_meta carries
    # plan: true (epic/tale auto-approval and submitted-plan flows). PLAN means
    # a submitted plan is waiting on manual review; agents still drafting a
    # plan, or using an auto-approval path, keep their current active display
    # state until later markers take over.
    if data.get("plan") and agent.status in ACTIVE_ENRICHMENT_STATUSES:
        plan_status = plan_enrichment_status(
            plan_approved=bool(data.get("plan_approved")),
            plan_action=data.get("plan_action"),
            plan_submitted=has_plan_submission_marker(data.get("plan_submitted_at")),
            auto_approved=meta_auto_approved,
        )
        if plan_status is not None:
            agent.status = plan_status
