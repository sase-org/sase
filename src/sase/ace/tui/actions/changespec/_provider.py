"""ACE ChangeSpec read provider helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.ace.changespec import ChangeSpec, TimestampEntry
from sase.daemon.client import LOCAL_DAEMON_DEFAULT_PAGE_LIMIT, LocalDaemonClient
from sase.daemon.read_facade import DaemonReadResult, read_or_fallback
from sase.daemon.read_models import (
    ChangeSpecListEntry,
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


@dataclass(frozen=True)
class _ChangeSpecQuerySession:
    """Daemon query/session metadata for the active ChangeSpecs page."""

    query: str
    status: str | None
    snapshot_id: str | None
    next_cursor: str | None
    page_limit: int


def read_changespecs_for_tui(
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
    query: str = "",
    status: str | None = None,
    page_limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
) -> DaemonReadResult[AceSnapshot[ChangeSpec]]:
    """Return the ACE ChangeSpec snapshot through daemon reads when possible."""

    from ....changespec import find_all_changespecs_cached

    result = read_or_fallback(
        "changespec_list",
        args=args,
        client=client,
        daemon_loader=lambda daemon: _daemon_changespec_snapshot(
            daemon,
            query=query,
            status=status,
            page_limit=page_limit,
        ),
        direct_loader=lambda: _changespec_snapshot(
            find_all_changespecs_cached(),
            provider_source="direct",
            prefers_daemon=False,
            fallback_reason=None,
            fallback_message=None,
            snapshot_id=None,
            page_count=1,
            next_cursor=None,
            total_count=None,
            query=query,
            query_session=None,
            full_reload=True,
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
        next_cursor=result.value.first_page.next_cursor,
        total_count=result.value.total_count,
        query=query,
        query_session=None,
        full_reload=True,
    )
    return DaemonReadResult(
        value=fallback_snapshot,
        surface=result.surface,
        used_daemon=False,
        fallback_reason=result.fallback_reason,
        fallback_message=result.fallback_message,
    )


def load_changespec_detail_for_tui(
    row_handle: AceRowHandle,
    *,
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
) -> DaemonReadResult[ChangeSpec | None]:
    """Load one ChangeSpec detail through the daemon when possible."""

    handle = row_handle.daemon_handle
    if not handle:
        return DaemonReadResult(
            value=None,
            surface="changespec_detail",
            used_daemon=False,
            fallback_reason="missing_daemon_handle",
            fallback_message="selected ChangeSpec row has no daemon handle",
        )

    def _load_detail(daemon: LocalDaemonClient) -> ChangeSpec | None:
        detail = changespec_detail_from_dict(daemon.changespec_detail(handle))
        return detail.changespec

    return read_or_fallback(
        "changespec_detail",
        args=args,
        client=client,
        daemon_loader=_load_detail,
        direct_loader=lambda: None,
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


def _changespec_row_handle_from_entry(entry: ChangeSpecListEntry) -> AceRowHandle:
    return AceRowHandle(
        surface="changespecs",
        stable_id=entry.handle,
        daemon_handle=entry.handle,
        local_identity=f"{entry.project_basename}:{entry.name}",
    )


def _daemon_changespec_snapshot(
    client: LocalDaemonClient,
    *,
    query: str,
    status: str | None,
    page_limit: int,
) -> AceSnapshot[ChangeSpec]:
    query = query.strip()
    loader = client.changespec_search if query else client.changespec_list
    page = changespec_list_from_dict(
        loader(
            query=query or None,
            status=status,
            limit=page_limit,
            cursor=None,
        )
    )
    changespecs = [_changespec_from_summary(entry) for entry in page.entries]
    row_handles = [_changespec_row_handle_from_entry(entry) for entry in page.entries]
    query_session = _ChangeSpecQuerySession(
        query=query,
        status=status,
        snapshot_id=page.snapshot.snapshot_id,
        next_cursor=page.page.next_cursor,
        page_limit=page_limit,
    )
    return _changespec_snapshot(
        changespecs,
        provider_source="daemon",
        prefers_daemon=True,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id=page.snapshot.snapshot_id,
        page_count=1,
        next_cursor=page.page.next_cursor,
        total_count=None,
        query=query,
        query_session=query_session,
        row_handles=row_handles,
        full_reload=False,
    )


def _changespec_from_summary(entry: ChangeSpecListEntry) -> ChangeSpec:
    changespec = ChangeSpec(
        name=entry.name,
        description="",
        parent=entry.parent,
        cl=entry.cl_or_pr,
        status=entry.status,
        file_path=entry.source_path or entry.file_path,
        line_number=0,
        bug=entry.bug,
        timestamps=_summary_timestamps(entry),
    )
    changespec.__dict__["_sase_daemon_summary_only"] = True
    return changespec


def _summary_timestamps(entry: ChangeSpecListEntry) -> list[TimestampEntry]:
    parsed = _parse_summary_updated_at(entry.updated_at)
    if parsed is None:
        return []
    return [
        TimestampEntry(
            timestamp=parsed.strftime("%Y-%m-%d %H:%M:%S"),
            event_type="UPDATED",
            detail="daemon summary",
        )
    ]


def _parse_summary_updated_at(raw: str) -> datetime | None:
    value = raw.strip()
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _changespec_snapshot(
    changespecs: list[ChangeSpec],
    *,
    provider_source: str,
    prefers_daemon: bool,
    fallback_reason: str | None,
    fallback_message: str | None,
    snapshot_id: str | None,
    page_count: int,
    next_cursor: str | None,
    total_count: int | None,
    query: str,
    query_session: _ChangeSpecQuerySession | None,
    full_reload: bool,
    row_handles: list[AceRowHandle] | None = None,
) -> AceSnapshot[ChangeSpec]:
    snapshot = make_snapshot(
        surface="changespecs",
        rows=changespecs,
        row_handles=(
            row_handles
            if row_handles is not None
            else [changespec_row_handle(changespec) for changespec in changespecs]
        ),
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
        next_cursor=next_cursor,
        total_count=total_count,
        metadata={
            "active_query": query,
            "query_session": query_session,
            "next_cursor": next_cursor,
        },
        full_reload=full_reload,
    )
    trace_provider_snapshot(snapshot)
    return snapshot


__all__ = [
    "changespec_row_handle",
    "load_changespec_detail_for_tui",
    "read_changespecs_for_tui",
]
