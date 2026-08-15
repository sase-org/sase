"""Wire records for output-variable selector parse and get queries.

Mirrors ``sase_core::agent_scan`` selector types. The Python CLI parses
selector strings through the Rust binding, then sends the typed query
back for resolution against the indexed occurrence projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.agent_output_variable_history_wire import (
    AgentOutputVariableLimitWire,
)
from sase.core.output_variable_values import VarValue
from sase.core.wire import known_field_kwargs

AGENT_OUTPUT_VARIABLE_SELECTOR_WIRE_SCHEMA_VERSION = 1
DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT = 20


@dataclass(frozen=True)
class _OutputVariableSelectorScopeWire:
    """Scope of one output-variable selector."""

    kind: str
    name: str | None = None


@dataclass(frozen=True)
class OutputVariableSelectorPathWire:
    """One JSON-path step applied after an occurrence is selected."""

    kind: str
    index: int | None = None
    key: str | None = None


@dataclass(frozen=True)
class OutputVariableSelectorWire:
    """Parsed ``sase var get`` selector."""

    raw: str
    scope: _OutputVariableSelectorScopeWire
    key: str | None
    path: list[OutputVariableSelectorPathWire] = field(default_factory=list)


@dataclass(frozen=True)
class AgentOutputVariableSelectorQueryWire:
    """Query knobs for selector-based output-variable retrieval."""

    selectors: list[OutputVariableSelectorWire] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    include_hidden: bool = False
    limit: int = DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT


@dataclass(frozen=True)
class AgentOutputVariableSelectorMatchWire:
    """One attributed selector match."""

    selector: str
    key: str
    path: list[OutputVariableSelectorPathWire]
    value: VarValue
    value_json: str
    artifact_dir: str
    project_name: str
    workflow_dir_name: str
    timestamp: str
    hidden: bool
    agent_name: str | None = None
    cl_name: str | None = None


@dataclass(frozen=True)
class AgentOutputVariableSelectorResultWire:
    """Selector matches returned by the artifact index."""

    schema_version: int
    index_path: str
    query: AgentOutputVariableSelectorQueryWire
    matches_limit: AgentOutputVariableLimitWire
    matches: list[AgentOutputVariableSelectorMatchWire]


def output_variable_selector_to_dict(
    selector: OutputVariableSelectorWire,
) -> dict[str, Any]:
    """Project a parsed selector to the Rust binding dict shape."""
    payload: dict[str, Any] = {
        "raw": selector.raw,
        "scope": _scope_to_dict(selector.scope),
        "key": selector.key,
        "path": [_path_to_dict(step) for step in selector.path],
    }
    return payload


def agent_output_variable_selector_query_to_dict(
    query: AgentOutputVariableSelectorQueryWire,
) -> dict[str, Any]:
    """Project a selector query to the Rust binding dict shape."""
    return {
        "selectors": [
            output_variable_selector_to_dict(selector) for selector in query.selectors
        ],
        "projects": list(query.projects),
        "include_hidden": bool(query.include_hidden),
        "limit": int(query.limit),
    }


def output_variable_selector_from_dict(
    data: dict[str, Any],
) -> OutputVariableSelectorWire:
    """Rehydrate one parsed selector from the Rust binding dict."""
    raw_scope = data.get("scope")
    scope = (
        _scope_from_dict(raw_scope)
        if isinstance(raw_scope, dict)
        else _OutputVariableSelectorScopeWire(kind="unscoped")
    )
    path = [
        _path_from_dict(item)
        for item in data.get("path") or []
        if isinstance(item, dict)
    ]
    key = data.get("key")
    return OutputVariableSelectorWire(
        raw=str(data.get("raw") or ""),
        scope=scope,
        key=None if key is None else str(key),
        path=path,
    )


def agent_output_variable_selector_result_from_dict(
    data: dict[str, Any],
) -> AgentOutputVariableSelectorResultWire:
    """Rehydrate a selector result from the Rust binding dict."""
    raw_query = data.get("query")
    query = (
        _query_from_dict(raw_query)
        if isinstance(raw_query, dict)
        else AgentOutputVariableSelectorQueryWire()
    )
    raw_limit = data.get("matches_limit")
    matches_limit = (
        AgentOutputVariableLimitWire(
            limit=int(raw_limit.get("limit", 0)),
            total_count=int(raw_limit.get("total_count", 0)),
            returned_count=int(raw_limit.get("returned_count", 0)),
            truncated=bool(raw_limit.get("truncated", False)),
        )
        if isinstance(raw_limit, dict)
        else AgentOutputVariableLimitWire(0, 0, 0, False)
    )
    matches = [
        _match_from_dict(item)
        for item in data.get("matches") or []
        if isinstance(item, dict)
    ]
    return AgentOutputVariableSelectorResultWire(
        schema_version=int(
            data.get(
                "schema_version",
                AGENT_OUTPUT_VARIABLE_SELECTOR_WIRE_SCHEMA_VERSION,
            )
        ),
        index_path=str(data.get("index_path") or ""),
        query=query,
        matches_limit=matches_limit,
        matches=matches,
    )


def _scope_to_dict(scope: _OutputVariableSelectorScopeWire) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": scope.kind}
    if scope.name is not None:
        payload["name"] = scope.name
    return payload


def _path_to_dict(step: OutputVariableSelectorPathWire) -> dict[str, Any]:
    payload: dict[str, Any] = {"kind": step.kind}
    if step.index is not None:
        payload["index"] = int(step.index)
    if step.key is not None:
        payload["key"] = step.key
    return payload


def _scope_from_dict(data: dict[str, Any]) -> _OutputVariableSelectorScopeWire:
    kwargs = known_field_kwargs(_OutputVariableSelectorScopeWire, data)
    kwargs.setdefault("kind", "unscoped")
    kwargs["kind"] = str(kwargs["kind"])
    if kwargs.get("name") is not None:
        kwargs["name"] = str(kwargs["name"])
    return _OutputVariableSelectorScopeWire(**kwargs)


def _path_from_dict(data: dict[str, Any]) -> OutputVariableSelectorPathWire:
    kwargs = known_field_kwargs(OutputVariableSelectorPathWire, data)
    kwargs.setdefault("kind", "index")
    kwargs["kind"] = str(kwargs["kind"])
    if kwargs.get("index") is not None:
        kwargs["index"] = int(kwargs["index"])
    if kwargs.get("key") is not None:
        kwargs["key"] = str(kwargs["key"])
    return OutputVariableSelectorPathWire(**kwargs)


def _query_from_dict(data: dict[str, Any]) -> AgentOutputVariableSelectorQueryWire:
    kwargs = known_field_kwargs(AgentOutputVariableSelectorQueryWire, data)
    kwargs.setdefault("selectors", [])
    kwargs.setdefault("projects", [])
    kwargs.setdefault("include_hidden", False)
    kwargs.setdefault("limit", DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT)
    kwargs["selectors"] = [
        output_variable_selector_from_dict(item)
        for item in kwargs["selectors"]
        if isinstance(item, dict)
    ]
    kwargs["projects"] = [str(item) for item in kwargs["projects"]]
    kwargs["include_hidden"] = bool(kwargs["include_hidden"])
    kwargs["limit"] = int(kwargs["limit"])
    return AgentOutputVariableSelectorQueryWire(**kwargs)


def _match_from_dict(data: dict[str, Any]) -> AgentOutputVariableSelectorMatchWire:
    return AgentOutputVariableSelectorMatchWire(
        selector=str(data.get("selector") or ""),
        key=str(data.get("key") or ""),
        path=[
            _path_from_dict(item)
            for item in data.get("path") or []
            if isinstance(item, dict)
        ],
        value=data.get("value"),
        value_json=str(data.get("value_json") or ""),
        artifact_dir=str(data.get("artifact_dir") or ""),
        project_name=str(data.get("project_name") or ""),
        workflow_dir_name=str(data.get("workflow_dir_name") or ""),
        timestamp=str(data.get("timestamp") or ""),
        hidden=bool(data.get("hidden", False)),
        agent_name=_optional_str(data.get("agent_name")),
        cl_name=_optional_str(data.get("cl_name")),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


__all__ = [
    "AGENT_OUTPUT_VARIABLE_SELECTOR_WIRE_SCHEMA_VERSION",
    "DEFAULT_OUTPUT_VARIABLE_SELECTOR_LIMIT",
    "AgentOutputVariableSelectorMatchWire",
    "AgentOutputVariableSelectorQueryWire",
    "AgentOutputVariableSelectorResultWire",
    "OutputVariableSelectorPathWire",
    "OutputVariableSelectorWire",
    "agent_output_variable_selector_query_to_dict",
    "agent_output_variable_selector_result_from_dict",
    "output_variable_selector_from_dict",
    "output_variable_selector_to_dict",
]
