"""Wire records for ProjectSpec lifecycle state.

The lifecycle contract is owned by ``sase_core_rs``. Python keeps typed
dataclasses at the facade boundary so CLI/TUI host code does not depend on
raw cross-language dicts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION = 1
PROJECT_LIFECYCLE_STATES = ("active", "archived", "closed")


@dataclass(frozen=True)
class ProjectLifecycleWire:
    """Effective lifecycle state parsed from one ProjectSpec content string."""

    schema_version: int
    state: str
    explicit: bool
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectRecordWire:
    """Lifecycle/discovery record for one SASE project directory."""

    schema_version: int
    project_name: str
    project_dir: str
    project_file: str
    archive_file: str | None
    workspace_dir: str | None
    state: str
    state_explicit: bool
    system_managed: bool
    active_claim_count: int
    launchable: bool
    warnings: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(item) for item in value]


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def project_lifecycle_from_dict(data: dict[str, Any]) -> ProjectLifecycleWire:
    """Build :class:`ProjectLifecycleWire` from a Rust/Python wire dict."""

    return ProjectLifecycleWire(
        schema_version=int(data["schema_version"]),
        state=str(data["state"]),
        explicit=bool(data["explicit"]),
        warnings=_str_list(data.get("warnings")),
    )


def project_record_from_dict(data: dict[str, Any]) -> ProjectRecordWire:
    """Build :class:`ProjectRecordWire` from a Rust/Python wire dict."""

    return ProjectRecordWire(
        schema_version=int(data["schema_version"]),
        project_name=str(data["project_name"]),
        project_dir=str(data["project_dir"]),
        project_file=str(data["project_file"]),
        archive_file=_optional_str(data.get("archive_file")),
        workspace_dir=_optional_str(data.get("workspace_dir")),
        state=str(data["state"]),
        state_explicit=bool(data["state_explicit"]),
        system_managed=bool(data["system_managed"]),
        active_claim_count=int(data["active_claim_count"]),
        launchable=bool(data["launchable"]),
        warnings=_str_list(data.get("warnings")),
        parse_warnings=_str_list(data.get("parse_warnings")),
    )


def project_lifecycle_wire_to_json_dict(record: Any) -> Any:
    """Convert lifecycle wire dataclasses to JSON-safe dict/list/scalar values."""

    if isinstance(record, (list, tuple)):
        return [project_lifecycle_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {
            str(key): project_lifecycle_wire_to_json_dict(value)
            for key, value in record.items()
        }
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


__all__ = [
    "PROJECT_LIFECYCLE_STATES",
    "PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION",
    "ProjectLifecycleWire",
    "ProjectRecordWire",
    "project_lifecycle_from_dict",
    "project_lifecycle_wire_to_json_dict",
    "project_record_from_dict",
]
