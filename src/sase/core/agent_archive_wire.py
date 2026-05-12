"""Wire records for the dismissed-agent archive Rust facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENT_ARCHIVE_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AgentArchiveQueryRequestWire:
    where_sql: str
    params: list[Any] = field(default_factory=list)
    limit: int = 50
    cursor: int | None = None


@dataclass(frozen=True)
class AgentArchiveFacetRequestWire:
    where_sql: str
    params: list[Any] = field(default_factory=list)
    facet: str = "status"
    limit: int = 20


@dataclass(frozen=True)
class AgentArchiveReviveMarkRequestWire:
    bundle_paths: list[str]
    revived_at: str


def agent_archive_query_request_to_dict(
    request: AgentArchiveQueryRequestWire,
) -> dict[str, Any]:
    return {
        "where_sql": request.where_sql,
        "params": list(request.params),
        "limit": request.limit,
        "cursor": request.cursor,
    }


def agent_archive_facet_request_to_dict(
    request: AgentArchiveFacetRequestWire,
) -> dict[str, Any]:
    return {
        "where_sql": request.where_sql,
        "params": list(request.params),
        "facet": request.facet,
        "limit": request.limit,
    }


def agent_archive_revive_mark_request_to_dict(
    request: AgentArchiveReviveMarkRequestWire,
) -> dict[str, Any]:
    return {
        "bundle_paths": list(request.bundle_paths),
        "revived_at": request.revived_at,
    }


__all__ = [
    "AGENT_ARCHIVE_WIRE_SCHEMA_VERSION",
    "AgentArchiveFacetRequestWire",
    "AgentArchiveQueryRequestWire",
    "AgentArchiveReviveMarkRequestWire",
    "agent_archive_facet_request_to_dict",
    "agent_archive_query_request_to_dict",
    "agent_archive_revive_mark_request_to_dict",
]
