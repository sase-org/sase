"""Shared helpers for agent metadata enrichment."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agent.status_buckets import pending_plan_status_for_tier
from sase.core.agent_identity_facade import imported_source_owner_from_mapping
from sase.core.time import to_local
from sase.core.artifact_file_helpers import select_canonical_plan_path
from sase.gate_shell.state import gate_member_status_bucket, gate_state_is_terminal
from sase.gate_shell.status import gate_status_pair
from sase.monitor_state import monitor_state_bucket
from sase.monitor_status import (
    DEFAULT_MONITOR_START_STATUS,
    clamp_monitor_status_or_default,
)
from sase.plan_chain import (
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
)

from ....agent_tribes import InvalidTribeError, validate_tribe_name
from ._json_cache import load_json_cached
from ..agent import Agent, LinkedRepoMetadata

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentMetaWire


ACTIVE_ENRICHMENT_STATUSES = {"STARTING", "RUNNING"}


def apply_imported_source_owner(agent: Agent, raw: object) -> None:
    """Copy an ``imported_source_owner`` mapping onto *agent* when present."""
    owner = imported_source_owner_from_mapping(raw)
    if owner is not None:
        agent.imported_source_owner = owner


def apply_monitor_meta(
    agent: Agent,
    *,
    monitor_id: object,
    monitor_state: object,
    monitor_command: object,
    monitor_label: object,
    monitor_start_status: object,
    monitor_stop_status: object,
    monitor_exit_code: object,
    monitor_cwd: object = None,
    monitor_reason: object = None,
    monitor_next_action: object = None,
    monitor_timeout_seconds: object = None,
    monitor_idle_timeout_seconds: object = None,
    monitor_output_truncated: object = None,
    monitor_followup_outcome: object = None,
    monitor_followup_error: object = None,
    monitor_member: bool,
) -> None:
    """Apply monitor fields from ``agent_meta.json`` to one row."""
    if not isinstance(monitor_id, str) or not monitor_id:
        return
    state = monitor_state if isinstance(monitor_state, str) else None
    agent.monitor_id = monitor_id
    agent.monitor_state = state
    agent.monitor_command = (
        monitor_command if isinstance(monitor_command, str) else None
    )
    agent.monitor_label = monitor_label if isinstance(monitor_label, str) else None
    if isinstance(monitor_start_status, str):
        start_status = clamp_monitor_status_or_default(monitor_start_status, default="")
        if start_status:
            agent.monitor_start_status = start_status
    if isinstance(monitor_stop_status, str):
        stop_status = clamp_monitor_status_or_default(monitor_stop_status, default="")
        if stop_status:
            agent.monitor_stop_status = stop_status
    if type(monitor_exit_code) is int:
        agent.monitor_exit_code = monitor_exit_code
    agent.monitor_cwd = monitor_cwd if isinstance(monitor_cwd, str) else None
    agent.monitor_reason = monitor_reason if isinstance(monitor_reason, str) else None
    agent.monitor_next_action = (
        monitor_next_action if isinstance(monitor_next_action, str) else None
    )
    if isinstance(monitor_timeout_seconds, (int, float)) and not isinstance(
        monitor_timeout_seconds, bool
    ):
        agent.monitor_timeout_seconds = float(monitor_timeout_seconds)
    if isinstance(monitor_idle_timeout_seconds, (int, float)) and not isinstance(
        monitor_idle_timeout_seconds, bool
    ):
        agent.monitor_idle_timeout_seconds = float(monitor_idle_timeout_seconds)
    agent.monitor_output_truncated = bool(monitor_output_truncated)
    agent.monitor_followup_outcome = (
        monitor_followup_outcome if isinstance(monitor_followup_outcome, str) else None
    )
    agent.monitor_followup_error = (
        monitor_followup_error if isinstance(monitor_followup_error, str) else None
    )
    if not monitor_member:
        return
    agent.status_bucket = monitor_state_bucket(state)
    if state == "running" and agent.status != "STARTING":
        agent.status = clamp_monitor_status_or_default(
            monitor_start_status if isinstance(monitor_start_status, str) else None,
            default=DEFAULT_MONITOR_START_STATUS,
        )


def apply_monitor_done(
    agent: Agent,
    *,
    monitor_state: object,
    monitor_exit_code: object,
    status_label: object,
    monitor_followup_outcome: object = None,
    monitor_followup_error: object = None,
) -> None:
    """Apply terminal monitor fields from ``done.json`` to one row."""
    state = monitor_state if isinstance(monitor_state, str) else agent.monitor_state
    if isinstance(state, str) and state:
        agent.monitor_state = state
        agent.status_bucket = monitor_state_bucket(state)
    if type(monitor_exit_code) is int:
        agent.monitor_exit_code = monitor_exit_code
    if isinstance(status_label, str) and status_label:
        agent.status = status_label
        agent.monitor_stop_status = (
            clamp_monitor_status_or_default(status_label, default="") or None
        )
    if isinstance(monitor_followup_outcome, str) and monitor_followup_outcome:
        agent.monitor_followup_outcome = monitor_followup_outcome
    if isinstance(monitor_followup_error, str) and monitor_followup_error:
        agent.monitor_followup_error = monitor_followup_error


def apply_gate_meta(
    agent: Agent,
    *,
    gate_id: object,
    gate_kind: object,
    gate_state: object,
    gate_start_status: object,
    gate_stop_status: object,
    gate_accent: object,
    gate_output_path: object = None,
    gate_output_truncated: object = None,
    gate_creator_agent: object = None,
    gate_followup_agent: object = None,
    gate_next_action: object = None,
    gate_next_fork: object = None,
    gate_next_output: object = None,
    gate_next_model: object = None,
    gate_followup_outcome: object = None,
    gate_followup_error: object = None,
    gate_followup_degraded_reason: object = None,
    gate_followup_prompt_path: object = None,
    gate_elapsed_seconds: object = None,
    gate_label: object = None,
    gate_reason: object = None,
    gate_timeout_seconds: object = None,
    gate_request_fingerprint: object = None,
    gate_workspace_policy: object = None,
    gate_bundle_path: object = None,
    gate_notification_id: object = None,
    gate_decision_path: object = None,
    gate_member: bool,
) -> None:
    """Apply gate fields from ``agent_meta.json`` to one row."""
    if not isinstance(gate_id, str) or not gate_id:
        return
    state = gate_state if isinstance(gate_state, str) else "pending"
    pair = gate_status_pair(
        gate_start_status if isinstance(gate_start_status, str) else None,
        gate_stop_status if isinstance(gate_stop_status, str) else None,
    )
    agent.gate_id = gate_id
    agent.gate_kind = gate_kind if isinstance(gate_kind, str) else None
    agent.gate_state = state
    agent.gate_start_status = pair.start
    agent.gate_stop_status = pair.stop
    agent.gate_accent = gate_accent if isinstance(gate_accent, str) else None
    agent.gate_output_path = (
        gate_output_path if isinstance(gate_output_path, str) else None
    )
    agent.gate_output_truncated = bool(gate_output_truncated)
    agent.gate_creator_agent = (
        gate_creator_agent if isinstance(gate_creator_agent, str) else None
    )
    agent.gate_followup_agent = (
        gate_followup_agent if isinstance(gate_followup_agent, str) else None
    )
    agent.gate_next_action = (
        gate_next_action if isinstance(gate_next_action, str) else None
    )
    agent.gate_next_fork = gate_next_fork if isinstance(gate_next_fork, str) else None
    agent.gate_next_output = (
        gate_next_output if isinstance(gate_next_output, str) else None
    )
    agent.gate_next_model = (
        gate_next_model if isinstance(gate_next_model, str) else None
    )
    agent.gate_followup_outcome = (
        gate_followup_outcome if isinstance(gate_followup_outcome, str) else None
    )
    agent.gate_followup_error = (
        gate_followup_error if isinstance(gate_followup_error, str) else None
    )
    agent.gate_followup_degraded_reason = (
        gate_followup_degraded_reason
        if isinstance(gate_followup_degraded_reason, str)
        else None
    )
    agent.gate_followup_prompt_path = (
        gate_followup_prompt_path
        if isinstance(gate_followup_prompt_path, str)
        else None
    )
    if isinstance(gate_elapsed_seconds, (int, float)) and not isinstance(
        gate_elapsed_seconds, bool
    ):
        agent.gate_elapsed_seconds = float(gate_elapsed_seconds)
    agent.gate_label = gate_label if isinstance(gate_label, str) else None
    agent.gate_reason = gate_reason if isinstance(gate_reason, str) else None
    if isinstance(gate_timeout_seconds, (int, float)) and not isinstance(
        gate_timeout_seconds, bool
    ):
        agent.gate_timeout_seconds = float(gate_timeout_seconds)
    agent.gate_request_fingerprint = (
        gate_request_fingerprint if isinstance(gate_request_fingerprint, str) else None
    )
    agent.gate_workspace_policy = (
        gate_workspace_policy if isinstance(gate_workspace_policy, str) else None
    )
    agent.gate_bundle_path = (
        gate_bundle_path if isinstance(gate_bundle_path, str) else None
    )
    agent.gate_notification_id = (
        gate_notification_id if isinstance(gate_notification_id, str) else None
    )
    agent.gate_decision_path = (
        gate_decision_path if isinstance(gate_decision_path, str) else None
    )
    if not gate_member:
        return
    agent.status = pair.stop if gate_state_is_terminal(state) else pair.start
    agent.status_bucket = gate_member_status_bucket(state, agent.status)


def apply_gate_done(
    agent: Agent,
    *,
    gate_id: object = None,
    gate_kind: object = None,
    gate_state: object,
    gate_elapsed_seconds: object = None,
    gate_output_path: object = None,
    gate_output_truncated: object = None,
    gate_bundle_path: object = None,
    gate_notification_id: object = None,
    status_label: object = None,
    gate_followup_outcome: object = None,
    gate_followup_error: object = None,
    gate_followup_degraded_reason: object = None,
    gate_followup_prompt_path: object = None,
) -> None:
    """Apply terminal gate fields from ``done.json`` to one row."""
    if isinstance(gate_id, str) and gate_id:
        agent.gate_id = gate_id
    if isinstance(gate_kind, str) and gate_kind:
        agent.gate_kind = gate_kind
    state = gate_state if isinstance(gate_state, str) else agent.gate_state
    if isinstance(state, str) and state:
        agent.gate_state = state
    if isinstance(gate_elapsed_seconds, (int, float)) and not isinstance(
        gate_elapsed_seconds, bool
    ):
        agent.gate_elapsed_seconds = float(gate_elapsed_seconds)
    if isinstance(gate_output_path, str) and gate_output_path:
        agent.gate_output_path = gate_output_path
    agent.gate_output_truncated = bool(gate_output_truncated)
    if isinstance(gate_bundle_path, str) and gate_bundle_path:
        agent.gate_bundle_path = gate_bundle_path
    if isinstance(gate_notification_id, str) and gate_notification_id:
        agent.gate_notification_id = gate_notification_id
    if isinstance(status_label, str) and status_label:
        pair = gate_status_pair(agent.gate_start_status, status_label)
        agent.gate_start_status = pair.start
        agent.gate_stop_status = pair.stop
        agent.status = pair.stop
    elif agent.gate_stop_status and gate_state_is_terminal(agent.gate_state):
        agent.status = agent.gate_stop_status
    if isinstance(state, str) and state:
        agent.status_bucket = gate_member_status_bucket(agent.gate_state, agent.status)
    if isinstance(gate_followup_outcome, str) and gate_followup_outcome:
        agent.gate_followup_outcome = gate_followup_outcome
    if isinstance(gate_followup_error, str) and gate_followup_error:
        agent.gate_followup_error = gate_followup_error
    if isinstance(gate_followup_degraded_reason, str) and gate_followup_degraded_reason:
        agent.gate_followup_degraded_reason = gate_followup_degraded_reason
    if isinstance(gate_followup_prompt_path, str) and gate_followup_prompt_path:
        agent.gate_followup_prompt_path = gate_followup_prompt_path


def refresh_agent_plan_path(agent: Agent) -> None:
    """Refresh the compatibility plan path from retained source metadata."""
    agent.plan_path = select_canonical_plan_path(
        archived_plan_path=agent.archived_plan_path or agent.plan_path,
        sdd_plan_path=agent.sdd_plan_path,
        plan_committed=agent.plan_committed,
        plan_action=agent.plan_action,
    )


def parse_utc_to_local(iso_str: str) -> datetime:
    """Parse a UTC ISO 8601 timestamp and convert to configured-tz display time.

    Delegates to :func:`sase.core.time.to_local`, the shared aware→naive-local
    normalizer, so every model timestamp is a configured-tz wall time.
    """
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return to_local(dt)


def _parse_timestamp_field(raw_value: object) -> list[datetime]:
    values: list[str] = []
    if isinstance(raw_value, str):
        values = [raw_value]
    elif isinstance(raw_value, list):
        values = [v for v in raw_value if isinstance(v, str)]
    return _parse_timestamp_values(values)


def _parse_timestamp_values(values: list[str]) -> list[datetime]:
    parsed: list[datetime] = []
    for value in values:
        try:
            parsed.append(parse_utc_to_local(value))
        except ValueError:
            continue
    return parsed


def append_timestamp_field(
    raw_value: object,
    target: list[datetime],
) -> list[datetime]:
    parsed = _parse_timestamp_field(raw_value)
    target.extend(parsed)
    return parsed


def append_timestamp_values(
    values: list[str],
    target: list[datetime],
) -> list[datetime]:
    parsed = _parse_timestamp_values(values)
    target.extend(parsed)
    return parsed


def has_plan_submission_marker(raw_value: object) -> bool:
    if isinstance(raw_value, str):
        return bool(raw_value)
    if isinstance(raw_value, list):
        return any(isinstance(value, str) and value for value in raw_value)
    return False


def plan_enrichment_status(
    *,
    plan_approved: bool,
    plan_action: str | None,
    plan_submitted: bool,
    auto_approved: bool,
    plan_tier: str | None = None,
) -> str | None:
    if plan_approved:
        if plan_action == "commit":
            return "PLAN COMMITTED"
        if plan_action == "tale":
            return "TALE APPROVED"
        if plan_action == "epic":
            return "EPIC APPROVED"
        return "PLAN APPROVED"

    if plan_submitted and not auto_approved:
        return pending_plan_status_for_tier(plan_tier)

    return None


def pending_question_status_for_request_path(request_path: object) -> str:
    """Map a pending-question ``request_path`` to ``QUESTION`` or ``ANSWERED``.

    The pending-question marker's ``request_path`` points at the
    ``question_request.json`` written in the user-question session directory.
    The sibling ``question_response.json`` appears there once the user answers
    but before the runner consumes the response and clears the marker, so its
    presence is the transient ``ANSWERED`` signal. When no response is visible
    yet, the agent is still blocked and the status stays ``QUESTION``.
    """
    if isinstance(request_path, str) and request_path:
        response_path = Path(request_path).parent / "question_response.json"
        try:
            if response_path.exists():
                return "ANSWERED"
        except OSError:
            pass
    return "QUESTION"


def pending_question_status_from_marker(marker_path: Path) -> str:
    """Read a filesystem ``pending_question.json`` and map it to a status."""
    try:
        marker = load_json_cached(marker_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return "QUESTION"
    request_path = marker.get("request_path") if isinstance(marker, dict) else None
    return pending_question_status_for_request_path(request_path)


def valid_meta_tribe(raw_value: object) -> str | None:
    if not isinstance(raw_value, str):
        return None
    try:
        return validate_tribe_name(raw_value)
    except InvalidTribeError:
        return None


def parse_linked_repos(raw_value: object) -> tuple[LinkedRepoMetadata, ...]:
    if not isinstance(raw_value, list):
        return ()

    parsed: list[LinkedRepoMetadata] = []
    from sase.linked_repos import is_legacy_static_linked_repo_record

    for item in raw_value:
        if not isinstance(item, dict):
            continue
        if is_legacy_static_linked_repo_record(item):
            continue
        raw_name = item.get("name")
        raw_workspace_dir = item.get("workspace_dir")
        if not isinstance(raw_name, str) or not raw_name:
            continue
        if not isinstance(raw_workspace_dir, str) or not raw_workspace_dir:
            continue
        parsed.append(
            LinkedRepoMetadata(
                name=raw_name,
                workspace_dir=raw_workspace_dir,
            )
        )
    return tuple(parsed)


def meta_has_wait_directive(data: dict[str, object]) -> bool:
    return (
        bool(data.get("wait_for"))
        or bool(data.get("wait_for_beads"))
        or data.get("wait_duration") is not None
        or bool(data.get("wait_until"))
    )


def wire_meta_has_wait_directive(meta: AgentMetaWire) -> bool:
    return (
        bool(meta.wait_for)
        or bool(meta.wait_for_beads)
        or meta.wait_duration is not None
        or bool(meta.wait_until)
    )


def parent_timestamp_from_meta(
    agent: Agent,
    raw_value: object,
    *,
    workflow_child: bool,
) -> str | None:
    if not raw_value:
        return None
    parent_timestamp = str(raw_value)
    if (
        not workflow_child
        and agent.parent_workflow is None
        and agent.raw_suffix is not None
        and parent_timestamp == agent.raw_suffix
    ):
        return None
    return parent_timestamp


def is_main_workflow_agent_step(agent: Agent) -> bool:
    return (
        agent.parent_workflow is not None
        and agent.step_type == "agent"
        and agent.parent_step_index is None
    )


def _root_family_name_from_meta(data: dict[str, object]) -> str | None:
    role_suffix = canonical_plan_chain_suffix(data.get("role_suffix"))
    is_root = (
        data.get("plan_chain_root")
        or data.get("agent_family_role") == "root"
        or role_suffix == PLAN_CHAIN_PLAN_SUFFIX
    )
    if not is_root:
        return None
    family = data.get("agent_family")
    if isinstance(family, str) and family:
        return family
    name = data.get("name")
    if isinstance(name, str) and name:
        return name
    return None


def _root_child_suffix_from_meta(data: dict[str, object]) -> str:
    return (
        canonical_plan_chain_suffix(data.get("role_suffix")) or PLAN_CHAIN_PLAN_SUFFIX
    )


def apply_workflow_child_identity_from_meta(
    agent: Agent,
    data: dict[str, object],
) -> None:
    """Derive concrete family identity for the main agent workflow step."""
    if not is_main_workflow_agent_step(agent):
        return
    family = _root_family_name_from_meta(data)
    if family is None:
        return
    child_suffix = _root_child_suffix_from_meta(data)
    child_name = agent_family_phase_name(family, child_suffix)
    agent.agent_name = child_name
    agent.agent_family = family
    agent.agent_family_role = agent_family_role_for_suffix(child_suffix)
    agent.role_suffix = child_suffix


def _root_family_name_from_meta_wire(meta: AgentMetaWire) -> str | None:
    role_suffix = canonical_plan_chain_suffix(meta.role_suffix)
    is_root = (
        meta.plan_chain_root
        or meta.agent_family_role == "root"
        or role_suffix == PLAN_CHAIN_PLAN_SUFFIX
    )
    if not is_root:
        return None
    if meta.agent_family:
        return meta.agent_family
    if meta.name:
        return meta.name
    return None


def _root_child_suffix_from_meta_wire(meta: AgentMetaWire) -> str:
    return canonical_plan_chain_suffix(meta.role_suffix) or PLAN_CHAIN_PLAN_SUFFIX


def apply_workflow_child_identity_from_meta_wire(
    agent: Agent,
    meta: AgentMetaWire,
) -> None:
    """Wire-aware mirror of :func:`apply_workflow_child_identity_from_meta`."""
    if not is_main_workflow_agent_step(agent):
        return
    family = _root_family_name_from_meta_wire(meta)
    if family is None:
        return
    child_suffix = _root_child_suffix_from_meta_wire(meta)
    child_name = agent_family_phase_name(family, child_suffix)
    agent.agent_name = child_name
    agent.agent_family = family
    agent.agent_family_role = agent_family_role_for_suffix(child_suffix)
    agent.role_suffix = child_suffix
