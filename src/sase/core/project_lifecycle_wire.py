"""Wire records for ProjectSpec lifecycle state.

The lifecycle contract is owned by ``sase_core_rs``. Python keeps typed
dataclasses at the facade boundary so CLI/TUI host code does not depend on
raw cross-language dicts.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION = 3
PROJECT_LIFECYCLE_STATES = ("enabled", "disabled", "sibling")
PROJECT_LIFECYCLE_LEGACY_ENABLED_STATES = ("active",)
PROJECT_LIFECYCLE_LEGACY_DISABLED_STATES = ("inactive", "archived", "closed")
PROJECT_LIFECYCLE_COMPAT_STATES = (
    *PROJECT_LIFECYCLE_STATES,
    *PROJECT_LIFECYCLE_LEGACY_ENABLED_STATES,
    *PROJECT_LIFECYCLE_LEGACY_DISABLED_STATES,
)


def normalize_project_lifecycle_state(state: str) -> str:
    """Return the canonical lifecycle state for *state*.

    Legacy ``active``/``inactive``/``archived``/``closed`` values are accepted
    for compatibility and normalize to ``enabled``/``disabled``.
    """

    value = state.strip()
    if value in PROJECT_LIFECYCLE_LEGACY_ENABLED_STATES:
        return "enabled"
    if value in PROJECT_LIFECYCLE_LEGACY_DISABLED_STATES:
        return "disabled"
    if value in PROJECT_LIFECYCLE_STATES:
        return value
    raise ValueError(f"invalid project lifecycle state: {state}")


def is_disabled_project_lifecycle_state(state: str) -> bool:
    """Return whether *state* represents the canonical disabled state."""

    return normalize_project_lifecycle_state(state) == "disabled"


is_inactive_project_lifecycle_state = is_disabled_project_lifecycle_state


def normalize_project_lifecycle_state_filter(
    include_states: Sequence[str] | str,
) -> list[str]:
    """Return canonical states for a lifecycle filter.

    ``"all"`` expands to the canonical state set. Legacy state filters are
    accepted and mapped to their canonical replacements.
    """

    states = (
        [include_states] if isinstance(include_states, str) else list(include_states)
    )
    if any(state == "all" for state in states):
        return list(PROJECT_LIFECYCLE_STATES)
    normalized: list[str] = []
    for state in states:
        canonical = normalize_project_lifecycle_state(state)
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


@dataclass(frozen=True)
class ProjectLifecycleWire:
    """Effective lifecycle state parsed from one ProjectSpec content string."""

    schema_version: int
    state: str
    explicit: bool
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", normalize_project_lifecycle_state(self.state))


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
    aliases: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)
    display_name: str | None = None
    is_project: bool = True
    vcs_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", normalize_project_lifecycle_state(self.state))


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
        state=normalize_project_lifecycle_state(str(data["state"])),
        explicit=bool(data["explicit"]),
        warnings=_str_list(data.get("warnings")),
    )


def project_record_from_dict(data: dict[str, Any]) -> ProjectRecordWire:
    """Build :class:`ProjectRecordWire` from a Rust/Python wire dict."""

    project_name = str(data["project_name"])
    state = normalize_project_lifecycle_state(str(data["state"]))
    system_managed = bool(data["system_managed"])
    return ProjectRecordWire(
        schema_version=int(data["schema_version"]),
        project_name=project_name,
        project_dir=str(data["project_dir"]),
        project_file=str(data["project_file"]),
        archive_file=_optional_str(data.get("archive_file")),
        workspace_dir=_optional_str(data.get("workspace_dir")),
        state=state,
        state_explicit=bool(data["state_explicit"]),
        system_managed=system_managed,
        active_claim_count=int(data["active_claim_count"]),
        launchable=bool(data["launchable"]),
        aliases=_str_list(data.get("aliases")),
        warnings=_str_list(data.get("warnings")),
        parse_warnings=_str_list(data.get("parse_warnings")),
        display_name=_optional_str(data.get("display_name")),
        is_project=bool(
            data.get(
                "is_project",
                not system_managed and state != "sibling",
            )
        ),
        vcs_kind=_optional_str(data.get("vcs_kind")),
    )


def effective_project_name(record: ProjectRecordWire) -> str:
    """Return the user-facing project name for *record*."""

    return record.display_name or record.project_name


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
    "PROJECT_LIFECYCLE_COMPAT_STATES",
    "PROJECT_LIFECYCLE_LEGACY_DISABLED_STATES",
    "PROJECT_LIFECYCLE_LEGACY_ENABLED_STATES",
    "PROJECT_LIFECYCLE_STATES",
    "PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION",
    "ProjectLifecycleWire",
    "ProjectRecordWire",
    "effective_project_name",
    "is_disabled_project_lifecycle_state",
    "is_inactive_project_lifecycle_state",
    "normalize_project_lifecycle_state",
    "normalize_project_lifecycle_state_filter",
    "project_lifecycle_from_dict",
    "project_lifecycle_wire_to_json_dict",
    "project_record_from_dict",
]
