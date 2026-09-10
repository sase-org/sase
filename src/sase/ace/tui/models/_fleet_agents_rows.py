"""Builds Agent rows from federation fleet summary payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._fleet_agents_follow import summary_followed
from ._fleet_agents_payload import host_payloads, summary_payloads
from ._fleet_agents_scalars import (
    datetime_from_unix,
    display_token,
    float_or_none,
    int_or_none,
    locator_id,
    mapping,
    optional_str,
    raw_suffix,
)
from .agent import Agent, AgentType


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
        host_alias = _host_alias(host, host_index)
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
        observed_at = float_or_none(
            host.get("observed_at_unix"),
            host.get("observed_at"),
        )
        for summary_index, summary in enumerate(summary_payloads(host)):
            agent = _agent_from_summary(
                summary,
                host_alias=host_alias,
                origin_installation_id=origin_installation_id,
                host_freshness=host_freshness,
                host_health=optional_str(host.get("status")),
                host_diagnostic=_host_diagnostic(host),
                observed_at_unix=observed_at,
                summary_index=summary_index,
                attention_by_logical_key=attention_by_logical_key,
            )
            followed = summary_followed(agent, active_keys, active_locator_ids)
            agent.fleet_followed = followed
            if followed_only and not followed:
                continue
            rows.append(agent)
    return rows


def _agent_from_summary(
    summary: Mapping[str, Any],
    *,
    host_alias: str,
    origin_installation_id: str | None,
    host_freshness: str | None,
    host_health: str | None,
    host_diagnostic: str | None,
    observed_at_unix: float | None,
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
    agent_name = _agent_name(
        summary,
        labels,
        logical_key,
        exact_key,
        summary_index,
    )
    patch_name = _patch_name(
        summary,
        labels,
        logical_locator,
        agent_name,
    )
    project_display_name = _project_display_name(summary, labels, logical_locator)
    project_file = _project_file(logical_locator, project_display_name)
    raw_suffix_value = raw_suffix(
        host_alias,
        exact_key or logical_key or locator_id(exact_locator or logical_locator),
        summary_index,
    )
    attention = attention_by_logical_key.get(logical_key) if logical_key else None
    status = _status_from_summary(
        summary,
        lifecycle,
        liveness,
        attention,
        lifecycle_token=summary.get("lifecycle"),
        liveness_token=summary.get("liveness"),
    )
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
    freshness = optional_str(
        summary.get("freshness"),
        host_freshness,
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
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=patch_name,
        project_file=project_file,
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        raw_suffix=raw_suffix_value,
        agent_name=agent_name,
        model=optional_str(summary.get("model")),
        llm_provider=optional_str(
            summary.get("provider"),
            summary.get("llm_provider"),
        ),
        reasoning_effort=optional_str(
            summary.get("reasoning_effort"),
        ),
        project_display_name=project_display_name,
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
        fleet_capabilities=dict(capabilities) if capabilities else None,
        fleet_content=dict(content) if content else None,
        fleet_bounded_intent=bounded_intent,
        fleet_diagnostic=host_diagnostic,
        fleet_attention=dict(attention) if attention else None,
    )
    return agent


def _host_alias(host: Mapping[str, Any], host_index: int) -> str:
    origin = mapping(host.get("origin"))
    alias = optional_str(
        host.get("alias"),
        origin.get("alias"),
        origin.get("name"),
        host.get("installation_id"),
        origin.get("installation_id"),
        host.get("origin_installation_id"),
    )
    if alias:
        return display_token(alias)
    return f"remote-{host_index + 1}"


def _agent_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_key: str | None,
    exact_key: str | None,
    summary_index: int,
) -> str:
    name = optional_str(
        labels.get("agent_label"),
        summary.get("agent_label"),
        summary.get("agent_name"),
        summary.get("name"),
    )
    if name:
        return name
    key = exact_key or logical_key
    if key:
        return key.rsplit("/", 1)[-1].rsplit(":", 1)[-1] or key
    return f"remote-agent-{summary_index + 1}"


def _patch_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
    agent_name: str,
) -> str:
    project = logical_locator.get("project")
    project_id = project.get("project_id") if isinstance(project, Mapping) else project
    patch = optional_str(
        project_id,
        summary.get("patch"),
        summary.get("patch_name"),
        logical_locator.get("patch"),
        logical_locator.get("patch_name"),
        summary.get("project_name"),
        labels.get("project_label"),
    )
    return display_token(patch or agent_name)


def _project_display_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
) -> str:
    return display_token(
        optional_str(
            summary.get("project_name"),
            labels.get("project_label"),
            _logical_project_id(logical_locator),
        )
        or "fleet"
    )


def _project_file(
    logical_locator: Mapping[str, Any],
    project_display_name: str,
) -> str:
    project_id = _logical_project_id(logical_locator) or project_display_name
    return f"/fleet/{display_token(project_id)}/project.yml"


def _logical_project_id(logical_locator: Mapping[str, Any]) -> str | None:
    project = logical_locator.get("project")
    if isinstance(project, Mapping):
        return optional_str(project.get("project_id"))
    return optional_str(project)


def _host_diagnostic(host: Mapping[str, Any]) -> str | None:
    diagnostics = host.get("diagnostics")
    if not isinstance(diagnostics, list):
        return None
    for item in diagnostics:
        if not isinstance(item, Mapping):
            continue
        message = optional_str(item.get("message"), item.get("code"))
        if message:
            return message
    return None


def _status_from_summary(
    summary: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    liveness: Mapping[str, Any],
    attention: Mapping[str, Any] | None = None,
    *,
    lifecycle_token: object = None,
    liveness_token: object = None,
) -> str:
    # A correlated, still-pending attention entry is the most specific
    # signal available: it distinguishes a question from a gate the way a
    # bare lifecycle/needs_attention flag never can.
    if attention is not None and attention.get("state") == "pending":
        kind = attention.get("kind")
        if kind == "question":
            return "QUESTION"
        if kind == "gate":
            return "WAITING INPUT"
    value = optional_str(
        summary.get("status"),
        lifecycle_token if isinstance(lifecycle_token, str) else None,
        lifecycle.get("display_status"),
        lifecycle.get("status"),
        lifecycle.get("state"),
        liveness_token if isinstance(liveness_token, str) else None,
        liveness.get("status"),
        liveness.get("state"),
    )
    if not value:
        return "RUNNING"
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    status_map = {
        "active": "RUNNING",
        "alive": "RUNNING",
        "running": "RUNNING",
        "started": "RUNNING",
        "queued": "QUEUED",
        "pending": "QUEUED",
        "waiting": "WAITING",
        "waiting_input": "WAITING INPUT",
        "needs_input": "WAITING INPUT",
        "blocked": "WAITING INPUT",
        # No attention entry has arrived yet (or this row isn't followed, so
        # none was fetched at all); fall back to the generic remote-blocked
        # status the owner's own lifecycle/needs_attention signal implies.
        "asking": "WAITING INPUT",
        "failed": "FAILED",
        "error": "FAILED",
        "done": "DONE",
        "complete": "DONE",
        "completed": "DONE",
        "terminal": "DONE",
        "stopped": "STOPPED",
        "cancelled": "STOPPED",
        "canceled": "STOPPED",
        "starting": "STARTING",
    }
    if normalized not in status_map and bool(summary.get("needs_attention")):
        return "WAITING INPUT"
    return status_map.get(normalized, value.upper())
