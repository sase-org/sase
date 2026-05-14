"""Daemon-backed ChangeSpec read helpers for CLI surfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    changespec_detail_from_dict,
    changespec_list_from_dict,
)


def read_changespecs_or_fallback(
    surface: str,
    *,
    args: Any | None,
    direct_loader: Callable[[], list[ChangeSpec]],
    project_id: str | None = None,
    client: LocalDaemonClient | None = None,
    page_limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
) -> DaemonReadResult[list[ChangeSpec]]:
    """Read ChangeSpecs through the daemon when available."""

    return read_or_fallback(
        surface,
        args=args,
        client=client,
        daemon_loader=lambda daemon: load_changespecs_from_daemon(
            daemon,
            project_id=project_id,
            page_limit=page_limit,
        ),
        direct_loader=direct_loader,
    )


def load_changespecs_from_daemon(
    client: LocalDaemonClient,
    *,
    project_id: str | None = None,
    page_limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
) -> list[ChangeSpec]:
    """Load full ChangeSpec display models from daemon list/detail pages."""

    changespecs: list[ChangeSpec] = []
    cursor: str | None = None
    while True:
        page = changespec_list_from_dict(
            client.changespec_list(
                project_id=project_id,
                limit=page_limit,
                cursor=cursor,
            )
        )
        for entry in page.entries:
            detail = changespec_detail_from_dict(client.changespec_detail(entry.handle))
            if detail.changespec is not None:
                changespecs.append(detail.changespec)
        if not page.page.next_cursor:
            break
        cursor = page.page.next_cursor
    return changespecs


__all__ = ["load_changespecs_from_daemon", "read_changespecs_or_fallback"]
