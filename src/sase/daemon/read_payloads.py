"""Payload builders for local daemon read requests."""

from __future__ import annotations

from typing import Any

from sase.daemon.constants import LOCAL_DAEMON_SCHEMA_VERSION


def page_data(*, limit: int, cursor: str | None) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "limit": limit,
        "cursor": cursor,
    }


def changespec_list_data(
    *,
    project_id: str | None,
    query: str | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "page": page_data(limit=limit, cursor=cursor),
        "project_id": project_id,
        "query": query,
        "status": status,
    }


def agent_list_data(
    *,
    project_id: str,
    include_hidden: bool,
    query: str | None,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "page": page_data(limit=limit, cursor=cursor),
        "project_id": project_id,
        "include_hidden": include_hidden,
        "query": query,
    }


def ace_agent_snapshot_data(
    *,
    include_hidden: bool,
    query: str | None,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "page": page_data(limit=limit, cursor=cursor),
        "include_hidden": include_hidden,
        "query": query,
    }


def bead_list_data(
    *,
    project_id: str,
    statuses: list[str] | None,
    issue_types: list[str] | None,
    tiers: list[str] | None,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "page": page_data(limit=limit, cursor=cursor),
        "project_id": project_id,
        "statuses": list(statuses or []),
        "issue_types": list(issue_types or []),
        "tiers": list(tiers or []),
    }


def catalog_list_data(
    *,
    project_id: str | None,
    query: str | None,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "page": page_data(limit=limit, cursor=cursor),
        "project_id": project_id,
        "query": query,
    }
