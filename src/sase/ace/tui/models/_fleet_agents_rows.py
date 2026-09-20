"""Builds Agent rows from federation fleet summary payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone, UTC
from typing import Any

from sase.core.time import to_local
from sase.gate_shell.state import gate_member_status_bucket, gate_state_is_terminal
from sase.gate_shell.state import is_real_gate_member
from sase.gate_shell.status import gate_status_pair

from ._fleet_agents_follow import summary_followed
from ._fleet_agents_hosts import (
    HostFeedIssue,
    combine_freshness,
    host_alias,
    host_diagnostic,
    host_feed_issues,
    viewer_observed_freshness,
)
from ._fleet_agents_identity import (
    agent_family_name,
    agent_name,
    patch_name,
    project_display_name,
    project_file,
    role_suffix_from_name,
)
from ._fleet_agents_nodes import normalize_remote_host_nodes
from ._fleet_agents_payload import host_payloads, summary_payloads
from ._fleet_agents_scalars import (
    datetime_from_unix,
    float_or_none,
    int_or_none,
    locator_id,
    mapping,
    optional_str,
    raw_suffix,
)
from ._fleet_agents_status import (
    liveness_is_stopped,
    queue_weight,
    status_bucket_from_wire,
    status_from_summary,
)
from .agent import Agent, AgentType

__all__ = ["HostFeedIssue", "host_feed_issues", "rows_from_response"]

_COARSE_REMOTE_STATUSES = frozenset(
    {
        "RUNNING",
        "STARTING",
        "WAITING",
        "WAITING INPUT",
        "QUEUED",
        "DONE",
        "FAILED",
        "STOPPED",
        "WAS RUNNING",
    }
)


def rows_from_response(
    response: Mapping[str, Any] | None,
    *,
    active_keys: frozenset[str],
    active_locator_ids: frozenset[str],
    followed_only: bool,
    attention_by_logical_key: Mapping[str, Mapping[str, Any]],
) -> list[Agent]:
    if response is None or response.get("disabled"):
        return []
    rows: list[Agent] = []
    for host_index, host in enumerate(host_payloads(response)):
        host_alias_value = host_alias(host, host_index)
        origin = mapping(host.get("origin"))
        origin_installation_id = optional_str(
            origin.get("installation_id"),
            origin.get("id"),
        )
        host_freshness_wire = mapping(host.get("freshness"))
        host_freshness = optional_str(
            host_freshness_wire.get("freshness"),
            host.get("freshness") if isinstance(host.get("freshness"), str) else None,
            host.get("status"),
        )
        host_status_raw = optional_str(host.get("status"))
        host_feed_error = optional_str(host_freshness_wire.get("error"))
        host_cache_age_seconds = (
            float_or_none(host.get("age_seconds")) if host.get("cached") else None
        )
        viewer_freshness = viewer_observed_freshness(host)
        observed_at = float_or_none(
            host.get("observed_at_unix"),
            host.get("observed_at"),
        )
        host_counts = mapping(host.get("authoritative_counts"))
        host_running_count = int_or_none(host_counts.get("running"))
        host_total_count = int_or_none(host_counts.get("logical_agent_total"))
        host_waiting_count = int_or_none(host_counts.get("waiting"))
        host_failed_count = int_or_none(host_counts.get("failed"))
        host_done_count = int_or_none(
            host_counts.get("done"),
            host_counts.get("completed"),
            host_counts.get("terminal"),
        )
        host_unknown_count = int_or_none(host_counts.get("unknown"))
        host_diagnostic_text = host_diagnostic(host, host_freshness_wire)
        host_summary_pairs: list[tuple[Mapping[str, Any], Agent]] = []
        for summary_index, summary in enumerate(summary_payloads(host)):
            agent = _agent_from_summary(
                summary,
                host_alias=host_alias_value,
                origin_installation_id=origin_installation_id,
                host_freshness=host_freshness,
                viewer_freshness=viewer_freshness,
                host_health=host_status_raw,
                host_diagnostic=host_diagnostic_text,
                host_status_raw=host_status_raw,
                host_feed_error=host_feed_error,
                host_cache_age_seconds=host_cache_age_seconds,
                observed_at_unix=observed_at,
                host_running_count=host_running_count,
                host_total_count=host_total_count,
                host_waiting_count=host_waiting_count,
                host_failed_count=host_failed_count,
                host_done_count=host_done_count,
                host_unknown_count=host_unknown_count,
                summary_index=summary_index,
                attention_by_logical_key=attention_by_logical_key,
            )
            followed = summary_followed(agent, active_keys, active_locator_ids)
            agent.fleet_followed = followed
            if followed_only and not followed:
                continue
            host_summary_pairs.append((summary, agent))
        rows.extend(normalize_remote_host_nodes(host_summary_pairs))
    return rows


def _agent_from_summary(
    summary: Mapping[str, Any],
    *,
    host_alias: str,
    origin_installation_id: str | None,
    host_freshness: str | None,
    viewer_freshness: str | None,
    host_health: str | None,
    host_diagnostic: str | None,
    host_status_raw: str | None,
    host_feed_error: str | None,
    host_cache_age_seconds: float | None,
    observed_at_unix: float | None,
    host_running_count: int | None,
    host_total_count: int | None,
    host_waiting_count: int | None,
    host_failed_count: int | None,
    host_done_count: int | None,
    host_unknown_count: int | None,
    summary_index: int,
    attention_by_logical_key: Mapping[str, Mapping[str, Any]],
) -> Agent:
    presentation = mapping(summary.get("presentation"))

    def fact(key: str) -> Any:
        # Owner-derived facts ride in ``presentation``; a legacy or hand-built
        # summary may still carry the same key flat.
        return presentation[key] if key in presentation else summary.get(key)

    owner_resolved = fact("owner_status") is True

    content = mapping(summary.get("content"))
    labels = mapping(summary.get("labels"))
    lifecycle = mapping(summary.get("lifecycle"))
    liveness = mapping(summary.get("liveness"))
    logical_locator = mapping(summary.get("logical_locator"))
    exact_locator = mapping(summary.get("exact_locator"))
    logical_key = optional_str(summary.get("logical_key"))
    exact_key = optional_str(summary.get("exact_key"))
    row_revision = mapping(summary.get("row_revision"))
    row_kind = optional_str(summary.get("row_kind"))
    family_role = optional_str(
        summary.get("family_role"),
        summary.get("agent_family_role"),
    )
    is_proc = row_kind == "proc" or family_role == "proc"
    is_gate = row_kind == "gate" or family_role == "gate"
    is_monitor = row_kind == "monitor" or family_role == "monitor"
    shell_id = exact_key or logical_key
    parent_timestamp = optional_str(summary.get("parent_timestamp"))
    family_name = agent_family_name(
        summary,
        labels,
        logical_locator,
        family_role=family_role,
        parent_timestamp=parent_timestamp,
    )
    agent_name_value = agent_name(
        summary,
        labels,
        logical_locator,
        exact_locator,
        logical_key,
        exact_key,
        summary_index,
    )
    role_suffix = optional_str(fact("role_suffix")) or role_suffix_from_name(
        agent_name_value,
        family_role,
    )
    patch_name_value = patch_name(
        summary,
        labels,
        logical_locator,
        agent_name_value,
    )
    project_display_name_value = project_display_name(summary, labels, logical_locator)
    project_file_value = project_file(logical_locator, project_display_name_value)
    raw_suffix_value = raw_suffix(
        host_alias,
        exact_key or logical_key or locator_id(exact_locator or logical_locator),
        summary_index,
    )
    attention = attention_by_logical_key.get(logical_key) if logical_key else None
    liveness_token = summary.get("liveness")
    dead = liveness_is_stopped(liveness_token, liveness)
    status = status_from_summary(
        summary,
        lifecycle,
        liveness,
        attention,
        lifecycle_token=summary.get("lifecycle"),
        liveness_token=liveness_token,
        owner_resolved=owner_resolved,
    )
    status_bucket = status_bucket_from_wire(summary.get("status_bucket"))
    revision = int_or_none(
        summary.get("revision"),
        row_revision.get("revision"),
    )
    start_time = datetime_from_unix(
        summary.get("started_at_unix"),
        summary.get("start_time_unix"),
        lifecycle.get("started_at_unix"),
        summary.get("observed_at_unix"),
        observed_at_unix,
    )
    stop_time = datetime_from_unix(
        summary.get("stopped_at_unix"),
        summary.get("finished_at_unix"),
        lifecycle.get("stopped_at_unix"),
    )
    run_start_time = (
        datetime_from_unix(
            summary.get("run_started_at_unix"),
            summary.get("run_start_time_unix"),
        )
        or start_time
    )
    freshness = combine_freshness(
        optional_str(
            summary.get("freshness"),
            host_freshness,
        ),
        viewer_freshness,
    )
    health = optional_str(
        summary.get("connection_health"),
        liveness.get("connection_health"),
        summary.get("liveness") if isinstance(summary.get("liveness"), str) else None,
        host_health,
    )
    bounded_intent = optional_str(
        summary.get("intent"),
        summary.get("bounded_intent"),
    )
    capabilities = mapping(summary.get("capabilities"))
    if revision is None:
        revision = int_or_none(row_revision.get("revision"))
    gate_id = optional_str(fact("gate_id"))
    if is_gate and gate_id is None:
        gate_id = shell_id
    monitor_id = optional_str(fact("monitor_id"))
    if is_monitor and monitor_id is None:
        monitor_id = shell_id
    proc_id = optional_str(fact("proc_id")) if is_proc else None
    if is_proc and proc_id is None:
        proc_id = shell_id
    monitor_state = optional_str(fact("monitor_state"))
    if is_monitor and monitor_state is None:
        monitor_state = "completed" if dead or stop_time is not None else "running"
    gate_state = optional_str(fact("gate_state"))
    if is_gate and gate_state is None:
        gate_state = "completed" if dead or stop_time is not None else "pending"
    agent = Agent(
        agent_type=AgentType.PROC_SHELL if is_proc else AgentType.RUNNING,
        cl_name=patch_name_value,
        project_file=project_file_value,
        status=status,
        # Owner-resolved rows derive the bucket from the rich status, exactly
        # like local rows; the wire bucket only describes the coarse lifecycle.
        status_bucket=None if owner_resolved else status_bucket,
        start_time=start_time,
        run_start_time=run_start_time,
        stop_time=stop_time,
        raw_suffix=raw_suffix_value,
        agent_name=agent_name_value,
        model=optional_str(summary.get("model")),
        llm_provider=optional_str(
            summary.get("provider"),
            summary.get("llm_provider"),
        ),
        reasoning_effort=optional_str(fact("reasoning_effort")),
        project_display_name=project_display_name_value,
        fleet_origin_alias=host_alias,
        fleet_origin_installation_id=origin_installation_id,
        fleet_logical_locator=dict(logical_locator) if logical_locator else None,
        fleet_exact_locator=dict(exact_locator) if exact_locator else None,
        fleet_logical_key=logical_key,
        fleet_exact_key=exact_key,
        fleet_revision=revision,
        fleet_row_revision=dict(row_revision) if row_revision else None,
        fleet_freshness=freshness,
        fleet_connection_health=health,
        fleet_observed_at_unix=observed_at_unix,
        fleet_host_status=host_status_raw,
        fleet_host_feed_error=host_feed_error,
        fleet_host_cache_age_seconds=host_cache_age_seconds,
        fleet_host_running_count=host_running_count,
        fleet_host_total_count=host_total_count,
        fleet_host_waiting_count=host_waiting_count,
        fleet_host_failed_count=host_failed_count,
        fleet_host_done_count=host_done_count,
        fleet_host_unknown_count=host_unknown_count,
        fleet_capabilities=dict(capabilities) if capabilities else None,
        fleet_content=dict(content) if content else None,
        fleet_bounded_intent=bounded_intent,
        fleet_diagnostic=host_diagnostic,
        fleet_attention=dict(attention) if attention else None,
        fleet_row_kind=row_kind,
        fleet_current_instance=bool(summary.get("current_instance")),
        fleet_container_projected_concrete_agent=bool(
            summary.get("container_projected_concrete_agent")
        ),
        role_suffix=role_suffix,
        agent_family=family_name,
        agent_family_role=optional_str(fact("agent_family_role")) or family_role,
        agent_family_parallel=bool(fact("agent_family_parallel")),
        parent_timestamp=parent_timestamp,
        plan_chain_root=bool(fact("plan_chain_root")),
        plan_action=optional_str(fact("plan_action")),
        plan_committed=_optional_bool(fact("plan_committed")),
        plan_times=_local_times(fact("plan_submitted_at_unix")),
        questions_times=_local_times(fact("questions_submitted_at_unix")),
        epic_time=_local_time(fact("epic_started_at_unix")),
        question_answered=fact("question_answered") is True,
        retry_of_timestamp=optional_str(fact("retry_of_timestamp")),
        retry_attempt=int_or_none(fact("retry_attempt")) or 0,
        retry_terminal=fact("retry_terminal") is True,
        workspace_num=int_or_none(summary.get("workspace_num")),
        agent_clan=optional_str(summary.get("agent_clan")),
        agent_clan_generation=optional_str(summary.get("agent_clan_generation")),
        clan_tribe=optional_str(summary.get("clan_tribe")),
        tribe=optional_str(summary.get("tribe")),
        monitor_id=monitor_id,
        monitor_state=monitor_state,
        monitor_command=optional_str(fact("monitor_command")),
        monitor_label=optional_str(fact("monitor_label")),
        monitor_start_status=_shell_status(
            fact("shell_start_status"),
            is_shell=is_monitor,
            fallback=_shell_pair_status(
                status, is_shell=is_monitor, active=monitor_state == "running"
            ),
        ),
        monitor_stop_status=_shell_status(
            fact("shell_stop_status"),
            is_shell=is_monitor,
            fallback=_shell_pair_status(
                status, is_shell=is_monitor, active=monitor_state != "running"
            ),
        ),
        gate_id=gate_id,
        gate_kind=optional_str(fact("gate_kind")),
        gate_state=gate_state,
        gate_label=optional_str(fact("gate_label")),
        gate_accent=optional_str(fact("gate_accent")),
        gate_start_status=_shell_status(
            fact("shell_start_status"),
            is_shell=is_gate,
            fallback=_shell_pair_status(
                status, is_shell=is_gate, active=gate_state == "pending"
            ),
        ),
        gate_stop_status=_shell_status(
            fact("shell_stop_status"),
            is_shell=is_gate,
            fallback=_shell_pair_status(
                status, is_shell=is_gate, active=gate_state != "pending"
            ),
        ),
        proc_id=proc_id,
        proc_status=optional_str(fact("proc_status")) if is_proc else None,
        proc_label=optional_str(fact("proc_label")) if is_proc else None,
        queue_weight=(
            None
            if summary.get("queue_weight_invalid") is True
            else queue_weight(summary)
        ),
        queue_weight_explicit=summary.get("queue_weight_explicit") is True,
        queue_weight_invalid=summary.get("queue_weight_invalid") is True,
        queue_weight_error=optional_str(summary.get("queue_weight_error")),
    )
    if owner_resolved:
        _apply_gate_member_status(agent, shipped_gate_id=optional_str(fact("gate_id")))
    agent.set_queue_capacity(
        int_or_none(summary.get("queue_capacity")),
        explicit=summary.get("queue_capacity_explicit") is True,
    )
    return agent


def _apply_gate_member_status(agent: Agent, *, shipped_gate_id: str | None) -> None:
    """Mirror ``apply_gate_meta``: a real gate member shows its gate status."""
    if shipped_gate_id is None or not is_real_gate_member(
        agent.agent_family_role, shipped_gate_id
    ):
        return
    state = agent.gate_state or "pending"
    pair = gate_status_pair(agent.gate_start_status, agent.gate_stop_status)
    if gate_state_is_terminal(state):
        agent.status = pair.stop or pair.start or state
    else:
        agent.status = pair.start or state
    agent.status_bucket = gate_member_status_bucket(state, agent.status)


def _shell_pair_status(status: str, *, is_shell: bool, active: bool) -> str | None:
    if not is_shell or not active or status in _COARSE_REMOTE_STATUSES:
        return None
    return status


def _shell_status(
    shipped: object, *, is_shell: bool, fallback: str | None
) -> str | None:
    """Prefer the owner's shipped shell status; keep the derived degraded path."""
    if not is_shell:
        return None
    return optional_str(shipped) or fallback


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _local_time(value: object) -> datetime | None:
    timestamp = float_or_none(value)
    if timestamp is None:
        return None
    try:
        return to_local(datetime.fromtimestamp(timestamp, tz=UTC))
    except (OSError, OverflowError, ValueError):
        return None


def _local_times(values: object) -> list[datetime]:
    if not isinstance(values, list):
        return []
    return [parsed for value in values if (parsed := _local_time(value)) is not None]
