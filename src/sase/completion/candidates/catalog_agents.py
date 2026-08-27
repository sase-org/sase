"""Catalog fetchers for live agent runtime state.

Agents, monitors, procs, and artifact files are all read from cached runtime
indexes, never by scanning live agent directories; see
:mod:`sase.completion.candidates.catalog` for the import contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.completion.candidates.catalog_support import (
    dedupe,
    project_records_and_snapshot,
)
from sase.completion.candidates.protocol import Candidate

if TYPE_CHECKING:
    from sase.core.agent_scan_wire import AgentArtifactScanWire


def _query_agent_index(*, only_monitors: bool) -> AgentArtifactScanWire:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        query_agent_artifact_index,
    )
    from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire
    from sase.core.paths import sase_projects_dir

    return query_agent_artifact_index(
        default_agent_artifact_index_path(),
        sase_projects_dir(),
        query=AgentArtifactIndexQueryWire(
            only_monitors=only_monitors,
            freshness="cached",
        ),
    )


def agent_source_path(_project: str | None) -> Path | None:
    """Return the agent artifact index whose mtime invalidates agent names."""
    from sase.core.agent_scan_facade import default_agent_artifact_index_path

    return default_agent_artifact_index_path()


def agent_candidates(project: str | None) -> list[Candidate]:
    """Return every known agent name, described by its project."""
    try:
        scan = _query_agent_index(only_monitors=False)
    except Exception:
        return []
    _records, snapshot = project_records_and_snapshot(project)
    candidates: list[Candidate] = []
    for record in scan.records:
        if project is not None and record.project_name != project:
            continue
        name = None
        if record.agent_meta is not None and record.agent_meta.name:
            name = record.agent_meta.name
        elif record.done is not None and record.done.name:
            name = record.done.name
        if not name:
            continue
        candidates.append(Candidate(name, snapshot.label_for(record.project_name)))
    return dedupe(candidates)


def monitor_source_path(_project: str | None) -> Path | None:
    """Return the agent artifact index whose mtime invalidates monitor ids."""
    from sase.core.agent_scan_facade import default_agent_artifact_index_path

    return default_agent_artifact_index_path()


def monitor_candidates(project: str | None) -> list[Candidate]:
    """Return every monitor id, described by its label or agent name."""
    try:
        scan = _query_agent_index(only_monitors=True)
    except Exception:
        return []
    candidates: list[Candidate] = []
    for record in scan.records:
        if project is not None and record.project_name != project:
            continue
        meta = record.agent_meta
        shell = None if meta is None else meta.family_shell
        monitor_shell = shell if shell is not None and shell.kind == "monitor" else None
        if meta is None or meta.agent_family_role != "monitor" or monitor_shell is None:
            continue
        monitor_id = monitor_shell.id
        if not monitor_id:
            continue
        description = monitor_shell.label or meta.name or ""
        candidates.append(Candidate(monitor_id, description))
    return dedupe(candidates)


def proc_source_path(_project: str | None) -> Path | None:
    """Return the procs journal whose mtime invalidates proc candidates."""
    from sase.core.paths import sase_subdir

    return sase_subdir("procs") / "procs.jsonl"


def proc_candidates(project: str | None) -> list[Candidate]:
    """Return every proc id in the procs snapshot, with status and label."""
    from sase.core.rust import require_rust_binding

    path = proc_source_path(project)
    if path is None or not path.is_file():
        return []
    try:
        payload = require_rust_binding("read_procs_snapshot")(str(path))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    raw_procs = payload.get("procs")
    if raw_procs is None:
        raw_procs = payload.get("tasks")
    if not isinstance(raw_procs, list):
        return []
    candidates: list[Candidate] = []
    for item in raw_procs:
        if not isinstance(item, dict):
            continue
        if project is not None and str(item.get("project") or "") not in {project, ""}:
            continue
        proc_id = str(item.get("proc_id") or "")
        if not proc_id:
            continue
        status = str(item.get("status") or "")
        label = str(item.get("label") or "")
        candidates.append(
            Candidate(proc_id, " ".join(part for part in (status, label) if part))
        )
    return dedupe(candidates)


def artifact_source_path(_project: str | None) -> Path | None:
    """Return the artifact index whose mtime invalidates artifact candidates."""
    from sase.core.paths import sase_home

    return sase_home() / "artifacts" / "index.jsonl"


def artifact_candidates(project: str | None) -> list[Candidate]:
    """Return the most recent artifact file ids, with their labels."""
    from sase.core.rust import require_rust_binding

    index = artifact_source_path(project)
    if index is None:
        return []
    filters: dict[str, object] = {
        "agent": None,
        "explicit_only": False,
        "kinds": None,
        "limit": 200,
        "project": project,
        "query": None,
        "since": None,
        "unused_only": False,
    }
    try:
        rows = require_rust_binding("artifact_files_query")(str(index), filters)
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    candidates: list[Candidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = str(row.get("id") or "")
        if not value:
            continue
        candidates.append(Candidate(value, str(row.get("label") or "")))
    return dedupe(candidates)


def artifact_ref_source_path(project: str | None) -> Path | None:
    """Return the artifact index whose mtime invalidates artifact references."""
    return artifact_source_path(project)


def artifact_ref_candidates(project: str | None) -> list[Candidate]:
    """Return the most recent artifact files as canonical ``file:`` refs."""
    return [
        Candidate(f"file:{candidate.value}", candidate.description)
        for candidate in artifact_candidates(project)
    ]


__all__ = [
    "agent_candidates",
    "agent_source_path",
    "artifact_candidates",
    "artifact_ref_candidates",
    "artifact_ref_source_path",
    "artifact_source_path",
    "monitor_candidates",
    "monitor_source_path",
    "proc_candidates",
    "proc_source_path",
]
