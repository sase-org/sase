"""Catalog fetchers for live agent runtime state.

Agents, monitors, procs, and artifact files are all read from cached runtime
indexes, never by scanning live agent directories; see
:mod:`sase.completion.candidates.catalog` for the import contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.completion.candidates.catalog_support import (
    dedupe,
    project_records_and_snapshot,
)
from sase.completion.candidates.protocol import Candidate


def _query_agent_index(*, only_monitors: bool) -> tuple[Mapping[str, Any], ...]:
    from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
    from sase.core.paths import sase_home
    from sase.core.paths import sase_projects_dir
    from sase.core.rust import require_rust_binding

    query = {
        "include_active": True,
        "include_recent_completed": True,
        "include_full_history": False,
        "active_limit": None,
        "recent_completed_limit": 200,
        "include_hidden": False,
        "freshness": "cached",
        "only_monitors": only_monitors,
        "record_shape": "list",
        "window_limit": None,
        "candidate_filter": None,
    }
    options = {
        "include_prompt_step_markers": False,
        "include_raw_prompt_snippets": False,
        "max_prompt_snippet_bytes": 0,
        "only_workflow_dirs": [],
        "max_records": None,
        "newest_first": False,
        "not_before_timestamp": None,
        "include_done_markers": True,
        "include_workflow_state": False,
        "include_waiting": False,
        "only_projects": [],
        "include_project_states": [],
    }
    with agent_artifact_index_operation_lock():
        payload = require_rust_binding("query_agent_artifact_index")(
            str(sase_home() / "agent_artifact_index.sqlite"),
            str(sase_projects_dir()),
            query,
            options,
        )
    if not isinstance(payload, Mapping):
        return ()
    records = payload.get("records")
    if not isinstance(records, list):
        return ()
    return tuple(record for record in records if isinstance(record, Mapping))


def agent_source_path(_project: str | None) -> Path | None:
    """Return the agent artifact index whose mtime invalidates agent names."""
    from sase.core.paths import sase_home

    return sase_home() / "agent_artifact_index.sqlite"


def agent_candidates(project: str | None) -> list[Candidate]:
    """Return every known agent name, described by its project."""
    try:
        records = _query_agent_index(only_monitors=False)
    except Exception:
        return []
    if not records:
        return []
    _records, snapshot = project_records_and_snapshot(project)
    candidates: list[Candidate] = []
    for record in records:
        project_name = str(record.get("project_name") or "")
        if project is not None and project_name != project:
            continue
        name = None
        meta = record.get("agent_meta")
        done = record.get("done")
        if isinstance(meta, Mapping) and meta.get("name"):
            name = str(meta["name"])
        elif isinstance(done, Mapping) and done.get("name"):
            name = str(done["name"])
        if not name:
            continue
        candidates.append(Candidate(name, snapshot.label_for(project_name)))
    return dedupe(candidates)


def monitor_source_path(_project: str | None) -> Path | None:
    """Return the agent artifact index whose mtime invalidates monitor ids."""
    from sase.core.paths import sase_home

    return sase_home() / "agent_artifact_index.sqlite"


def monitor_candidates(project: str | None) -> list[Candidate]:
    """Return every monitor id, described by its label or agent name."""
    try:
        records = _query_agent_index(only_monitors=True)
    except Exception:
        return []
    candidates: list[Candidate] = []
    for record in records:
        project_name = str(record.get("project_name") or "")
        if project is not None and project_name != project:
            continue
        meta = record.get("agent_meta")
        if not isinstance(meta, Mapping):
            continue
        shell = meta.get("family_shell")
        monitor_shell = (
            shell
            if isinstance(shell, Mapping) and shell.get("kind") == "monitor"
            else None
        )
        if meta.get("agent_family_role") != "monitor" or monitor_shell is None:
            continue
        monitor_id = str(monitor_shell.get("id") or "")
        if not monitor_id:
            continue
        description = str(monitor_shell.get("label") or meta.get("name") or "")
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
