"""Filesystem-backed agent metadata enrichment implementation."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_scan_wire_markers import finalizer_status_from_mapping
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.core.output_variable_values import coerce_var_map
from sase.plan_chain import (
    agent_session_parallel_value,
    agent_session_role_value,
    agent_session_value,
)
from sase.sdd.plan_tiers import cached_plan_tier

from ._json_cache import load_json_cached
from ._meta_enrichment_filesystem_turn import apply_filesystem_turn_meta
from ._meta_enrichment_filesystem_waiting import (
    apply_filesystem_waiting_meta,
    apply_queue_weight_fields,
)
from ._meta_enrichment_identity import (
    apply_archive_source_machine,
    apply_imported_source_owner,
    apply_workflow_child_identity_from_meta,
    is_main_workflow_agent_step,
    meta_has_wait_directive,
    parent_timestamp_from_meta,
    parse_linked_repos,
    valid_meta_tribe,
)
from ._meta_enrichment_status import (
    ACTIVE_ENRICHMENT_STATUSES,
    append_timestamp_field,
    apply_finalizer_status,
    has_plan_submission_marker,
    parse_utc_to_local,
    pending_review_window_active,
    plan_enrichment_status,
    refresh_agent_plan_path,
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
    # Imported lazily to keep the TUI startup closure lean.
    from sase.core.wait_epic_follow_view import epic_follow_views

    if not artifacts_dir:
        agent.refresh_raw_presented_agent_name()
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
        agent.refresh_raw_presented_agent_name()
        return

    if not isinstance(data, dict):
        refresh_agent_plan_path(agent)
        agent.refresh_raw_presented_agent_name()
        return
    data = canonicalize_agent_tribe_metadata(dict(data))
    for field_name in ("process_identity", "runner_claim_owner_key"):
        value = data.get(field_name)
        if isinstance(value, str):
            setattr(agent, field_name, value)

    raw_status_bucket = data.get("status_bucket")
    if isinstance(raw_status_bucket, str) and raw_status_bucket:
        agent.status_bucket = raw_status_bucket
    if data.get("model"):
        agent.model = data["model"]
    if data.get("llm_provider"):
        agent.llm_provider = data["llm_provider"]
    if data.get("reasoning_effort"):
        agent.reasoning_effort = data["reasoning_effort"]
    if data.get("model_alias"):
        agent.model_alias = data["model_alias"]
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
    raw_epic_plan_ref = data.get("epic_plan_ref")
    if isinstance(raw_epic_plan_ref, str) and raw_epic_plan_ref:
        agent.epic_plan_ref = raw_epic_plan_ref
    raw_epic_bead_id = data.get("epic_bead_id")
    if isinstance(raw_epic_bead_id, str) and raw_epic_bead_id:
        agent.epic_bead_id = raw_epic_bead_id
    raw_phase_bead_id = data.get("phase_bead_id")
    if isinstance(raw_phase_bead_id, str) and raw_phase_bead_id:
        agent.phase_bead_id = raw_phase_bead_id
    from sase.core.created_epics import created_epic_ids_from_meta

    created_epic_ids = created_epic_ids_from_meta(data)
    if created_epic_ids and not agent.created_epic_ids:
        agent.created_epic_ids = tuple(created_epic_ids)
    if "linked_repos" in data:
        agent.linked_repos = parse_linked_repos(data.get("linked_repos"))
    commit_diff_path = data.get("commit_diff_path")
    if not agent.diff_path and isinstance(commit_diff_path, str) and commit_diff_path:
        agent.diff_path = commit_diff_path
    if not workflow_child and data.get("name"):
        agent.agent_name = data["name"]
    meta_tribe = valid_meta_tribe(data.get("tribe"))
    if meta_tribe:
        agent.tribe = meta_tribe
    raw_tab = data.get("agent_tab")
    if isinstance(raw_tab, str) and raw_tab:
        try:
            from sase.core.agent_tab import canonicalize_agent_tab

            canonical = canonicalize_agent_tab(raw_tab)
            if canonical:
                agent.agent_tab = canonical
        except Exception:  # noqa: BLE001 - bad file must not fail load.
            pass
    if "output_variables" in data:
        agent.output_variables = coerce_var_map(data.get("output_variables"))
    if data.get("wait_for"):
        agent.waiting_for = data["wait_for"]
    if data.get("wait_for_beads"):
        agent.waiting_for_beads = data["wait_for_beads"]
    if data.get("wait_for_hoods"):
        agent.waiting_for_hoods = data["wait_for_hoods"]
    if data.get("wait_for_epics_of"):
        agent.wait_for_epics_of = [
            item for item in data["wait_for_epics_of"] if isinstance(item, str)
        ]
    if data.get("wait_epic_follows"):
        agent.wait_epic_follows = list(epic_follow_views(data["wait_epic_follows"]))
    from sase.core.agent_scan_wire_markers_wait_turn import (
        wait_turn_bindings_from_payload,
    )

    agent.wait_turn_bindings = wait_turn_bindings_from_payload(data)
    apply_queue_weight_fields(agent, data)
    # Record-only launches persist no legacy ``%auto`` keys: project them
    # from the stored record into a loader-local view (never written back)
    # so the TUI renders identical state in both flag states.
    from sase.autonomy.record import with_legacy_projection

    try:
        auto_data = with_legacy_projection(data)
    except Exception:
        auto_data = data
    raw_auto_action = auto_data.get("auto_approve_plan_action")
    auto_action = (
        raw_auto_action
        if isinstance(raw_auto_action, str) and raw_auto_action
        else None
    )
    meta_auto_approved = (
        agent.approve or bool(auto_data.get("approve")) or bool(auto_action)
    )
    if meta_auto_approved:
        from sase._plan_gate_metadata import recorded_auto_covers_plan

        meta_auto_approved = recorded_auto_covers_plan(
            auto_action,
            auto_data.get("auto_approve_argument"),
            auto_data.get("plan_path"),
        )
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
    if apply_meta_approve and auto_data.get("approve"):
        agent.approve = True
    if data.get("hidden"):
        agent.hidden = True
    if not workflow_child and data.get("role_suffix"):
        agent.role_suffix = data["role_suffix"]
    session_name = agent_session_value(data)
    if not workflow_child and session_name:
        agent.agent_session = session_name
    session_role = agent_session_role_value(data)
    if not workflow_child and session_role:
        agent.agent_session_role = session_role
    if not workflow_child:
        apply_imported_source_owner(agent, data.get("imported_source_owner"))
        apply_archive_source_machine(agent, data.get("source_machine"))
    if not workflow_child:
        agent.agent_session_parallel = bool(agent_session_parallel_value(data))
        raw_clan = data.get("agent_clan")
        if not isinstance(raw_clan, str) or not raw_clan:
            session_fallback = agent_session_value(data)
            if agent.agent_session_parallel and isinstance(session_fallback, str):
                raw_clan = session_fallback
        if isinstance(raw_clan, str) and raw_clan:
            agent.agent_clan = raw_clan
        raw_generation = data.get("agent_clan_generation")
        if isinstance(raw_generation, str) and raw_generation:
            agent.agent_clan_generation = raw_generation
        raw_clan_tribe = data.get("clan_tribe")
        if isinstance(raw_clan_tribe, str) and raw_clan_tribe:
            agent.clan_tribe = raw_clan_tribe
        raw_clan_summary = data.get("clan_summary")
        if isinstance(raw_clan_summary, str) and raw_clan_summary:
            agent.clan_summary = raw_clan_summary
    if not workflow_child and data.get("plan_chain_root"):
        agent.plan_chain_root = True
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

    apply_filesystem_waiting_meta(agent, data, artifacts_dir)

    # Set plan review / approval statuses for agents whose agent_meta carries
    # plan: true (epic/tale auto-approval and submitted-plan flows). PLAN means
    # a submitted plan is waiting on manual review; agents still drafting a
    # plan, or using an auto-approval path, keep their current active display
    # state until later markers take over.
    if auto_data.get("plan"):
        plan_approved = bool(data.get("plan_approved"))
        raw_plan_action = data.get("plan_action")
        plan_action = raw_plan_action if isinstance(raw_plan_action, str) else None
        plan_submitted = has_plan_submission_marker(data.get("plan_submitted_at"))
        eligible = agent.status in ACTIVE_ENRICHMENT_STATUSES
        if not eligible and agent.status == "DONE":
            raw_gate_id = data.get("gate_id")
            raw_gate_member_agent_name = data.get("gate_member_agent_name")
            eligible = pending_review_window_active(
                plan_submitted=plan_submitted,
                plan_approved=plan_approved,
                plan_action=plan_action,
                auto_approved=meta_auto_approved,
                gate_id=raw_gate_id if isinstance(raw_gate_id, str) else None,
                gate_member_agent_name=(
                    raw_gate_member_agent_name
                    if isinstance(raw_gate_member_agent_name, str)
                    else None
                ),
                stopped_at=stopped_at if isinstance(stopped_at, str) else None,
                has_done_marker=(Path(artifacts_dir) / "done.json").exists(),
                pid=agent.pid,
            )
        if eligible:
            plan_status = plan_enrichment_status(
                plan_approved=plan_approved,
                plan_action=plan_action,
                plan_submitted=plan_submitted,
                auto_approved=meta_auto_approved,
                plan_tier=(
                    cached_plan_tier(data.get("plan_path"))
                    if plan_submitted and not plan_approved and not meta_auto_approved
                    else None
                ),
                plan_committed=agent.plan_committed,
            )
            if plan_status is not None:
                agent.status = plan_status

    apply_filesystem_turn_meta(agent, data)

    apply_finalizer_status(
        agent,
        finalizer_status_from_mapping(data.get("finalizer_status")),
    )

    from sase.agent.auto_restart.ux import apply_provenance_to_agent

    apply_provenance_to_agent(agent, data.get("auto_restart"))

    if agent.is_monitor and agent.pid is None:
        pid = data.get("pid")
        if type(pid) is not int:
            try:
                running = load_json_cached(Path(artifacts_dir) / "running.json")
            except (OSError, ValueError):
                running = {}
            if not isinstance(running, dict):
                running = {}
            pid = running.get("pid")
            if agent.process_identity is None:
                identity = running.get("process_identity")
                if isinstance(identity, str):
                    agent.process_identity = identity
        if type(pid) is int:
            agent.pid = pid
            agent.pid_liveness_unverified = True

    agent.refresh_raw_presented_agent_name()
