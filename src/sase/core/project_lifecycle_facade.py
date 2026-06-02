"""Python facade for Rust-backed ProjectSpec lifecycle helpers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core.paths import is_valid_sase_project_name
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectLifecycleWire,
    ProjectRecordWire,
    project_lifecycle_from_dict,
    project_record_from_dict,
)
from sase.core.rust import require_rust_binding

_PROJECT_HEADER_STOP_PREFIXES = ("NAME:",)


def _project_header_lines(content: str) -> list[str]:
    lines: list[str] = []
    for line in content.splitlines():
        if line.startswith(_PROJECT_HEADER_STOP_PREFIXES):
            break
        lines.append(line)
    return lines


def _read_lifecycle_from_project_header(content: str) -> ProjectLifecycleWire:
    warnings: list[str] = []
    for line in _project_header_lines(content):
        if not line.startswith("PROJECT_STATE:"):
            continue
        state = line.split(":", 1)[1].strip() or "active"
        if state not in PROJECT_LIFECYCLE_STATES:
            warnings.append(f"invalid PROJECT_STATE {state!r}; defaulting to active")
            state = "active"
        return ProjectLifecycleWire(
            schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
            state=state,
            explicit=True,
            warnings=warnings,
        )
    return ProjectLifecycleWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        state="active",
        explicit=False,
        warnings=[],
    )


def _apply_lifecycle_update_to_project_header(content: str, state: str) -> str:
    if state not in PROJECT_LIFECYCLE_STATES:
        raise ValueError(f"invalid project state: {state}")

    lines = content.splitlines(keepends=True)
    state_line = f"PROJECT_STATE: {state}\n"
    for index, line in enumerate(lines):
        if line.startswith("PROJECT_STATE:"):
            lines[index] = state_line
            return "".join(lines)

    insert_index = len(lines)
    for index, line in enumerate(lines):
        if line.startswith(("RUNNING:", "NAME:")):
            insert_index = index
            break
    lines.insert(insert_index, state_line)
    return "".join(lines)


def _workspace_dir_from_project_header(content: str) -> str | None:
    for line in _project_header_lines(content):
        if line.startswith("WORKSPACE_DIR:"):
            value = line.split(":", 1)[1].strip()
            return value or None
    return None


def _workspace_claim_count(content: str) -> int:
    try:
        binding = require_rust_binding("list_workspace_claims_from_content")
    except (ImportError, AttributeError):
        return 0
    try:
        claims = binding(content)
    except Exception:
        return 0
    return len(claims) if isinstance(claims, list) else 0


def _preferred_project_spec_path(
    project_dir: Path,
    project_name: str,
    *,
    archive: bool = False,
) -> Path:
    suffix = "-archive" if archive else ""
    canonical = project_dir / f"{project_name}{suffix}.sase"
    if canonical.exists():
        return canonical
    legacy = project_dir / f"{project_name}{suffix}.gp"
    if legacy.exists():
        return legacy
    return canonical


def _fallback_project_record(project_dir: Path) -> ProjectRecordWire | None:
    project_name = project_dir.name
    if not is_valid_sase_project_name(project_name):
        return None

    project_file = _preferred_project_spec_path(project_dir, project_name)
    archive_file = _preferred_project_spec_path(project_dir, project_name, archive=True)
    archive_file_text = str(archive_file) if archive_file.is_file() else None
    warnings: list[str] = []
    parse_warnings: list[str] = []
    content = ""

    if project_file.is_file():
        try:
            content = project_file.read_text(encoding="utf-8")
        except OSError as exc:
            warnings.append(f"could not read active ProjectSpec file: {exc}")
    else:
        warnings.append(f"active ProjectSpec file not found: {project_file}")

    lifecycle = _read_lifecycle_from_project_header(content)
    parse_warnings.extend(lifecycle.warnings)
    workspace_dir = _workspace_dir_from_project_header(content)
    active_claim_count = _workspace_claim_count(content)
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=archive_file_text,
        workspace_dir=workspace_dir,
        state=lifecycle.state,
        state_explicit=lifecycle.explicit,
        system_managed=project_name == "home",
        active_claim_count=active_claim_count,
        launchable=lifecycle.state == "active" and workspace_dir is not None,
        warnings=warnings,
        parse_warnings=parse_warnings,
    )


def _normalize_include_states(include_states: Sequence[str] | str) -> list[str]:
    if include_states == "all":
        return list(PROJECT_LIFECYCLE_STATES)
    states = (
        [include_states] if isinstance(include_states, str) else list(include_states)
    )
    invalid = [state for state in states if state not in PROJECT_LIFECYCLE_STATES]
    if invalid:
        raise ValueError(f"invalid project state: {invalid[0]}")
    return states


def read_project_lifecycle_from_content(content: str) -> ProjectLifecycleWire:
    """Parse effective ProjectSpec lifecycle state via ``sase_core_rs``."""

    try:
        binding = require_rust_binding("read_project_lifecycle_from_content")
    except AttributeError:
        return _read_lifecycle_from_project_header(content)
    payload: dict[str, Any] = binding(content)
    return project_lifecycle_from_dict(dict(payload))


def apply_project_lifecycle_update(content: str, state: str) -> str:
    """Return ProjectSpec content with ``PROJECT_STATE`` updated by Rust."""

    try:
        binding = require_rust_binding("apply_project_lifecycle_update")
    except AttributeError:
        return _apply_lifecycle_update_to_project_header(content, state)
    return binding(content, state)  # type: ignore[no-any-return]


def list_project_records(
    projects_root: Path | str,
    include_states: Sequence[str] | str = ("active",),
    *,
    include_home: bool = False,
) -> list[ProjectRecordWire]:
    """List lifecycle records under a projects root via ``sase_core_rs``."""

    states = _normalize_include_states(include_states)
    try:
        binding = require_rust_binding("list_project_records")
    except AttributeError:
        root = Path(projects_root).expanduser()
        if not root.is_dir():
            return []
        records: list[ProjectRecordWire] = []
        for project_dir in sorted(root.iterdir()):
            if not project_dir.is_dir():
                continue
            record = _fallback_project_record(project_dir)
            if record is None:
                continue
            if record.project_name == "home" and not include_home:
                continue
            if record.state not in states:
                continue
            records.append(record)
        return records

    payload: list[dict[str, Any]] = binding(str(projects_root), states, include_home)
    return [
        project_record_from_dict(dict(item))
        for item in payload
        if is_valid_sase_project_name(str(item.get("project_name", "")))
    ]


__all__ = [
    "ProjectLifecycleWire",
    "ProjectRecordWire",
    "apply_project_lifecycle_update",
    "list_project_records",
    "read_project_lifecycle_from_content",
]
