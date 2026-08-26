"""Wire records for bounded per-alias agent history queries.

Mirrors ``sase_core::agent_scan``'s ``AgentAliasHistoryQueryWire`` /
``AgentAliasHistoryWire`` family (artifact-index schema 23). The Python CLI
builds a request, the Rust binding executes one bounded index query per
requested alias, and these records are the only shape that crosses the
facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sase.core.agent_scan_wire_markers import UsedXPromptWire
from sase.core.wire import known_field_kwargs

AGENT_ALIAS_HISTORY_WIRE_SCHEMA_VERSION = 1
DEFAULT_ALIAS_HISTORY_LIMIT_PER_ALIAS = 10
DEFAULT_ALIAS_HISTORY_PROMPT_SNIPPET_BYTES = 240


@dataclass(frozen=True)
class AgentAliasHistoryQueryWire:
    """Query knobs for bounded per-alias agent history.

    ``aliases`` is required; an empty list is a request error, not an
    implicit "everything".
    """

    aliases: list[str] = field(default_factory=list)
    limit_per_alias: int = DEFAULT_ALIAS_HISTORY_LIMIT_PER_ALIAS
    include_hidden: bool = False
    projects: list[str] = field(default_factory=list)
    prompt_snippet_bytes: int = DEFAULT_ALIAS_HISTORY_PROMPT_SNIPPET_BYTES
    freshness: Literal["revalidate", "cached"] = "cached"


@dataclass(frozen=True)
class _AgentAliasHistoryLimitWire:
    """Effective limit and truncation metadata for one alias group."""

    limit: int
    total_count: int
    returned_count: int
    truncated: bool


@dataclass(frozen=True)
class AgentAliasRunWire:
    """One indexed run that used a requested model alias."""

    artifact_dir: str
    project_name: str
    workflow_dir_name: str
    timestamp: str
    alias_position: int
    status: str
    has_done_marker: bool
    hidden: bool
    agent_name: str | None = None
    workflow_name: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
    model_alias: str | None = None
    model_alias_origin: str | None = None
    model_alias_trail: list[str] = field(default_factory=list)
    workflow_status: str | None = None
    started_at: str | None = None
    finished_at: float | None = None
    retry_attempt: int | None = None
    bead_id: str | None = None
    cl_name: str | None = None
    workspace_num: int | None = None
    prompt_snippet: str | None = None
    used_xprompts: list[UsedXPromptWire] = field(default_factory=list)


@dataclass(frozen=True)
class AgentAliasHistoryGroupWire:
    """History group for one requested alias."""

    alias: str
    runs_limit: _AgentAliasHistoryLimitWire
    runs: list[AgentAliasRunWire] = field(default_factory=list)


@dataclass(frozen=True)
class AgentAliasHistoryWire:
    """Bounded alias history returned by the persistent artifact index."""

    schema_version: int
    index_path: str
    query: AgentAliasHistoryQueryWire
    groups: list[AgentAliasHistoryGroupWire] = field(default_factory=list)


def agent_alias_history_query_to_dict(
    query: AgentAliasHistoryQueryWire,
) -> dict[str, Any]:
    """Project an alias-history query to the Rust binding dict shape."""
    return {
        "aliases": list(query.aliases),
        "limit_per_alias": int(query.limit_per_alias),
        "include_hidden": query.include_hidden,
        "projects": list(query.projects),
        "prompt_snippet_bytes": int(query.prompt_snippet_bytes),
        "freshness": query.freshness,
    }


def agent_alias_history_from_dict(data: dict[str, Any]) -> AgentAliasHistoryWire:
    """Rehydrate an alias-history response from the Rust binding dict."""
    raw_query = data.get("query")
    query = (
        _query_from_dict(raw_query)
        if isinstance(raw_query, dict)
        else AgentAliasHistoryQueryWire()
    )
    return AgentAliasHistoryWire(
        schema_version=int(
            data.get("schema_version", AGENT_ALIAS_HISTORY_WIRE_SCHEMA_VERSION)
        ),
        index_path=str(data.get("index_path") or ""),
        query=query,
        groups=[
            _group_from_dict(item)
            for item in data.get("groups") or []
            if isinstance(item, dict)
        ],
    )


def _query_from_dict(data: dict[str, Any]) -> AgentAliasHistoryQueryWire:
    kwargs = known_field_kwargs(AgentAliasHistoryQueryWire, data)
    kwargs.setdefault("aliases", [])
    kwargs.setdefault("limit_per_alias", DEFAULT_ALIAS_HISTORY_LIMIT_PER_ALIAS)
    kwargs.setdefault("include_hidden", False)
    kwargs.setdefault("projects", [])
    kwargs.setdefault(
        "prompt_snippet_bytes", DEFAULT_ALIAS_HISTORY_PROMPT_SNIPPET_BYTES
    )
    kwargs.setdefault("freshness", "cached")
    kwargs["aliases"] = [str(item) for item in kwargs["aliases"]]
    kwargs["limit_per_alias"] = int(kwargs["limit_per_alias"])
    kwargs["include_hidden"] = bool(kwargs["include_hidden"])
    kwargs["projects"] = [str(item) for item in kwargs["projects"]]
    kwargs["prompt_snippet_bytes"] = int(kwargs["prompt_snippet_bytes"])
    return AgentAliasHistoryQueryWire(**kwargs)


def _limit_from_dict(data: dict[str, Any]) -> _AgentAliasHistoryLimitWire:
    return _AgentAliasHistoryLimitWire(
        limit=int(data.get("limit", 0)),
        total_count=int(data.get("total_count", 0)),
        returned_count=int(data.get("returned_count", 0)),
        truncated=bool(data.get("truncated", False)),
    )


def _run_from_dict(data: dict[str, Any]) -> AgentAliasRunWire:
    kwargs = known_field_kwargs(AgentAliasRunWire, data)
    kwargs.pop("used_xprompts", None)
    kwargs.setdefault("model_alias_trail", [])
    kwargs["model_alias_trail"] = [str(item) for item in kwargs["model_alias_trail"]]
    return AgentAliasRunWire(
        used_xprompts=[
            UsedXPromptWire(**known_field_kwargs(UsedXPromptWire, used))
            for used in data.get("used_xprompts") or []
            if isinstance(used, dict)
        ],
        **kwargs,
    )


def _group_from_dict(data: dict[str, Any]) -> AgentAliasHistoryGroupWire:
    raw_limit = data.get("runs_limit")
    runs_limit = (
        _limit_from_dict(raw_limit)
        if isinstance(raw_limit, dict)
        else _AgentAliasHistoryLimitWire(0, 0, 0, False)
    )
    return AgentAliasHistoryGroupWire(
        alias=str(data.get("alias") or ""),
        runs_limit=runs_limit,
        runs=[
            _run_from_dict(item)
            for item in data.get("runs") or []
            if isinstance(item, dict)
        ],
    )


__all__ = [
    "AGENT_ALIAS_HISTORY_WIRE_SCHEMA_VERSION",
    "DEFAULT_ALIAS_HISTORY_LIMIT_PER_ALIAS",
    "DEFAULT_ALIAS_HISTORY_PROMPT_SNIPPET_BYTES",
    "AgentAliasHistoryGroupWire",
    "AgentAliasHistoryQueryWire",
    "AgentAliasHistoryWire",
    "AgentAliasRunWire",
    "agent_alias_history_from_dict",
    "agent_alias_history_query_to_dict",
]
