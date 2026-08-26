"""Index-backed lookups for gate-shell family members."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.agent_scan_wire_markers import AgentMetaWire, DoneMarkerWire
from sase.core.paths import sase_projects_dir
from sase.core.wire import known_field_kwargs
from sase.gate_shell.models import GateShellRecord, is_gate_shell_member_record


def read_gate_shell_marker(
    project_name: str,
    artifacts_dir: str,
) -> GateShellRecord | None:
    """Read one gate-shell member directly from its own markers."""
    raw_meta = _read_json_object(os.path.join(artifacts_dir, "agent_meta.json"))
    if raw_meta is None:
        return None
    raw_done = _read_json_object(os.path.join(artifacts_dir, "done.json"))
    record = AgentArtifactRecordWire(
        project_name=project_name,
        project_dir="",
        project_file="",
        workflow_dir_name="",
        artifact_dir=artifacts_dir,
        timestamp=os.path.basename(artifacts_dir.rstrip("/")),
        agent_meta=AgentMetaWire(**known_field_kwargs(AgentMetaWire, raw_meta)),
        done=(
            DoneMarkerWire(**known_field_kwargs(DoneMarkerWire, raw_done))
            if raw_done is not None
            else None
        ),
    )
    try:
        return GateShellRecord.from_record(record)
    except ValueError:
        return None


def list_gate_shells(*, project: str | None = None) -> list[GateShellRecord]:
    """Return every gate-shell record, newest first."""
    records = [
        converted
        for converted in (
            _gate_record_from_wire(record) for record in _gate_records(project)
        )
        if converted is not None
    ]
    records.sort(
        key=lambda record: (record.timestamp, record.artifacts_dir),
        reverse=True,
    )
    return records


def has_any_gate_shell(project_name: str, lane: str) -> bool:
    """Return whether ``lane`` has ever had a gate-shell member."""
    return any(
        record.agent_meta is not None and record.agent_meta.agent_family == lane
        for record in _gate_records(project_name)
    )


def find_gate_shell_by_gate_id(
    project_name: str,
    gate_id: str,
) -> GateShellRecord | None:
    """Return the newest gate-shell member for ``gate_id``, if present."""
    matches = [
        record
        for record in list_gate_shells(project=project_name)
        if record.gate_id == gate_id
    ]
    return matches[0] if matches else None


def _read_json_object(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _gate_record_from_wire(record: AgentArtifactRecordWire) -> GateShellRecord | None:
    try:
        return GateShellRecord.from_record(record)
    except ValueError:
        return None


def _gate_records(project_name: str | None) -> list[AgentArtifactRecordWire]:
    return [
        record
        for record in _project_records(project_name)
        if is_gate_shell_member_record(record)
    ]


def _project_records(project_name: str | None) -> list[AgentArtifactRecordWire]:
    projects_root = sase_projects_dir()
    options = AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project_name,) if project_name else (),
        max_records=None,
        newest_first=False,
    )
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=True,
        active_limit=None,
        recent_completed_limit=None,
        include_hidden=True,
        only_monitors=False,
    )
    index_path = default_agent_artifact_index_path()
    if index_path.is_file():
        try:
            scan = query_agent_artifact_index(index_path, projects_root, query, options)
            return list(scan.records)
        except (OSError, RuntimeError, ValueError, ImportError, AttributeError):
            pass
    scan = scan_agent_artifacts(projects_root, options)
    return list(scan.records)


__all__ = [
    "find_gate_shell_by_gate_id",
    "has_any_gate_shell",
    "list_gate_shells",
    "read_gate_shell_marker",
]
