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
__all__ = [
    "AGENT_ARCHIVE_WIRE_SCHEMA_VERSION",
    "AgentArchiveFacetRequestWire",
    "AgentArchiveQueryRequestWire",
    "agent_archive_facet_request_to_dict",
    "agent_archive_query_request_to_dict",
]
