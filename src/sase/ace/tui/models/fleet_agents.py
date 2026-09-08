"""Adapters from federation fleet summaries to Agents-tab rows."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sase.core.time import local_now
from sase.dispatch.follow_store import FollowStoreSnapshot

from .agent import Agent, AgentType


@dataclass(frozen=True)
class FleetRowsProjection:
    """TUI-ready fleet rows plus safe status metadata."""

    focus_rows: tuple[Agent, ...] = ()
    fleet_rows: tuple[Agent, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    configured_host_count: int = 0
    partial: bool = False
    counts: dict[str, Any] = field(default_factory=dict)


def project_fleet_agents(
    *,
    summary_response: Mapping[str, Any] | None = None,
    catalog_response: Mapping[str, Any] | None = None,
    followed_response: Mapping[str, Any] | None = None,
    attention_response: Mapping[str, Any] | None = None,
    follow_snapshot: FollowStoreSnapshot | None = None,
    local_agent_count: int = 0,
) -> FleetRowsProjection:
    """Project federation responses into Focus and Fleet Agent rows."""
    active_keys, active_locator_ids = _active_follow_state(follow_snapshot)
    diagnostics = [
        *_diagnostics_from_response(summary_response),
        *_diagnostics_from_response(catalog_response),
        *_diagnostics_from_response(followed_response),
        *_diagnostics_from_response(attention_response),
    ]
    attention_by_logical_key = _attention_by_logical_key(attention_response)
    fleet_source = catalog_response or summary_response
    fleet_rows = tuple(
        _dedupe_rows(
            _rows_from_response(
                fleet_source,
                active_keys=active_keys,
                active_locator_ids=active_locator_ids,
                followed_only=False,
                attention_by_logical_key=attention_by_logical_key,
            )
        )
    )
    followed_source = followed_response or summary_response
    focus_rows = tuple(
        _dedupe_rows(
            _rows_from_response(
                followed_source,
                active_keys=active_keys,
                active_locator_ids=active_locator_ids,
                followed_only=True,
                attention_by_logical_key=attention_by_logical_key,
            )
        )
    )
    host_count = max(
        _host_count(summary_response),
        _host_count(catalog_response),
        _host_count(followed_response),
    )
    fallback_counts: dict[str, Any] = {
        "local": local_agent_count,
        "focus_remote": len(focus_rows),
        "focus_total": local_agent_count + len(focus_rows),
        "fleet": len(fleet_rows),
        "hosts": host_count,
    }
    counts = _rust_counts_or_fallback(
        fallback_counts,
        followed_response=followed_response,
        fleet_response=fleet_source,
    )
    return FleetRowsProjection(
        focus_rows=focus_rows,
        fleet_rows=fleet_rows,
        diagnostics=tuple(diagnostics),
        configured_host_count=host_count,
        partial=any(
            bool(response and response.get("partial"))
            for response in (
                summary_response,
                catalog_response,
                followed_response,
                attention_response,
            )
        ),
        counts=counts,
    )


def followed_logical_locators(
    snapshot: FollowStoreSnapshot | None,
) -> tuple[dict[str, Any], ...]:
    """Return active logical locators for a followed-batch request."""
    if snapshot is None:
        return ()
    locators: list[dict[str, Any]] = []
    for record in snapshot.active_records:
        locator = record.get("logical_locator")
        if isinstance(locator, Mapping):
            locators.append(dict(locator))
    return tuple(locators)


def followed_logical_keys(
    snapshot: FollowStoreSnapshot | None,
) -> tuple[str, ...]:
    """Return active logical keys for a bounded attention read."""
    if snapshot is None:
        return ()
    keys: list[str] = []
    for record in snapshot.active_records:
        key = record.get("logical_key")
        if isinstance(key, str) and key:
            keys.append(key)
    return tuple(keys)


def followed_batch_family_promotions(
    snapshot: FollowStoreSnapshot | None,
    followed_response: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    """Derive safe singleton-to-family follow promotions from hydrated rows."""
    if (
        snapshot is None
        or followed_response is None
        or followed_response.get("disabled")
    ):
        return ()

    family_locators = _family_locators_by_identity(followed_response)
    if not family_locators:
        return ()

    promotions: list[dict[str, Any]] = []
    promoted_sources: set[str] = set()
    for record in snapshot.active_records:
        if record.get("created_by") != "explicit":
            continue
        source = _mapping(record.get("logical_locator"))
        if not source or _locator_family_id(source):
            continue
        source_identity = _promotion_identity(source)
        if source_identity is None:
            continue
        matches = family_locators.get(source_identity)
        if matches is None or len(matches) != 1:
            continue
        target = next(iter(matches.values()))
        source_id = _locator_id(source)
        if source_id in promoted_sources or source_id == _locator_id(target):
            continue
        promotions.append(
            {
                "schema_version": 1,
                "from": dict(source),
                "to": dict(target),
            }
        )
        promoted_sources.add(source_id)
    return tuple(promotions)


def _rows_from_response(
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
    for host_index, host in enumerate(_host_payloads(response)):
        host_alias = _host_alias(host, host_index)
        origin = _mapping(host.get("origin"))
        origin_installation_id = _optional_str(
            host.get("origin_installation_id"),
            origin.get("installation_id"),
            origin.get("id"),
        )
        host_freshness = _optional_str(host.get("freshness"), host.get("status"))
        host_health = _optional_str(
            host.get("connection_health"),
            host.get("health"),
            host.get("state"),
        )
        observed_at = _float_or_none(
            host.get("observed_at_unix"),
            host.get("observed_at"),
        )
        for summary_index, summary in enumerate(_summary_payloads(host)):
            agent = _agent_from_summary(
                summary,
                host_alias=host_alias,
                origin_installation_id=origin_installation_id,
                host_freshness=host_freshness,
                host_health=host_health,
                observed_at_unix=observed_at,
                summary_index=summary_index,
                attention_by_logical_key=attention_by_logical_key,
            )
            followed = _summary_followed(agent, active_keys, active_locator_ids)
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
    observed_at_unix: float | None,
    summary_index: int,
    attention_by_logical_key: Mapping[str, Mapping[str, Any]],
) -> Agent:
    content = _mapping(summary.get("content"))
    lifecycle = _mapping(summary.get("lifecycle"))
    liveness = _mapping(summary.get("liveness"))
    logical_locator = _mapping(summary.get("logical_locator"))
    exact_locator = _mapping(summary.get("exact_locator"))
    logical_key = _optional_str(summary.get("logical_key"))
    exact_key = _optional_str(summary.get("exact_key"))
    agent_name = _agent_name(summary, content, logical_key, exact_key, summary_index)
    patch_name = _patch_name(summary, content, logical_locator, agent_name)
    raw_suffix = _raw_suffix(
        host_alias,
        exact_key or logical_key or _locator_id(exact_locator or logical_locator),
        summary_index,
    )
    attention = attention_by_logical_key.get(logical_key) if logical_key else None
    status = _status_from_summary(summary, lifecycle, liveness, attention)
    revision = _int_or_none(
        summary.get("revision"),
        lifecycle.get("revision"),
        content.get("revision"),
    )
    start_time = _datetime_from_unix(
        summary.get("started_at_unix"),
        summary.get("start_time_unix"),
        lifecycle.get("started_at_unix"),
        content.get("started_at_unix"),
        observed_at_unix,
    )
    stop_time = _datetime_from_unix(
        summary.get("stopped_at_unix"),
        summary.get("finished_at_unix"),
        lifecycle.get("stopped_at_unix"),
        content.get("stopped_at_unix"),
    )
    freshness = _optional_str(
        summary.get("freshness"),
        lifecycle.get("freshness"),
        host_freshness,
    )
    health = _optional_str(
        summary.get("connection_health"),
        liveness.get("connection_health"),
        host_health,
    )
    bounded_intent = _optional_str(
        content.get("bounded_intent"),
        content.get("intent"),
        summary.get("bounded_intent"),
    )
    capabilities = _mapping(summary.get("capabilities"))
    row_revision = _mapping(summary.get("row_revision"))
    if revision is None:
        revision = _int_or_none(row_revision.get("revision"))
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=patch_name,
        project_file=f"/fleet/{host_alias}/project.yml",
        status=status,
        start_time=start_time,
        stop_time=stop_time,
        raw_suffix=raw_suffix,
        agent_name=agent_name,
        model=_optional_str(content.get("model"), summary.get("model")),
        llm_provider=_optional_str(
            content.get("llm_provider"),
            content.get("provider"),
            summary.get("llm_provider"),
        ),
        reasoning_effort=_optional_str(
            content.get("reasoning_effort"),
            summary.get("reasoning_effort"),
        ),
        project_display_name=host_alias,
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
        fleet_attention=dict(attention) if attention else None,
    )
    return agent


def _host_payloads(response: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    hosts = response.get("hosts")
    if isinstance(hosts, Sequence) and not isinstance(hosts, (str, bytes, bytearray)):
        return tuple(host for host in hosts if isinstance(host, Mapping))
    if _summary_payloads(response):
        return (response,)
    result = response.get("result")
    if isinstance(result, Mapping):
        return _host_payloads(result)
    return ()


def _summary_payloads(host: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for key in ("summaries", "agents", "rows"):
        value = host.get(key)
        if isinstance(value, Sequence) and not isinstance(
            value,
            (str, bytes, bytearray),
        ):
            return tuple(item for item in value if isinstance(item, Mapping))
    result = host.get("result")
    if isinstance(result, Mapping):
        return _summary_payloads(result)
    return ()


def _attention_by_logical_key(
    response: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if response is None or response.get("disabled"):
        return result
    for host in _host_payloads(response):
        for entry in _attention_entries_from_host(host):
            logical_key = entry.get("logical_key")
            if not isinstance(logical_key, str) or not logical_key:
                continue
            existing = result.get(logical_key)
            if existing is None or (
                existing.get("state") != "pending" and entry.get("state") == "pending"
            ):
                result[logical_key] = dict(entry)
    return result


def _attention_entries_from_host(
    host: Mapping[str, Any],
) -> tuple[Mapping[str, Any], ...]:
    payload = host.get("payload")
    if isinstance(payload, Mapping):
        entries = payload.get("entries")
        if isinstance(entries, Sequence) and not isinstance(
            entries,
            (str, bytes, bytearray),
        ):
            return tuple(item for item in entries if isinstance(item, Mapping))
    result = host.get("result")
    if isinstance(result, Mapping):
        return _attention_entries_from_host(result)
    return ()


PromotionIdentity = tuple[str, str, str]


def _family_locators_by_identity(
    response: Mapping[str, Any],
) -> dict[PromotionIdentity, dict[str, dict[str, Any]]]:
    locators: dict[PromotionIdentity, dict[str, dict[str, Any]]] = {}
    for host in _host_payloads(response):
        for summary in _summary_payloads(host):
            locator = _mapping(summary.get("logical_locator"))
            if not locator or not _locator_family_id(locator):
                continue
            identity = _promotion_identity(locator)
            if identity is None:
                continue
            locators.setdefault(identity, {})[_locator_id(locator)] = dict(locator)
    return locators


def _promotion_identity(locator: Mapping[str, Any]) -> PromotionIdentity | None:
    project = _mapping(locator.get("project"))
    origin = _mapping(project.get("origin"))
    installation_id = _optional_str(
        origin.get("installation_id"),
        locator.get("origin_installation_id"),
        locator.get("installation_id"),
    )
    project_id = _optional_str(project.get("project_id"), locator.get("project_id"))
    agent_id = _optional_str(locator.get("agent_id"))
    if installation_id is None or project_id is None or agent_id is None:
        return None
    return (installation_id, project_id, agent_id)


def _locator_family_id(locator: Mapping[str, Any]) -> str | None:
    return _optional_str(locator.get("family_id"))


def _host_alias(host: Mapping[str, Any], host_index: int) -> str:
    origin = _mapping(host.get("origin"))
    alias = _optional_str(
        host.get("alias"),
        origin.get("alias"),
        origin.get("name"),
        origin.get("installation_id"),
        host.get("origin_installation_id"),
    )
    if alias:
        return _display_token(alias)
    return f"remote-{host_index + 1}"


def _agent_name(
    summary: Mapping[str, Any],
    content: Mapping[str, Any],
    logical_key: str | None,
    exact_key: str | None,
    summary_index: int,
) -> str:
    name = _optional_str(
        content.get("agent_name"),
        content.get("name"),
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
    content: Mapping[str, Any],
    logical_locator: Mapping[str, Any],
    agent_name: str,
) -> str:
    patch = _optional_str(
        content.get("patch"),
        content.get("patch_name"),
        content.get("cl_name"),
        summary.get("patch"),
        summary.get("patch_name"),
        logical_locator.get("patch"),
        logical_locator.get("patch_name"),
        logical_locator.get("project"),
    )
    return _display_token(patch or agent_name)


def _status_from_summary(
    summary: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    liveness: Mapping[str, Any],
    attention: Mapping[str, Any] | None = None,
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
    value = _optional_str(
        summary.get("status"),
        lifecycle.get("display_status"),
        lifecycle.get("status"),
        lifecycle.get("state"),
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
        "stopped": "STOPPED",
        "cancelled": "STOPPED",
        "canceled": "STOPPED",
        "starting": "STARTING",
    }
    if normalized not in status_map and bool(summary.get("needs_attention")):
        return "WAITING INPUT"
    return status_map.get(normalized, value.upper())


def _active_follow_state(
    snapshot: FollowStoreSnapshot | None,
) -> tuple[frozenset[str], frozenset[str]]:
    if snapshot is None:
        return frozenset(), frozenset()
    locator_ids = []
    for record in snapshot.active_records:
        locator = record.get("logical_locator")
        if isinstance(locator, Mapping):
            locator_ids.append(_locator_id(locator))
    return snapshot.active_logical_keys, frozenset(locator_ids)


def _summary_followed(
    agent: Agent,
    active_keys: frozenset[str],
    active_locator_ids: frozenset[str],
) -> bool:
    if agent.fleet_logical_key and agent.fleet_logical_key in active_keys:
        return True
    if agent.fleet_logical_locator:
        return _locator_id(agent.fleet_logical_locator) in active_locator_ids
    return False


def _dedupe_rows(rows: Sequence[Agent]) -> list[Agent]:
    deduped: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for row in rows:
        if row.identity in seen:
            continue
        deduped.append(row)
        seen.add(row.identity)
    return deduped


def _diagnostics_from_response(
    response: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    if response is None:
        return ()
    diagnostics = response.get("diagnostics")
    if not isinstance(diagnostics, Sequence) or isinstance(
        diagnostics,
        (str, bytes, bytearray),
    ):
        return ()
    return tuple(dict(item) for item in diagnostics if isinstance(item, Mapping))


def _host_count(response: Mapping[str, Any] | None) -> int:
    if response is None:
        return 0
    configured = response.get("configured_hosts")
    if isinstance(configured, int) and configured >= 0:
        return configured
    hosts = _host_payloads(response)
    return len(hosts)


def _rust_counts_or_fallback(
    fallback: dict[str, Any],
    *,
    followed_response: Mapping[str, Any] | None,
    fleet_response: Mapping[str, Any] | None,
) -> dict[str, Any]:
    followed_hosts = _host_payloads(followed_response) if followed_response else ()
    fleet_hosts = _host_payloads(fleet_response) if fleet_response else ()
    if not followed_hosts and not fleet_hosts:
        return fallback
    try:
        from sase.dispatch.counts import count_focus_and_fleet

        wire = count_focus_and_fleet(
            {
                "schema_version": 1,
                "local_summaries": [],
                "followed_remote_hosts": [dict(host) for host in followed_hosts],
                "fleet_hosts": [dict(host) for host in fleet_hosts],
            }
        )
    except Exception:
        return fallback

    counts = dict(fallback)
    counts["wire"] = wire
    focus_running = _nested_count(wire, "focus")
    fleet_running = _nested_count(wire, "fleet")
    if focus_running is not None:
        counts["focus_remote"] = focus_running
        counts["focus_total"] = int(fallback.get("local", 0)) + focus_running
    if fleet_running is not None:
        counts["fleet"] = fleet_running
    return counts


def _nested_count(wire: Mapping[str, Any], key: str) -> int | None:
    section = wire.get(key)
    if not isinstance(section, Mapping):
        return None
    counts = section.get("counts")
    if not isinstance(counts, Mapping):
        return None
    running = counts.get("running")
    return running if isinstance(running, int) else None


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _optional_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return None


def _float_or_none(*values: object) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _int_or_none(*values: object) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str) and value.strip():
            try:
                return int(value)
            except ValueError:
                continue
    return None


def _datetime_from_unix(*values: object) -> datetime | None:
    timestamp = _float_or_none(*values)
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=local_now().tzinfo)
    except (OSError, OverflowError, ValueError):
        return None


def _locator_id(locator: Mapping[str, Any]) -> str:
    try:
        return json.dumps(dict(locator), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return repr(sorted((str(key), repr(value)) for key, value in locator.items()))


def _raw_suffix(host_alias: str, key: str | None, summary_index: int) -> str:
    suffix_key = key or f"row-{summary_index + 1}"
    return f"fleet:{host_alias}:{suffix_key}"


def _display_token(value: str) -> str:
    token = value.strip().replace("/", ":")
    return token or "fleet"


__all__ = [
    "FleetRowsProjection",
    "followed_batch_family_promotions",
    "followed_logical_keys",
    "followed_logical_locators",
    "project_fleet_agents",
]
