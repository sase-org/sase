"""Read-surface request helpers for the local daemon client."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Protocol

from sase.daemon.constants import (
    LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
    LOCAL_DAEMON_SCHEMA_VERSION,
)
from sase.daemon.protocol import read_payload_data
from sase.daemon.read_payloads import (
    agent_list_data,
    bead_list_data,
    catalog_list_data,
    changespec_list_data,
    page_data,
)


class _RequestClient(Protocol):
    def request(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]: ...


class _ReadClient(_RequestClient, Protocol):
    def read(
        self, surface: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]: ...


class LocalDaemonReadMixin:
    """Request builders for daemon projection read surfaces."""

    def read(
        self: _RequestClient,
        surface: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.request(
            {
                "type": "read",
                "data": {"surface": surface, "data": data or {}},
            }
        )
        return read_payload_data(response, surface)

    def changespec_list(
        self: _ReadClient,
        *,
        project_id: str | None = None,
        query: str | None = None,
        status: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "changespec_list",
            changespec_list_data(
                project_id=project_id,
                query=query,
                status=status,
                limit=limit,
                cursor=cursor,
            ),
        )

    def changespec_search(
        self: _ReadClient,
        *,
        project_id: str | None = None,
        query: str | None = None,
        status: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "changespec_search",
            changespec_list_data(
                project_id=project_id,
                query=query,
                status=status,
                limit=limit,
                cursor=cursor,
            ),
        )

    def changespec_detail(self: _ReadClient, handle: str) -> dict[str, Any]:
        return self.read(
            "changespec_detail",
            {"schema_version": LOCAL_DAEMON_SCHEMA_VERSION, "handle": handle},
        )

    def agent_active(
        self: _ReadClient,
        *,
        project_id: str,
        include_hidden: bool = False,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "agent_active",
            agent_list_data(
                project_id=project_id,
                include_hidden=include_hidden,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def agent_recent(
        self: _ReadClient,
        *,
        project_id: str,
        include_hidden: bool = False,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "agent_recent",
            agent_list_data(
                project_id=project_id,
                include_hidden=include_hidden,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def agent_archive(
        self: _ReadClient,
        *,
        project_id: str,
        include_hidden: bool = False,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "agent_archive",
            agent_list_data(
                project_id=project_id,
                include_hidden=include_hidden,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def agent_search(
        self: _ReadClient,
        *,
        project_id: str,
        include_hidden: bool = False,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "agent_search",
            agent_list_data(
                project_id=project_id,
                include_hidden=include_hidden,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def agent_detail(
        self: _ReadClient, *, project_id: str, agent_id: str
    ) -> dict[str, Any]:
        return self.read(
            "agent_detail",
            {
                "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
                "project_id": project_id,
                "agent_id": agent_id,
            },
        )

    def notification_list(
        self: _ReadClient,
        *,
        include_dismissed: bool = False,
        query: str | None = None,
        sender: str | None = None,
        unread: bool | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "notification_list",
            {
                "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
                "page": page_data(limit=limit, cursor=cursor),
                "include_dismissed": include_dismissed,
                "query": query,
                "sender": sender,
                "unread": unread,
            },
        )

    def notification_detail(self: _ReadClient, notification_id: str) -> dict[str, Any]:
        return self.read(
            "notification_detail",
            {
                "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
                "notification_id": notification_id,
            },
        )

    def notification_counts(self: _ReadClient) -> dict[str, Any]:
        return self.read("notification_counts")

    def notification_pending_actions(self: _ReadClient) -> dict[str, Any]:
        return self.read("notification_pending_actions")

    def bead_list(
        self: _ReadClient,
        *,
        project_id: str,
        statuses: list[str] | None = None,
        issue_types: list[str] | None = None,
        tiers: list[str] | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "bead_list",
            bead_list_data(
                project_id=project_id,
                statuses=statuses,
                issue_types=issue_types,
                tiers=tiers,
                limit=limit,
                cursor=cursor,
            ),
        )

    def bead_ready(
        self: _ReadClient,
        *,
        project_id: str,
        statuses: list[str] | None = None,
        issue_types: list[str] | None = None,
        tiers: list[str] | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "bead_ready",
            bead_list_data(
                project_id=project_id,
                statuses=statuses,
                issue_types=issue_types,
                tiers=tiers,
                limit=limit,
                cursor=cursor,
            ),
        )

    def bead_blocked(
        self: _ReadClient,
        *,
        project_id: str,
        statuses: list[str] | None = None,
        issue_types: list[str] | None = None,
        tiers: list[str] | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "bead_blocked",
            bead_list_data(
                project_id=project_id,
                statuses=statuses,
                issue_types=issue_types,
                tiers=tiers,
                limit=limit,
                cursor=cursor,
            ),
        )

    def bead_show(
        self: _ReadClient, *, project_id: str, bead_id: str
    ) -> dict[str, Any]:
        return self.read(
            "bead_show",
            {
                "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
                "project_id": project_id,
                "bead_id": bead_id,
            },
        )

    def bead_stats(
        self: _ReadClient,
        *,
        project_id: str,
        statuses: list[str] | None = None,
        issue_types: list[str] | None = None,
        tiers: list[str] | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "bead_stats",
            bead_list_data(
                project_id=project_id,
                statuses=statuses,
                issue_types=issue_types,
                tiers=tiers,
                limit=limit,
                cursor=cursor,
            ),
        )

    def xprompt_catalog(
        self: _ReadClient,
        *,
        project_id: str | None = None,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "xprompt_catalog",
            catalog_list_data(
                project_id=project_id,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def editor_catalog(
        self: _ReadClient,
        *,
        project_id: str | None = None,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "editor_catalog",
            catalog_list_data(
                project_id=project_id,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def snippet_catalog(
        self: _ReadClient,
        *,
        project_id: str | None = None,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "snippet_catalog",
            catalog_list_data(
                project_id=project_id,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def file_history(
        self: _ReadClient,
        *,
        project_id: str | None = None,
        query: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        return self.read(
            "file_history",
            catalog_list_data(
                project_id=project_id,
                query=query,
                limit=limit,
                cursor=cursor,
            ),
        )

    def iter_read_pages(
        self: _ReadClient,
        surface: str,
        make_data: Callable[[str | None], dict[str, Any]],
        *,
        first_cursor: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        cursor = first_cursor
        while True:
            page = self.read(surface, make_data(cursor))
            yield page
            page_info = page.get("page")
            if not isinstance(page_info, dict):
                return
            next_cursor = page_info.get("next_cursor")
            if not isinstance(next_cursor, str) or not next_cursor:
                return
            cursor = next_cursor

    def iter_read_items(
        self: Any,
        surface: str,
        make_data: Callable[[str | None], dict[str, Any]],
        *,
        items_key: str,
        first_cursor: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        for page in self.iter_read_pages(surface, make_data, first_cursor=first_cursor):
            items = page.get(items_key)
            if not isinstance(items, list):
                return
            for item in items:
                if isinstance(item, dict):
                    yield item
