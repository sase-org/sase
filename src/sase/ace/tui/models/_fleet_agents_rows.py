"""Builds Agent rows from federation fleet summary payloads."""

from __future__ import annotations

import math
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
        viewer_freshness = _viewer_observed_freshness(host)
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
        host_rows: list[Agent] = []
        host_summary_pairs: list[tuple[Mapping[str, Any], Agent]] = []
        for summary_index, summary in enumerate(summary_payloads(host)):
            agent = _agent_from_summary(
                summary,
                host_alias=host_alias,
                origin_installation_id=origin_installation_id,
                host_freshness=host_freshness,
                viewer_freshness=viewer_freshness,
                host_health=optional_str(host.get("status")),
                host_diagnostic=_host_diagnostic(host),
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
            host_rows.append(agent)
            host_summary_pairs.append((summary, agent))
        _resolve_host_parent_lineage(host_summary_pairs)
        rows.extend(host_rows)
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
    parent_timestamp = optional_str(summary.get("parent_timestamp"))
    family_name = _agent_family_name(
        summary,
        labels,
        logical_locator,
        family_role=family_role,
        parent_timestamp=parent_timestamp,
    )
    agent_name = _agent_name(
        summary,
        labels,
        logical_key,
        exact_key,
        summary_index,
    )
    role_suffix = optional_str(summary.get("role_suffix")) or _role_suffix_from_name(
        agent_name,
        family_role,
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
    liveness_token = summary.get("liveness")
    status = _status_from_summary(
        summary,
        lifecycle,
        liveness,
        attention,
        lifecycle_token=summary.get("lifecycle"),
        liveness_token=liveness_token,
    )
    status_bucket = _status_bucket_from_wire(summary.get("status_bucket"))
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
    freshness = _combine_freshness(
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
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=patch_name,
        project_file=project_file,
        status=status,
        status_bucket=status_bucket,
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
        role_suffix=role_suffix,
        agent_family=family_name,
        agent_family_role=family_role,
        agent_family_parallel=bool(summary.get("agent_family_parallel")),
        parent_timestamp=parent_timestamp,
        plan_chain_root=bool(summary.get("plan_chain_root")),
        monitor_id=optional_str(summary.get("monitor_id")),
        monitor_state=optional_str(summary.get("monitor_state")),
        monitor_command=optional_str(summary.get("monitor_command")),
        monitor_label=optional_str(summary.get("monitor_label")),
        gate_id=optional_str(summary.get("gate_id")),
        gate_kind=optional_str(summary.get("gate_kind")),
        gate_state=optional_str(summary.get("gate_state")),
        gate_label=optional_str(summary.get("gate_label")),
        proc_id=optional_str(summary.get("proc_id")) if row_kind == "proc" else None,
        proc_status=optional_str(summary.get("proc_status"))
        if row_kind == "proc"
        else None,
        proc_label=optional_str(summary.get("proc_label"))
        if row_kind == "proc"
        else None,
        queue_weight=(
            None
            if summary.get("queue_weight_invalid") is True
            else _queue_weight(summary)
        ),
        queue_weight_explicit=summary.get("queue_weight_explicit") is True,
        queue_weight_invalid=summary.get("queue_weight_invalid") is True,
        queue_weight_error=optional_str(summary.get("queue_weight_error")),
    )
    return agent


def _resolve_host_parent_lineage(
    summary_pairs: list[tuple[Mapping[str, Any], Agent]],
) -> None:
    """Map owner-local parent tokens to rendered host-qualified row ids."""
    by_owner_key: dict[str, str] = {}
    for summary, agent in summary_pairs:
        if not agent.raw_suffix:
            continue
        for key in _summary_owner_lineage_keys(summary):
            by_owner_key.setdefault(key, agent.raw_suffix)

    for _summary, agent in summary_pairs:
        raw_parent = agent.parent_timestamp
        if not raw_parent:
            continue
        resolved = by_owner_key.get(raw_parent)
        if resolved is None:
            # Unresolved lineage should not hide a row beneath a parent that
            # is outside this bounded fleet page. Keeping it top-level
            # preserves visibility while still carrying family_role/role query
            # metadata from the summary.
            agent.parent_timestamp = None
        else:
            agent.parent_timestamp = resolved


def _summary_owner_lineage_keys(summary: Mapping[str, Any]) -> tuple[str, ...]:
    logical_locator = mapping(summary.get("logical_locator"))
    exact_locator = mapping(summary.get("exact_locator"))
    nested_logical = mapping(exact_locator.get("logical"))
    keys = (
        summary.get("raw_suffix"),
        summary.get("timestamp"),
        summary.get("agent_timestamp"),
        summary.get("logical_key"),
        summary.get("exact_key"),
        logical_locator.get("agent_id"),
        nested_logical.get("agent_id"),
        exact_locator.get("run_id"),
        exact_locator.get("shell_id"),
    )
    seen: set[str] = set()
    result: list[str] = []
    for key in keys:
        value = optional_str(key)
        if value is None or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


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


def _agent_family_name(
    summary: Mapping[str, Any],
    labels: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
    *,
    family_role: str | None,
    parent_timestamp: str | None,
) -> str | None:
    explicit = optional_str(summary.get("agent_family"))
    if explicit is not None:
        return explicit
    if family_role == "root" and parent_timestamp is None:
        return None
    return optional_str(labels.get("family_label"), logical_locator.get("family_id"))


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


def _role_suffix_from_name(
    agent_name: str | None, family_role: str | None
) -> str | None:
    if family_role in {None, "root", "historical_shell"} or not agent_name:
        return None
    for separator in ("--", "."):
        if separator not in agent_name:
            continue
        base, suffix = agent_name.rsplit(separator, 1)
        if base and suffix and not any(character.isspace() for character in suffix):
            return f"{separator}{suffix}"
    return None


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


def _queue_weight(summary: Mapping[str, Any]) -> float | None:
    weight = float_or_none(summary.get("queue_weight"))
    if weight is None or not math.isfinite(weight) or weight <= 0.0:
        return None
    return weight


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
    dead = _liveness_stops(liveness_token, liveness)
    if not value:
        return "WAS RUNNING" if dead else "RUNNING"
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
        # No row-scoped attention entry has arrived; fall back to the generic
        # remote-blocked status the owner's lifecycle/needs_attention signal
        # implies.
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
    resolved = status_map.get(normalized, value.upper())
    # Owner-resolved liveness overrides a stale RUNNING/STARTING claim: the
    # process is confirmed gone, so the row presents "was running" instead
    # of fabricating an active state. Never demote other statuses (a real
    # completion, failure, or pending-input pause stays as reported).
    if dead and resolved in {"RUNNING", "STARTING"}:
        return "WAS RUNNING"
    return resolved


_LIVENESS_STOPPED_VALUES = frozenset({"dead", "not_process"})


def _liveness_stops(liveness_token: object, liveness: Mapping[str, Any]) -> bool:
    """Whether owner-resolved liveness definitively rules out an active row.

    Mirrors sase-core's ``bucket_for_lifecycle`` liveness_stops predicate:
    only a definitively Dead/NotProcess liveness may demote a row. Alive or
    genuinely Unknown liveness never hides a potentially live agent.
    """
    value = optional_str(
        liveness_token if isinstance(liveness_token, str) else None,
        liveness.get("liveness"),
        liveness.get("status"),
        liveness.get("state"),
    )
    if not value:
        return False
    return value.casefold() in _LIVENESS_STOPPED_VALUES


_FLEET_STATUS_BUCKET_WIRE_MAP: dict[str, str] = {
    "stopped": "Stopped",
    "failed": "Failed",
    "starting": "Starting",
    "running": "Running",
    "queued": "Queued",
    "waiting": "Waiting",
    "done": "Done",
}


def _status_bucket_from_wire(value: object) -> str | None:
    """Map the wire's liveness-aware ``status_bucket`` to a display bucket.

    The wire enum is a deliberate 1:1 mirror of
    ``sase.agent.status_buckets.AGENT_STATUS_BUCKETS``, so setting
    ``Agent.status_bucket`` from it overrides the local text-derived bucket
    fallback everywhere that already consults ``agent_status_bucket()``
    (banners, folding, filters) with the owner's liveness-aware bucket.
    """
    if not isinstance(value, str):
        return None
    return _FLEET_STATUS_BUCKET_WIRE_MAP.get(value.casefold())


_FRESHNESS_RANK: dict[str, int] = {"fresh": 0, "aging": 1, "stale": 2, "unknown": 3}
# Owner-side snapshot freshness thresholds (sase-core
# FLEET_SNAPSHOT_FRESH_SECONDS / FLEET_SNAPSHOT_STALE_SECONDS), reused here
# for the viewer's own cache-age classification so both sides agree on what
# "fresh" means.
_FLEET_VIEWER_FRESH_SECONDS = 5.0
_FLEET_VIEWER_STALE_SECONDS = 60.0


def _combine_freshness(*values: str | None) -> str | None:
    """Return the least-fresh of the given freshness labels.

    A row must never look fresher than the worst signal available: an
    honestly-stamped owner freshness can still be undercut by a viewer-side
    cache serving an aged copy of that same payload.
    """
    ranked = [value for value in values if value in _FRESHNESS_RANK]
    if not ranked:
        for value in values:
            if value:
                return value
        return None
    return max(ranked, key=lambda value: _FRESHNESS_RANK[value])


def _viewer_observed_freshness(host: Mapping[str, Any]) -> str | None:
    """Classify the viewer's own cache age for *host*, or ``None`` when live.

    ``cached`` marks a response the federation worker served from its local
    cache rather than a live fetch; ``age_seconds`` is how long ago that
    cached copy was fetched. A live (non-cached) response carries no viewer
    cache age to fold in.
    """
    if not bool(host.get("cached")):
        return None
    age_seconds = float_or_none(host.get("age_seconds"))
    from sase.dispatch.counts import classify_cache_freshness

    decision = classify_cache_freshness(
        {
            "schema_version": 1,
            "viewer_monotonic_elapsed_seconds": age_seconds,
            "fresh_threshold_seconds": _FLEET_VIEWER_FRESH_SECONDS,
            "stale_threshold_seconds": _FLEET_VIEWER_STALE_SECONDS,
        }
    )
    return optional_str(decision.get("freshness"))
