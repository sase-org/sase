"""Wire records for indexed output-variable history queries.

Mirrors ``sase_core::agent_scan`` history types. The Python CLI builds a
request, the Rust binding executes one index query, and these records are
the only shape that crosses the facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.output_variable_values import VarValue
from sase.core.wire import known_field_kwargs

AGENT_OUTPUT_VARIABLE_HISTORY_WIRE_SCHEMA_VERSION = 1
DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT = 20
DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT = 5


@dataclass(frozen=True)
class AgentOutputVariableHistoryQueryWire:
    """Query knobs for grouped output-variable history."""

    projects: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    value_json: list[VarValue] = field(default_factory=list)
    since_timestamp: str | None = None
    until_timestamp: str | None = None
    include_hidden: bool = False
    key_limit: int = DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT
    value_limit: int = DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT
    reverse: bool = False


@dataclass(frozen=True)
class AgentOutputVariableLimitWire:
    """Effective limit and truncation metadata for one history dimension."""

    limit: int
    total_count: int
    returned_count: int
    truncated: bool


@dataclass(frozen=True)
class AgentOutputVariableOccurrenceWire:
    """One indexed output-variable occurrence."""

    artifact_dir: str
    project_name: str
    workflow_dir_name: str
    timestamp: str
    key: str
    value: VarValue
    value_json: str
    hidden: bool
    agent_name: str | None = None
    cl_name: str | None = None


@dataclass(frozen=True)
class AgentOutputVariableValueGroupWire:
    """One distinct typed value for a variable key."""

    value: VarValue
    value_json: str
    occurrence_count: int
    agent_count: int
    agents: list[str]
    projects: list[str]
    first_seen_timestamp: str
    last_seen_timestamp: str
    newest: AgentOutputVariableOccurrenceWire


@dataclass(frozen=True)
class AgentOutputVariableKeyGroupWire:
    """Grouped history for one output-variable key."""

    key: str
    occurrence_count: int
    distinct_value_count: int
    values_limit: AgentOutputVariableLimitWire
    values: list[AgentOutputVariableValueGroupWire]


@dataclass(frozen=True)
class AgentOutputVariableHistoryWire:
    """Grouped output-variable history returned by the artifact index."""

    schema_version: int
    index_path: str
    query: AgentOutputVariableHistoryQueryWire
    keys_limit: AgentOutputVariableLimitWire
    groups: list[AgentOutputVariableKeyGroupWire]


def agent_output_variable_history_query_to_dict(
    query: AgentOutputVariableHistoryQueryWire,
) -> dict[str, Any]:
    """Project a history query to the Rust binding dict shape."""
    return {
        "projects": list(query.projects),
        "agents": list(query.agents),
        "keys": list(query.keys),
        "values": list(query.values),
        "value_json": list(query.value_json),
        "since_timestamp": query.since_timestamp,
        "until_timestamp": query.until_timestamp,
        "include_hidden": query.include_hidden,
        "key_limit": int(query.key_limit),
        "value_limit": int(query.value_limit),
        "reverse": query.reverse,
    }


def agent_output_variable_history_from_dict(
    data: dict[str, Any],
) -> AgentOutputVariableHistoryWire:
    """Rehydrate a history response from the Rust binding dict."""
    raw_query = data.get("query")
    query = (
        _query_from_dict(raw_query)
        if isinstance(raw_query, dict)
        else AgentOutputVariableHistoryQueryWire()
    )
    raw_keys_limit = data.get("keys_limit")
    keys_limit = (
        _limit_from_dict(raw_keys_limit)
        if isinstance(raw_keys_limit, dict)
        else AgentOutputVariableLimitWire(0, 0, 0, False)
    )
    groups = [
        _key_group_from_dict(item)
        for item in data.get("groups") or []
        if isinstance(item, dict)
    ]
    return AgentOutputVariableHistoryWire(
        schema_version=int(
            data.get(
                "schema_version",
                AGENT_OUTPUT_VARIABLE_HISTORY_WIRE_SCHEMA_VERSION,
            )
        ),
        index_path=str(data.get("index_path") or ""),
        query=query,
        keys_limit=keys_limit,
        groups=groups,
    )


def _query_from_dict(data: dict[str, Any]) -> AgentOutputVariableHistoryQueryWire:
    kwargs = known_field_kwargs(AgentOutputVariableHistoryQueryWire, data)
    kwargs.setdefault("projects", [])
    kwargs.setdefault("agents", [])
    kwargs.setdefault("keys", [])
    kwargs.setdefault("values", [])
    kwargs.setdefault("value_json", [])
    kwargs.setdefault("include_hidden", False)
    kwargs.setdefault("key_limit", DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT)
    kwargs.setdefault("value_limit", DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT)
    kwargs.setdefault("reverse", False)
    kwargs["projects"] = [str(item) for item in kwargs["projects"]]
    kwargs["agents"] = [str(item) for item in kwargs["agents"]]
    kwargs["keys"] = [str(item) for item in kwargs["keys"]]
    kwargs["values"] = [str(item) for item in kwargs["values"]]
    kwargs["value_json"] = list(kwargs["value_json"])
    kwargs["include_hidden"] = bool(kwargs["include_hidden"])
    kwargs["key_limit"] = int(kwargs["key_limit"])
    kwargs["value_limit"] = int(kwargs["value_limit"])
    kwargs["reverse"] = bool(kwargs["reverse"])
    if kwargs.get("since_timestamp") is not None:
        kwargs["since_timestamp"] = str(kwargs["since_timestamp"])
    if kwargs.get("until_timestamp") is not None:
        kwargs["until_timestamp"] = str(kwargs["until_timestamp"])
    return AgentOutputVariableHistoryQueryWire(**kwargs)


def _limit_from_dict(data: dict[str, Any]) -> AgentOutputVariableLimitWire:
    return AgentOutputVariableLimitWire(
        limit=int(data.get("limit", 0)),
        total_count=int(data.get("total_count", 0)),
        returned_count=int(data.get("returned_count", 0)),
        truncated=bool(data.get("truncated", False)),
    )


def _occurrence_from_dict(data: dict[str, Any]) -> AgentOutputVariableOccurrenceWire:
    return AgentOutputVariableOccurrenceWire(
        artifact_dir=str(data.get("artifact_dir") or ""),
        project_name=str(data.get("project_name") or ""),
        workflow_dir_name=str(data.get("workflow_dir_name") or ""),
        timestamp=str(data.get("timestamp") or ""),
        key=str(data.get("key") or ""),
        value=data.get("value"),
        value_json=str(data.get("value_json") or ""),
        hidden=bool(data.get("hidden", False)),
        agent_name=_optional_str(data.get("agent_name")),
        cl_name=_optional_str(data.get("cl_name")),
    )


def _value_group_from_dict(data: dict[str, Any]) -> AgentOutputVariableValueGroupWire:
    raw_newest = data.get("newest")
    newest = (
        _occurrence_from_dict(raw_newest)
        if isinstance(raw_newest, dict)
        else AgentOutputVariableOccurrenceWire(
            artifact_dir="",
            project_name="",
            workflow_dir_name="",
            timestamp="",
            key="",
            value=None,
            value_json="",
            hidden=False,
        )
    )
    return AgentOutputVariableValueGroupWire(
        value=data.get("value"),
        value_json=str(data.get("value_json") or ""),
        occurrence_count=int(data.get("occurrence_count", 0)),
        agent_count=int(data.get("agent_count", 0)),
        agents=[str(item) for item in data.get("agents") or []],
        projects=[str(item) for item in data.get("projects") or []],
        first_seen_timestamp=str(data.get("first_seen_timestamp") or ""),
        last_seen_timestamp=str(data.get("last_seen_timestamp") or ""),
        newest=newest,
    )


def _key_group_from_dict(data: dict[str, Any]) -> AgentOutputVariableKeyGroupWire:
    raw_limit = data.get("values_limit")
    values_limit = (
        _limit_from_dict(raw_limit)
        if isinstance(raw_limit, dict)
        else AgentOutputVariableLimitWire(0, 0, 0, False)
    )
    return AgentOutputVariableKeyGroupWire(
        key=str(data.get("key") or ""),
        occurrence_count=int(data.get("occurrence_count", 0)),
        distinct_value_count=int(data.get("distinct_value_count", 0)),
        values_limit=values_limit,
        values=[
            _value_group_from_dict(item)
            for item in data.get("values") or []
            if isinstance(item, dict)
        ],
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


__all__ = [
    "AGENT_OUTPUT_VARIABLE_HISTORY_WIRE_SCHEMA_VERSION",
    "DEFAULT_OUTPUT_VARIABLE_KEY_LIMIT",
    "DEFAULT_OUTPUT_VARIABLE_VALUE_LIMIT",
    "AgentOutputVariableHistoryQueryWire",
    "AgentOutputVariableHistoryWire",
    "AgentOutputVariableKeyGroupWire",
    "AgentOutputVariableLimitWire",
    "AgentOutputVariableOccurrenceWire",
    "AgentOutputVariableValueGroupWire",
    "agent_output_variable_history_from_dict",
    "agent_output_variable_history_query_to_dict",
]
