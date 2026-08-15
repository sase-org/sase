"""Shared resolution helpers for ``sase var show`` and ``sase var list``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import os
from pathlib import Path

from sase.agent.identity import agent_name_from_meta, resolve_local_agent_name
from sase.core.agent_artifact_index_lifecycle import (
    default_agent_artifact_projects_root,
    refresh_agent_artifact_index_if_schema_stale,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.time import get_timezone
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)
from sase.vcs_log.dates import TimeBound, parse_time_bound

_LAUNCHER_SENTINEL = "1"


def prepare_output_variable_index(
    *,
    index_path: Path | str | None = None,
    projects_root: Path | str | None = None,
) -> tuple[Path, Path]:
    """Refresh a stale artifact index and return ``(index, projects_root)``."""
    index = (
        Path(index_path).expanduser()
        if index_path is not None
        else default_agent_artifact_index_path()
    )
    root = (
        Path(projects_root).expanduser()
        if projects_root is not None
        else default_agent_artifact_projects_root()
    )
    refresh_agent_artifact_index_if_schema_stale(index_path=index, projects_root=root)
    return index, root


def resolve_current_var_agent_name(
    artifacts_dir: str | None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Resolve the current display identity without treating ``SASE_AGENT=1`` as a name."""
    current_env = env if env is not None else os.environ
    local_name = resolve_local_agent_name(current_env)
    if local_name:
        return local_name
    meta_name = agent_name_from_meta(artifacts_dir)
    if meta_name:
        return meta_name
    fallback = _clean_env(current_env.get("SASE_AGENT"))
    if fallback is not None and fallback != _LAUNCHER_SENTINEL:
        return fallback
    return None


def resolve_var_projects(
    refs: Sequence[str] | None,
    *,
    snapshot: ProjectRefDisplaySnapshot | None = None,
) -> tuple[list[str], ProjectRefDisplaySnapshot]:
    """Resolve display names/aliases to indexed project directory names."""
    display = snapshot or load_project_ref_display_snapshot()
    if not refs:
        return [], display
    resolved: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        key = display.project_key_for_ref(ref) or ref
        if key in seen:
            continue
        seen.add(key)
        resolved.append(key)
    return resolved, display


def display_project_name(
    project_name: str,
    snapshot: ProjectRefDisplaySnapshot,
) -> str:
    """Return the configured label for an indexed project directory name."""
    return snapshot.label_for_ref(project_name) or project_name


def artifact_timestamp_from_date(value: str, *, boundary: str) -> str:
    """Normalize a DATE token to an inclusive ``YYYYmmddHHMMSS`` bound."""
    spec: TimeBound = parse_time_bound(value)
    epoch = spec.resolve(boundary="since" if boundary == "since" else "until")
    return datetime.fromtimestamp(epoch, tz=get_timezone()).strftime("%Y%m%d%H%M%S")


def resolve_named_var_artifact(
    agent_name: str,
    *,
    project: str | None = None,
    include_hidden: bool = False,
    index_path: Path | str | None = None,
    projects_root: Path | str | None = None,
    display: ProjectRefDisplaySnapshot | None = None,
) -> AgentArtifactRecordWire | None:
    """Return the newest visible exact-name artifact, or ``None`` if unknown."""
    index, root = prepare_output_variable_index(
        index_path=index_path,
        projects_root=projects_root,
    )
    project_keys, _snapshot = resolve_var_projects(
        [project] if project else None,
        snapshot=display,
    )
    snapshot = query_agent_artifact_index(
        index,
        root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=True,
            include_full_history=True,
            active_limit=None,
            recent_completed_limit=None,
            include_hidden=include_hidden,
        ),
        AgentArtifactScanOptionsWire(
            include_prompt_step_markers=False,
            include_raw_prompt_snippets=False,
            only_projects=tuple(project_keys),
        ),
    )
    matches = [
        record
        for record in snapshot.records
        if record.agent_meta is not None and record.agent_meta.name == agent_name
    ]
    if not matches:
        return None
    newest = matches[0]
    for record in matches[1:]:
        if record.timestamp > newest.timestamp:
            newest = record
        elif record.timestamp == newest.timestamp and (
            record.project_name,
            record.artifact_dir,
        ) < (newest.project_name, newest.artifact_dir):
            newest = record
    return newest


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "artifact_timestamp_from_date",
    "display_project_name",
    "prepare_output_variable_index",
    "resolve_current_var_agent_name",
    "resolve_named_var_artifact",
    "resolve_var_projects",
]
