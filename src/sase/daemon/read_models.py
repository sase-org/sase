"""Typed helpers for local daemon projection read payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.ace.changespec import ChangeSpec
from sase.bead.model import Issue
from sase.core.bead_wire import issue_from_dict, issues_from_list
from sase.core.wire_conversion import changespec_from_wire_dict
from sase.core.notification_store_wire import notification_from_dict
from sase.notifications.models import Notification

PROJECTION_READ_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProjectionSnapshot:
    schema_version: int
    snapshot_id: str


@dataclass(frozen=True)
class ProjectionPage:
    schema_version: int
    next_cursor: str | None = None


@dataclass(frozen=True)
class ProjectionPayloadBound:
    schema_version: int
    max_payload_bytes: int
    truncated: bool = False


@dataclass(frozen=True)
class GenericDaemonRead:
    """Lossless typed wrapper for surfaces with no local model yet."""

    surface: str
    data: dict[str, Any]
    snapshot: ProjectionSnapshot | None = None
    page: ProjectionPage | None = None
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class NotificationListRead:
    snapshot: ProjectionSnapshot
    page: ProjectionPage
    notifications: list[Notification] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class NotificationDetailRead:
    snapshot: ProjectionSnapshot
    notification: Notification | None
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class BeadListRead:
    snapshot: ProjectionSnapshot
    page: ProjectionPage
    issues: list[Issue] = field(default_factory=list)
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class BeadDetailRead:
    snapshot: ProjectionSnapshot
    issue: Issue
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class ChangeSpecListEntry:
    schema_version: int
    handle: str
    project_id: str
    name: str
    project_basename: str
    file_path: str
    source_path: str
    is_archive: bool
    status: str
    parent: str | None
    cl_or_pr: str | None
    bug: str | None
    updated_at: str
    last_seq: int


@dataclass(frozen=True)
class ChangeSpecListRead:
    snapshot: ProjectionSnapshot
    page: ProjectionPage
    entries: list[ChangeSpecListEntry] = field(default_factory=list)
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class ChangeSpecDetailRead:
    snapshot: ProjectionSnapshot
    changespec: ChangeSpec | None
    summary: ChangeSpecListEntry | None = None
    bounded: ProjectionPayloadBound | None = None


def generic_read_from_dict(surface: str, data: Mapping[str, Any]) -> GenericDaemonRead:
    raw = dict(data)
    return GenericDaemonRead(
        surface=surface,
        data=raw,
        snapshot=_snapshot(raw.get("snapshot")),
        page=_page(raw.get("page")),
        bounded=_bounded(raw.get("bounded")),
    )


def notification_list_from_dict(data: Mapping[str, Any]) -> NotificationListRead:
    raw = dict(data)
    return NotificationListRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        page=_required_page(raw.get("page")),
        notifications=[
            notification_from_dict(item)
            for item in _dict_list(raw.get("notifications"), "notifications")
        ],
        counts=dict(raw.get("counts") or {}),
        bounded=_bounded(raw.get("bounded")),
    )


def notification_detail_from_dict(data: Mapping[str, Any]) -> NotificationDetailRead:
    raw = dict(data)
    notification_raw = raw.get("notification")
    return NotificationDetailRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        notification=(
            None
            if notification_raw is None
            else notification_from_dict(_require_dict(notification_raw, "notification"))
        ),
        bounded=_bounded(raw.get("bounded")),
    )


def bead_list_from_dict(data: Mapping[str, Any]) -> BeadListRead:
    raw = dict(data)
    return BeadListRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        page=_required_page(raw.get("page")),
        issues=issues_from_list(_dict_list(raw.get("issues"), "issues")),
        bounded=_bounded(raw.get("bounded")),
    )


def bead_detail_from_dict(data: Mapping[str, Any]) -> BeadDetailRead:
    raw = dict(data)
    return BeadDetailRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        issue=issue_from_dict(_require_dict(raw.get("issue"), "issue")),
        bounded=_bounded(raw.get("bounded")),
    )


def changespec_list_from_dict(data: Mapping[str, Any]) -> ChangeSpecListRead:
    raw = dict(data)
    entries_page = _require_dict(raw.get("entries"), "entries")
    return ChangeSpecListRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        page=_required_page(raw.get("page")),
        entries=[
            _changespec_list_entry_from_dict(item)
            for item in _dict_list(entries_page.get("entries"), "entries.entries")
        ],
        bounded=_bounded(raw.get("bounded")),
    )


def changespec_detail_from_dict(data: Mapping[str, Any]) -> ChangeSpecDetailRead:
    raw = dict(data)
    detail_raw = raw.get("detail")
    detail = None if detail_raw is None else _require_dict(detail_raw, "detail")
    summary = None
    changespec = None
    if detail is not None:
        summary = _changespec_list_entry_from_dict(
            _require_dict(detail.get("summary"), "detail.summary")
        )
        changespec = changespec_from_wire_dict(
            _require_dict(detail.get("spec"), "detail.spec")
        )
    return ChangeSpecDetailRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        changespec=changespec,
        summary=summary,
        bounded=_bounded(raw.get("bounded")),
    )


def _changespec_list_entry_from_dict(data: Mapping[str, Any]) -> ChangeSpecListEntry:
    raw = dict(data)
    return ChangeSpecListEntry(
        schema_version=int(raw.get("schema_version", PROJECTION_READ_SCHEMA_VERSION)),
        handle=str(raw["handle"]),
        project_id=str(raw["project_id"]),
        name=str(raw["name"]),
        project_basename=str(raw["project_basename"]),
        file_path=str(raw["file_path"]),
        source_path=str(raw["source_path"]),
        is_archive=bool(raw["is_archive"]),
        status=str(raw["status"]),
        parent=_optional_str(raw.get("parent")),
        cl_or_pr=_optional_str(raw.get("cl_or_pr")),
        bug=_optional_str(raw.get("bug")),
        updated_at=str(raw["updated_at"]),
        last_seq=int(raw["last_seq"]),
    )


def _snapshot(value: Any) -> ProjectionSnapshot | None:
    if value is None:
        return None
    raw = _require_dict(value, "snapshot")
    return ProjectionSnapshot(
        schema_version=int(raw.get("schema_version", PROJECTION_READ_SCHEMA_VERSION)),
        snapshot_id=str(raw["snapshot_id"]),
    )


def _required_snapshot(value: Any) -> ProjectionSnapshot:
    snapshot = _snapshot(value)
    if snapshot is None:
        raise ValueError("missing projection read snapshot")
    return snapshot


def _page(value: Any) -> ProjectionPage | None:
    if value is None:
        return None
    raw = _require_dict(value, "page")
    next_cursor = raw.get("next_cursor")
    return ProjectionPage(
        schema_version=int(raw.get("schema_version", PROJECTION_READ_SCHEMA_VERSION)),
        next_cursor=None if next_cursor is None else str(next_cursor),
    )


def _required_page(value: Any) -> ProjectionPage:
    page = _page(value)
    if page is None:
        raise ValueError("missing projection read page")
    return page


def _bounded(value: Any) -> ProjectionPayloadBound | None:
    if value is None:
        return None
    raw = _require_dict(value, "bounded")
    return ProjectionPayloadBound(
        schema_version=int(raw.get("schema_version", PROJECTION_READ_SCHEMA_VERSION)),
        max_payload_bytes=int(raw["max_payload_bytes"]),
        truncated=bool(raw.get("truncated", False)),
    )


def _require_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"expected {field_name} to be an object")
    return value


def _dict_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"expected {field_name} to be a list")
    return [_require_dict(item, field_name) for item in value]


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "PROJECTION_READ_SCHEMA_VERSION",
    "BeadDetailRead",
    "BeadListRead",
    "ChangeSpecDetailRead",
    "ChangeSpecListEntry",
    "ChangeSpecListRead",
    "GenericDaemonRead",
    "NotificationDetailRead",
    "NotificationListRead",
    "ProjectionPage",
    "ProjectionPayloadBound",
    "ProjectionSnapshot",
    "bead_detail_from_dict",
    "bead_list_from_dict",
    "changespec_detail_from_dict",
    "changespec_list_from_dict",
    "generic_read_from_dict",
    "notification_detail_from_dict",
    "notification_list_from_dict",
]
