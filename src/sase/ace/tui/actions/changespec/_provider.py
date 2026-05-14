"""ACE ChangeSpec read provider helpers."""

from __future__ import annotations

from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    changespec_detail_from_dict,
    changespec_list_from_dict,
)

from ...provider_contract import (
    AceFallbackMetadata,
    AceProviderCapabilities,
    AceProviderInfo,
    AceRowHandle,
    AceSnapshot,
    make_snapshot,
    trace_provider_snapshot,
)


def read_changespecs_for_tui(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[AceSnapshot[ChangeSpec]]:
    """Return the ACE ChangeSpec snapshot through daemon reads when possible."""

    from ....changespec import find_all_changespecs_cached

    result = read_or_fallback(
        "changespec_list",
        args=args,
        client=client,
        daemon_loader=_daemon_changespec_snapshot,
        direct_loader=lambda: _changespec_snapshot(
            find_all_changespecs_cached(),
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=None,
            page_count=1,
        ),
    )
    if result.used_daemon:
        return result
    fallback_snapshot = _changespec_snapshot(
        result.value.rows,
        provider_source="direct_fallback",
        prefers_daemon=True,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
        snapshot_id=result.value.snapshot_id,
        page_count=int(result.value.metadata.get("page_count", 1)),
    )
    return DaemonReadResult(
        value=fallback_snapshot,
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
def changespec_row_handle(changespec: ChangeSpec) -> AceRowHandle:
    """Return the stable ACE row handle for a ChangeSpec row."""

    handle = f"changespec:{changespec.project_basename}:{changespec.name}"
    return AceRowHandle(
        surface="changespecs",
        stable_id=handle,
        daemon_handle=handle,
        local_identity=f"{changespec.project_basename}:{changespec.name}",
    )


def _daemon_changespec_snapshot(client: LocalDaemonClient) -> AceSnapshot[ChangeSpec]:
    changespecs: list[ChangeSpec] = []
    snapshot_id: str | None = None
    cursor: str | None = None
    page_count = 0
    while True:
        page = changespec_list_from_dict(
            client.changespec_list(
                limit=LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
                cursor=cursor,
            )
        )
        page_count += 1
        snapshot_id = snapshot_id or page.snapshot.snapshot_id
        for entry in page.entries:
            detail = changespec_detail_from_dict(client.changespec_detail(entry.handle))
            if detail.changespec is not None:
                changespecs.append(detail.changespec)
        if not page.page.next_cursor:
            break
        cursor = page.page.next_cursor
    return _changespec_snapshot(
        changespecs,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=snapshot_id,
        page_count=page_count,
    )


def _changespec_snapshot(
    changespecs: list[ChangeSpec],
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
) -> AceSnapshot[ChangeSpec]:
    snapshot = make_snapshot(
        surface="changespecs",
        rows=changespecs,
        row_handles=[changespec_row_handle(changespec) for changespec in changespecs],
        provider=AceProviderInfo(
            identity=f"changespecs:{provider_source}",
            surface="changespecs",
            source=provider_source,
            prefers_daemon=prefers_daemon,
            capabilities=AceProviderCapabilities(
                pages=provider_source == "daemon",
                lazy_details=provider_source == "daemon",
            ),
            fallback=AceFallbackMetadata(fallback_reason, fallback_message),
        ),
        snapshot_id=snapshot_id,
        page_count=page_count,
        full_reload=True,
    )
    trace_provider_snapshot(snapshot)
    return snapshot


__all__ = ["changespec_row_handle", "read_changespecs_for_tui"]
