"""Typed helpers for local daemon projection read payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sase.ace.changespec import ChangeSpec
from sase.bead.model import Issue
from sase.core.bead_wire import issue_from_dict, issues_from_list
from sase.core.wire_conversion import changespec_from_wire_dict

if TYPE_CHECKING:
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
class NotificationCountsRead:
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class NotificationPendingActionsRead:
    snapshot: ProjectionSnapshot
    store: dict[str, Any] = field(default_factory=dict)
    actions: list[dict[str, Any]] = field(default_factory=list)
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
class BeadStatsRead:
    snapshot: ProjectionSnapshot
    project_id: str
    stats: dict[str, int] = field(default_factory=dict)
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
class AgentProjectionSummary:
    schema_version: int
    agent_id: str
    project_id: str
    project_name: str
    project_dir: str
    project_file: str
    workflow_dir_name: str
    artifact_dir: str
    timestamp: str
    status: str
    agent_type: str
    cl_name: str | None = None
    agent_name: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    started_at: str | None = None
    finished_at: float | None = None
    hidden: bool = False
    has_done_marker: bool = False
    has_running_marker: bool = False
    has_waiting_marker: bool = False
    has_workflow_state: bool = False
    batch_id: str | None = None
    queue_id: str | None = None
    parent_agent_id: str | None = None
    workflow_id: str | None = None
    retry_of_agent_id: str | None = None
    resume_of_agent_id: str | None = None
    host_id: str | None = None
    pid: int | None = None
    workspace_claim_id: str | None = None
    last_heartbeat_at: str | None = None
    last_check_at: str | None = None
    lifecycle_changed_at: str | None = None
    stale_reason: str | None = None
    last_seq: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentArtifactAssociation:
    schema_version: int
    agent_id: str
    artifact_path: str
    artifact_kind: str
    display_name: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class _AgentListRead:
    snapshot: ProjectionSnapshot
    page: ProjectionPage
    agents: list[AgentProjectionSummary] = field(default_factory=list)
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class ChangeSpecDetailRead:
    snapshot: ProjectionSnapshot
    changespec: ChangeSpec | None
    summary: ChangeSpecListEntry | None = None
    bounded: ProjectionPayloadBound | None = None


@dataclass(frozen=True)
class AgentDetailRead:
    snapshot: ProjectionSnapshot
    summary: AgentProjectionSummary
    children: list[AgentProjectionSummary] = field(default_factory=list)
    artifacts: list[AgentArtifactAssociation] = field(default_factory=list)
    bounded: ProjectionPayloadBound | None = None
    extra: dict[str, Any] = field(default_factory=dict)


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
    from sase.core.notification_store_wire import notification_from_dict

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
    from sase.core.notification_store_wire import notification_from_dict

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


def notification_counts_from_dict(data: Mapping[str, Any]) -> NotificationCountsRead:
    return NotificationCountsRead(
        counts={str(key): int(value) for key, value in data.items()}
    )


def notification_pending_actions_from_dict(
    data: Mapping[str, Any],
) -> NotificationPendingActionsRead:
    raw = dict(data)
    return NotificationPendingActionsRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        store=dict(_require_dict(raw.get("store"), "store")),
        actions=_dict_list(raw.get("actions"), "actions"),
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


def bead_stats_from_dict(data: Mapping[str, Any]) -> BeadStatsRead:
    raw = dict(data)
    stats_raw = raw.get("stats")
    if not isinstance(stats_raw, dict):
        raise ValueError("expected stats to be an object")
    return BeadStatsRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        project_id=str(raw.get("project_id", "")),
        stats={str(key): int(value) for key, value in stats_raw.items()},
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


def agent_list_from_dict(data: Mapping[str, Any]) -> _AgentListRead:
    raw = dict(data)
    entries = _require_dict(raw.get("entries"), "entries")
    return _AgentListRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        page=_required_page(raw.get("page")),
        agents=[
            _agent_summary_from_dict(item)
            for item in _dict_list(entries.get("entries"), "entries.entries")
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


def agent_detail_from_dict(data: Mapping[str, Any]) -> AgentDetailRead:
    raw = dict(data)
    known = {"snapshot", "summary", "children", "artifacts", "bounded"}
    return AgentDetailRead(
        snapshot=_required_snapshot(raw.get("snapshot")),
        summary=_agent_summary_from_dict(_require_dict(raw.get("summary"), "summary")),
        children=[
            _agent_summary_from_dict(item)
            for item in _dict_list(raw.get("children", []), "children")
        ],
        artifacts=[
            agent_artifact_from_dict(item)
            for item in _dict_list(raw.get("artifacts", []), "artifacts")
        ],
        bounded=_bounded(raw.get("bounded")),
        extra={key: value for key, value in raw.items() if key not in known},
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


def _agent_summary_from_dict(data: Mapping[str, Any]) -> AgentProjectionSummary:
    raw = dict(data)
    known = {
        "schema_version",
        "agent_id",
        "project_id",
        "project_name",
        "project_dir",
        "project_file",
        "workflow_dir_name",
        "artifact_dir",
        "timestamp",
        "status",
        "agent_type",
        "cl_name",
        "agent_name",
        "model",
        "llm_provider",
        "started_at",
        "finished_at",
        "hidden",
        "has_done_marker",
        "has_running_marker",
        "has_waiting_marker",
        "has_workflow_state",
        "batch_id",
        "queue_id",
        "parent_agent_id",
        "workflow_id",
        "retry_of_agent_id",
        "resume_of_agent_id",
        "host_id",
        "pid",
        "workspace_claim_id",
        "last_heartbeat_at",
        "last_check_at",
        "lifecycle_changed_at",
        "stale_reason",
        "last_seq",
    }
    finished_at = raw.get("finished_at")
    return AgentProjectionSummary(
        schema_version=int(raw.get("schema_version", PROJECTION_READ_SCHEMA_VERSION)),
        agent_id=str(raw["agent_id"]),
        project_id=str(raw["project_id"]),
        project_name=str(raw["project_name"]),
        project_dir=str(raw["project_dir"]),
        project_file=str(raw["project_file"]),
        workflow_dir_name=str(raw["workflow_dir_name"]),
        artifact_dir=str(raw["artifact_dir"]),
        timestamp=str(raw["timestamp"]),
        status=str(raw["status"]),
        agent_type=str(raw["agent_type"]),
        cl_name=_optional_str(raw.get("cl_name")),
        agent_name=_optional_str(raw.get("agent_name")),
        model=_optional_str(raw.get("model")),
        llm_provider=_optional_str(raw.get("llm_provider")),
        started_at=_optional_str(raw.get("started_at")),
        finished_at=None if finished_at is None else float(finished_at),
        hidden=bool(raw.get("hidden", False)),
        has_done_marker=bool(raw.get("has_done_marker", False)),
        has_running_marker=bool(raw.get("has_running_marker", False)),
        has_waiting_marker=bool(raw.get("has_waiting_marker", False)),
        has_workflow_state=bool(raw.get("has_workflow_state", False)),
        batch_id=_optional_str(raw.get("batch_id")),
        queue_id=_optional_str(raw.get("queue_id")),
        parent_agent_id=_optional_str(raw.get("parent_agent_id")),
        workflow_id=_optional_str(raw.get("workflow_id")),
        retry_of_agent_id=_optional_str(raw.get("retry_of_agent_id")),
        resume_of_agent_id=_optional_str(raw.get("resume_of_agent_id")),
        host_id=_optional_str(raw.get("host_id")),
        pid=_optional_int(raw.get("pid")),
        workspace_claim_id=_optional_str(raw.get("workspace_claim_id")),
        last_heartbeat_at=_optional_str(raw.get("last_heartbeat_at")),
        last_check_at=_optional_str(raw.get("last_check_at")),
        lifecycle_changed_at=_optional_str(raw.get("lifecycle_changed_at")),
        stale_reason=_optional_str(raw.get("stale_reason")),
        last_seq=int(raw.get("last_seq", 0)),
        extra={key: value for key, value in raw.items() if key not in known},
    )


def agent_artifact_from_dict(data: Mapping[str, Any]) -> AgentArtifactAssociation:
    raw = dict(data)
    return AgentArtifactAssociation(
        schema_version=int(raw.get("schema_version", PROJECTION_READ_SCHEMA_VERSION)),
        agent_id=str(raw["agent_id"]),
        artifact_path=str(raw["artifact_path"]),
        artifact_kind=str(raw["artifact_kind"]),
        display_name=_optional_str(raw.get("display_name")),
        role=_optional_str(raw.get("role")),
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


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


__all__ = [
    "PROJECTION_READ_SCHEMA_VERSION",
    "AgentArtifactAssociation",
    "AgentDetailRead",
    "AgentProjectionSummary",
    "BeadDetailRead",
    "BeadListRead",
    "BeadStatsRead",
    "ChangeSpecDetailRead",
    "ChangeSpecListEntry",
    "ChangeSpecListRead",
    "GenericDaemonRead",
    "NotificationCountsRead",
    "NotificationDetailRead",
    "NotificationListRead",
    "NotificationPendingActionsRead",
    "ProjectionPage",
    "ProjectionPayloadBound",
    "ProjectionSnapshot",
    "agent_artifact_from_dict",
    "agent_detail_from_dict",
    "agent_list_from_dict",
    "bead_detail_from_dict",
    "bead_list_from_dict",
    "bead_stats_from_dict",
    "changespec_detail_from_dict",
    "changespec_list_from_dict",
    "generic_read_from_dict",
    "notification_counts_from_dict",
    "notification_detail_from_dict",
    "notification_list_from_dict",
    "notification_pending_actions_from_dict",
]
