"""Builds Agent rows from federation fleet summary payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
    queue_weight,
    status_bucket_from_wire,
    status_from_summary,
)
from .agent import Agent, AgentType

__all__ = ["HostFeedIssue", "host_feed_issues", "rows_from_response"]


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
    role_suffix = optional_str(summary.get("role_suffix")) or role_suffix_from_name(
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
    status = status_from_summary(
        summary,
        lifecycle,
        liveness,
        attention,
        lifecycle_token=summary.get("lifecycle"),
        liveness_token=liveness_token,
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
    # The wire carries one owner-resolved "started" moment (preferring the
    # actual run start over the launch/queue time; see sase-core
    # started_at_unix_for_record). Remote rows have no separate queued-vs
    # -running signal to split it further, so it doubles as both
    # ``start_time`` and ``run_start_time`` -- the latter is what
    # ``leaf_runtime_interval`` needs to compute an active row's elapsed
    # duration instead of rendering ``0s``.
    run_start_time = start_time
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
    gate_id = optional_str(summary.get("gate_id"))
    if is_gate and gate_id is None:
        gate_id = shell_id
    monitor_id = optional_str(summary.get("monitor_id"))
    if is_monitor and monitor_id is None:
        monitor_id = shell_id
    proc_id = optional_str(summary.get("proc_id")) if is_proc else None
    if is_proc and proc_id is None:
        proc_id = shell_id
    agent = Agent(
        agent_type=AgentType.PROC_SHELL if is_proc else AgentType.RUNNING,
        cl_name=patch_name_value,
        project_file=project_file_value,
        status=status,
        status_bucket=status_bucket,
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
        reasoning_effort=optional_str(
            summary.get("reasoning_effort"),
        ),
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
        agent_family_role=family_role,
        agent_family_parallel=bool(summary.get("agent_family_parallel")),
        parent_timestamp=parent_timestamp,
        plan_chain_root=bool(summary.get("plan_chain_root")),
        workspace_num=int_or_none(summary.get("workspace_num")),
        agent_clan=optional_str(summary.get("agent_clan")),
        agent_clan_generation=optional_str(summary.get("agent_clan_generation")),
        clan_tribe=optional_str(summary.get("clan_tribe")),
        tribe=optional_str(summary.get("tribe")),
        monitor_id=monitor_id,
        monitor_state=optional_str(summary.get("monitor_state")),
        monitor_command=optional_str(summary.get("monitor_command")),
        monitor_label=optional_str(summary.get("monitor_label")),
        gate_id=gate_id,
        gate_kind=optional_str(summary.get("gate_kind")),
        gate_state=optional_str(summary.get("gate_state")),
        gate_label=optional_str(summary.get("gate_label")),
        proc_id=proc_id,
        proc_status=optional_str(summary.get("proc_status")) if is_proc else None,
        proc_label=optional_str(summary.get("proc_label")) if is_proc else None,
        queue_weight=(
            None
            if summary.get("queue_weight_invalid") is True
            else queue_weight(summary)
        ),
        queue_weight_explicit=summary.get("queue_weight_explicit") is True,
        queue_weight_invalid=summary.get("queue_weight_invalid") is True,
        queue_weight_error=optional_str(summary.get("queue_weight_error")),
    )
    agent.set_queue_capacity(
        int_or_none(summary.get("queue_capacity")),
        explicit=summary.get("queue_capacity_explicit") is True,
    )
    return agent
