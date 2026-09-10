"""Query-row adapter for the live Agents tab."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sase.agent.status_buckets import _NEEDS_INPUT_STATUSES, _STOPPED_STATUSES
from sase.ace.query.profile_evaluator import ProfileFieldValue
from sase.core.agent_types import AgentIdentity, AgentType
from sase.core.time import get_timezone, local_now

from ._agent_time_intervals import leaf_runtime_interval
from .agent_source import agent_source

if TYPE_CHECKING:
    from .agent import Agent

_PINNED_TRIBE = "pinned"
_MACHINE_KEYS = (
    "machine",
    "machine_name",
    "hostname",
    "host_name",
    "host",
)


class _ContentCache(Protocol):
    def get_haystack(self, agent: Agent) -> str: ...


def agent_live_query_entry(
    agent: Agent,
    *,
    content_cache: _ContentCache | None = None,
    unread_agent_ids: Collection[AgentIdentity] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the profile-query row entry for one live Agents-tab row."""

    reference = now if now is not None else local_now()
    status = _status(agent.status)
    content = _content_text(agent, content_cache)
    metadata = _metadata_values(agent)
    text_values = _distinct(*metadata, content)
    fields: dict[str, ProfileFieldValue | tuple[ProfileFieldValue, ...]] = {}

    _add_field(fields, "name", _name_values(agent))
    _add_field(fields, "kind", _kind_values(agent))
    _add_field(fields, "family", _family_values(agent))
    _add_field(fields, "clan", _clan_values(agent))
    _add_field(fields, "project", _project_values(agent))
    _add_field(fields, "role", _role_values(agent))
    _add_field(fields, "workflow", _workflow_values(agent))
    _add_field(fields, "model", _normalized_text(agent.model))
    _add_field(fields, "provider", _normalized_lower(agent.llm_provider))
    _add_field(fields, "status", status)
    _add_field(fields, "attempt", agent.retry_attempt)
    _add_field(fields, "hidden", bool(agent.hidden))
    _add_field(fields, "attention", status in _STOPPED_STATUSES)
    _add_field(fields, "retry", _is_retrying(agent))
    _add_field(fields, "machine", _machine_values(agent))
    _add_field(fields, "tribe", _tribe_values(agent))
    _add_field(fields, "pinned", agent.tribe == _PINNED_TRIBE)
    _add_field(fields, "unread", agent.identity in unread_agent_ids)
    _add_field(fields, "needs", ("input",) if status in _NEEDS_INPUT_STATUSES else ())
    _add_field(fields, "source", agent_source(agent))
    start_epoch = _epoch_seconds(agent.start_time)
    if start_epoch is not None:
        _add_field(fields, "since", start_epoch)
        _add_field(fields, "until", start_epoch)
    finish_epoch = _epoch_seconds(agent.stop_time)
    if finish_epoch is not None:
        _add_field(fields, "after", finish_epoch)
        _add_field(fields, "before", finish_epoch)
    runtime = _runtime_seconds(agent, now=reference)
    if runtime is not None:
        _add_field(fields, "min", runtime)
        _add_field(fields, "max", runtime)
    _add_field(fields, "cl", agent.cl_name)
    _add_field(fields, "text", text_values)

    return {
        "stable_id": agent_live_query_row_id(agent),
        "fields": fields,
        "searchable_text": "\n".join(str(value) for value in text_values),
        "predicates": (),
    }


def agent_live_query_row_id(agent: Agent) -> str:
    """Return the stable query row id for one live Agents-tab row."""

    for value in (agent.agent_name, agent.presented_identity_name):
        text = _normalized_text(value)
        if text:
            return text
    identity_type, cl_name, raw_suffix = agent.identity
    return ":".join((identity_type.value, cl_name, raw_suffix or ""))


def _name_values(agent: Agent) -> tuple[str, ...]:
    return _distinct(
        agent.agent_name,
        agent.presented_identity_name,
        agent.presented_agent_name,
        agent.display_name,
    )


def _kind_values(agent: Agent) -> tuple[str, ...]:
    if agent.is_clan_container:
        return ("clan",)
    if agent.is_family_container_row:
        return ("family",)
    kinds: list[str] = []
    if agent.is_child_row:
        kinds.append("member")
    elif agent.agent_type is AgentType.WORKFLOW:
        kinds.append("workflow")
    else:
        kinds.append("agent")
    if agent.is_workflow_step_child:
        kinds.append("workflow-child")
    elif agent.agent_type is AgentType.WORKFLOW and agent.is_child_row:
        kinds.append("workflow")
    return tuple(kinds)


def _family_values(agent: Agent) -> tuple[str, ...]:
    inferred = _family_from_name(agent.agent_name)
    values = [agent.agent_family, inferred]
    if agent.agent_family or agent.is_family_root_entry:
        values.append(agent.presented_family_reference_name())
    return _distinct(*values)


def _family_from_name(name: str | None) -> str | None:
    if not name:
        return None
    for separator in ("--", "."):
        if separator not in name:
            continue
        base, suffix = name.rsplit(separator, 1)
        if base and suffix in {"code", "plan", "mon", "gate"}:
            return base
    return None


def _clan_values(agent: Agent) -> tuple[str, ...]:
    return _distinct(
        agent.agent_clan,
        agent.cl_name if agent.is_clan_container else None,
        agent.presented_clan_reference_name() if agent.agent_clan else None,
    )


def _project_values(agent: Agent) -> tuple[str, ...]:
    return _distinct(
        _project_basename(agent.project_file),
        agent.project_display_name,
        *_project_locator_values(agent.fleet_logical_locator),
        *_project_locator_values(agent.fleet_exact_locator),
    )


def _project_basename(project_file: str | None) -> str | None:
    if not project_file:
        return None
    return Path(project_file).parent.name or None


def _project_locator_values(locator: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not locator:
        return ()
    project = locator.get("project")
    if isinstance(project, Mapping):
        return _distinct(project.get("project_id"), project.get("name"))
    return _distinct(project)


def _role_values(agent: Agent) -> tuple[str, ...]:
    return _distinct(
        _normalized_role(agent.agent_family_role),
        _normalized_role(agent.role_suffix),
        _role_from_name(agent.agent_name),
    )


def _normalized_role(value: str | None) -> str | None:
    text = _normalized_text(value)
    if not text:
        return None
    normalized = text.removeprefix("--").removeprefix("-").removeprefix(".")
    if not normalized or normalized == "root" or normalized.isdigit():
        return None
    if normalized == "monitor":
        return "mon"
    return normalized


def _role_from_name(name: str | None) -> str | None:
    if not name:
        return None
    for separator in ("--", "."):
        if separator not in name:
            continue
        suffix = name.rsplit(separator, 1)[1]
        if suffix in {"code", "plan", "mon", "gate"}:
            return suffix
    return None


def _workflow_values(agent: Agent) -> tuple[str, ...]:
    return _distinct(
        agent.workflow, agent.parent_workflow, agent.embedded_workflow_name
    )


def _machine_values(agent: Agent) -> tuple[str, ...]:
    alias = _normalized_text(agent.fleet_origin_alias)
    return _distinct(
        alias or "here",
        *_machine_locator_values(agent.fleet_logical_locator),
        *_machine_locator_values(agent.fleet_exact_locator),
        agent.source_machine,
    )


def _machine_locator_values(locator: Mapping[str, Any] | None) -> tuple[str, ...]:
    if not locator:
        return ()
    values: list[object] = []
    for key in _MACHINE_KEYS:
        value = locator.get(key)
        if not isinstance(value, Mapping):
            values.append(value)
    for nested_key in ("host", "origin", "machine"):
        nested = locator.get(nested_key)
        if isinstance(nested, Mapping):
            values.extend(nested.get(key) for key in _MACHINE_KEYS)
    return _distinct(*values)


def _tribe_values(agent: Agent) -> tuple[str, ...]:
    return _distinct(agent.tribe, agent.clan_tribe, *agent.clan_tribes)


def _is_retrying(agent: Agent) -> bool:
    return bool(
        agent.retry_attempt > 0
        or agent.retry_of_timestamp
        or agent.retried_as_timestamp
        or agent.retry_chain_root_timestamp
    )


def _epoch_seconds(value: datetime | None) -> int | None:
    if value is None:
        return None
    timestamp = value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=get_timezone())
    return int(timestamp.timestamp())


def _runtime_seconds(agent: Agent, *, now: datetime) -> int | None:
    interval = leaf_runtime_interval(agent, now)
    if interval is None:
        return None
    return max(0, int(interval.elapsed_seconds))


def _metadata_values(agent: Agent) -> tuple[str, ...]:
    return _distinct(
        agent.cl_name,
        agent.display_name,
        agent.agent_name,
        agent.status,
    )


def _content_text(agent: Agent, content_cache: _ContentCache | None) -> str | None:
    if content_cache is None:
        return None
    return _normalized_text(content_cache.get_haystack(agent))


def _status(value: str | None) -> str | None:
    text = _normalized_text(value)
    return text.upper() if text else None


def _normalized_lower(value: str | None) -> str | None:
    text = _normalized_text(value)
    return text.casefold() if text else None


def _normalized_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _add_field(
    fields: dict[str, ProfileFieldValue | tuple[ProfileFieldValue, ...]],
    key: str,
    value: ProfileFieldValue | Iterable[ProfileFieldValue] | None,
) -> None:
    if value is None:
        return
    values: tuple[ProfileFieldValue, ...]
    if isinstance(value, (str, bool, int)):
        values = (value,)
    else:
        values = tuple(value)
    present = tuple(item for item in values if _field_value_present(item))
    if present:
        fields[key] = present


def _field_value_present(value: ProfileFieldValue) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _distinct(*values: object) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _normalized_text(value)
        if text is None:
            continue
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        result.append(text)
    return tuple(result)


__all__ = ["agent_live_query_entry", "agent_live_query_row_id"]
