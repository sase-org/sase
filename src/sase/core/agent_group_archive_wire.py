"""Wire records for saved dismissed-agent groups."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sase.core.agent_tribe import canonicalize_agent_tribe_metadata

AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION = 2
_LEGACY_AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SavedAgentGroupRefWire:
    """Reference to one dismissed bundle included in a saved group."""

    agent_type: str
    cl_name: str
    raw_suffix: str | None = None
    bundle_path: str | None = None
    is_workflow_child: bool = False
    parent_timestamp: str | None = None
    display_name: str | None = None
    agent_name: str | None = None
    status: str | None = None
    start_time: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    tribe: str | None = None
    prompt_preview: str | None = None
    reasoning_effort: str | None = None
    source_run_id: str | None = None


@dataclass(frozen=True)
class SavedAgentGroupWire:
    """Saved group metadata plus stable per-agent bundle refs."""

    group_id: str
    created_at: str
    source: str
    title: str
    agent_count: int
    top_level_agent_count: int
    name: str | None = None
    schema_version: int = AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION
    status_counts: dict[str, int] = field(default_factory=dict)
    project_names: tuple[str, ...] = ()
    cl_names: tuple[str, ...] = ()
    agent_refs: tuple[SavedAgentGroupRefWire, ...] = ()
    revived_at: str | None = None
    times_revived: int = 0
    canonical_global_family: str | None = None
    source_snapshot_digest: str | None = None


@dataclass(frozen=True)
class SavedAgentGroupSummaryWire:
    """List-page summary for a saved dismissed-agent group."""

    group_id: str
    created_at: str
    source: str
    title: str
    agent_count: int
    top_level_agent_count: int
    name: str | None = None
    schema_version: int = AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION
    status_counts: dict[str, int] = field(default_factory=dict)
    project_names: tuple[str, ...] = ()
    cl_names: tuple[str, ...] = ()
    revived_at: str | None = None
    times_revived: int = 0


@dataclass(frozen=True)
class SavedAgentGroupPageWire:
    """Newest-first page of saved group summaries."""

    groups: tuple[SavedAgentGroupSummaryWire, ...]
    next_cursor: int | None = None


def saved_agent_group_wire_to_json_dict(record: Any) -> Any:
    """Project saved-group wire records to a JSON-safe dict/list tree."""

    if isinstance(record, (list, tuple)):
        return [saved_agent_group_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: saved_agent_group_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def _saved_agent_group_ref_from_dict(data: dict[str, Any]) -> SavedAgentGroupRefWire:
    """Rehydrate a saved group ref from a dict."""
    data = canonicalize_agent_tribe_metadata(dict(data))

    return SavedAgentGroupRefWire(
        agent_type=str(data["agent_type"]),
        cl_name=str(data["cl_name"]),
        raw_suffix=None if data.get("raw_suffix") is None else str(data["raw_suffix"]),
        bundle_path=(
            None if data.get("bundle_path") is None else str(data["bundle_path"])
        ),
        is_workflow_child=bool(data.get("is_workflow_child", False)),
        parent_timestamp=(
            None
            if data.get("parent_timestamp") is None
            else str(data["parent_timestamp"])
        ),
        display_name=(
            None if data.get("display_name") is None else str(data["display_name"])
        ),
        agent_name=None if data.get("agent_name") is None else str(data["agent_name"]),
        status=None if data.get("status") is None else str(data["status"]),
        start_time=None if data.get("start_time") is None else str(data["start_time"]),
        model=None if data.get("model") is None else str(data["model"]),
        llm_provider=(
            None if data.get("llm_provider") is None else str(data["llm_provider"])
        ),
        tribe=None if data.get("tribe") is None else str(data["tribe"]),
        prompt_preview=(
            None if data.get("prompt_preview") is None else str(data["prompt_preview"])
        ),
        reasoning_effort=(
            None
            if data.get("reasoning_effort") is None
            else str(data["reasoning_effort"])
        ),
        source_run_id=(
            None if data.get("source_run_id") is None else str(data["source_run_id"])
        ),
    )


def saved_agent_group_from_dict(data: dict[str, Any]) -> SavedAgentGroupWire:
    """Rehydrate a saved group from a dict."""

    schema = int(data.get("schema_version", AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION))
    _check_schema(schema)
    return SavedAgentGroupWire(
        schema_version=AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION,
        group_id=str(data["group_id"]),
        created_at=str(data["created_at"]),
        source=str(data["source"]),
        title=str(data["title"]),
        agent_count=int(data["agent_count"]),
        top_level_agent_count=int(data["top_level_agent_count"]),
        name=_optional_nonblank_str(data.get("name")),
        status_counts=_status_counts_from_dict(data.get("status_counts") or {}),
        project_names=tuple(str(item) for item in data.get("project_names") or ()),
        cl_names=tuple(str(item) for item in data.get("cl_names") or ()),
        agent_refs=tuple(
            _saved_agent_group_ref_from_dict(item)
            for item in data.get("agent_refs") or ()
        ),
        revived_at=None if data.get("revived_at") is None else str(data["revived_at"]),
        times_revived=int(data.get("times_revived", 0)),
        canonical_global_family=_optional_nonblank_str(
            data.get("canonical_global_family")
        ),
        source_snapshot_digest=_optional_nonblank_str(
            data.get("source_snapshot_digest")
        ),
    )


def _saved_agent_group_summary_from_dict(
    data: dict[str, Any],
) -> SavedAgentGroupSummaryWire:
    """Rehydrate a saved group summary from a dict."""

    schema = int(data.get("schema_version", AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION))
    _check_schema(schema)
    return SavedAgentGroupSummaryWire(
        schema_version=AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION,
        group_id=str(data["group_id"]),
        created_at=str(data["created_at"]),
        source=str(data["source"]),
        title=str(data["title"]),
        agent_count=int(data["agent_count"]),
        top_level_agent_count=int(data["top_level_agent_count"]),
        name=_optional_nonblank_str(data.get("name")),
        status_counts=_status_counts_from_dict(data.get("status_counts") or {}),
        project_names=tuple(str(item) for item in data.get("project_names") or ()),
        cl_names=tuple(str(item) for item in data.get("cl_names") or ()),
        revived_at=None if data.get("revived_at") is None else str(data["revived_at"]),
        times_revived=int(data.get("times_revived", 0)),
    )


def saved_agent_group_page_from_dict(data: dict[str, Any]) -> SavedAgentGroupPageWire:
    """Rehydrate a saved group list page from a dict."""

    return SavedAgentGroupPageWire(
        groups=tuple(
            _saved_agent_group_summary_from_dict(item)
            for item in data.get("groups") or ()
        ),
        next_cursor=(
            None if data.get("next_cursor") is None else int(data["next_cursor"])
        ),
    )


def saved_agent_group_summary_from_group(
    group: SavedAgentGroupWire,
) -> SavedAgentGroupSummaryWire:
    """Build a list summary from a full saved group record."""

    return SavedAgentGroupSummaryWire(
        schema_version=group.schema_version,
        group_id=group.group_id,
        created_at=group.created_at,
        source=group.source,
        title=group.title,
        agent_count=group.agent_count,
        top_level_agent_count=group.top_level_agent_count,
        name=group.name,
        status_counts=dict(group.status_counts),
        project_names=group.project_names,
        cl_names=group.cl_names,
        revived_at=group.revived_at,
        times_revived=group.times_revived,
    )


def _status_counts_from_dict(data: dict[str, Any]) -> dict[str, int]:
    return {str(key): int(value) for key, value in data.items()}


def _optional_nonblank_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _check_schema(schema: int) -> None:
    if schema not in {
        _LEGACY_AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION,
        AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION,
    }:
        raise ValueError(
            f"saved agent group wire schema mismatch: got {schema}, "
            f"expected {AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION}"
        )


__all__ = [
    "AGENT_GROUP_ARCHIVE_WIRE_SCHEMA_VERSION",
    "SavedAgentGroupPageWire",
    "SavedAgentGroupRefWire",
    "SavedAgentGroupSummaryWire",
    "SavedAgentGroupWire",
    "saved_agent_group_from_dict",
    "saved_agent_group_page_from_dict",
    "saved_agent_group_summary_from_group",
    "saved_agent_group_wire_to_json_dict",
]
