"""sase.core facade for the agent/artifact filesystem snapshot scan.

:func:`scan_agent_artifacts` calls ``sase_core_rs.scan_agent_artifacts``
directly through :func:`sase.core.rust.require_rust_binding` and rehydrates
the returned dict into typed wire records. The Rust extension is a hard
runtime dependency; a missing or stale wheel surfaces as
:class:`ImportError` / :class:`AttributeError`.

The scanner is read-only: it does not check process liveness (that lives
in :mod:`sase.ace.hooks.processes` and ``/proc`` guards), does not parse
RUNNING-field claims (that lives in :mod:`sase.running_field`), and does
not mutate filesystem state. Soft errors (unreadable directories,
malformed marker JSON) are absorbed silently by the Rust scanner and
counted in :class:`AgentArtifactScanStatsWire`.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DoneMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_update_from_dict,
    agent_scan_wire_from_dict,
)
from sase.core.rust import require_rust_binding


def _options_to_dict(options: AgentArtifactScanOptionsWire) -> dict[str, Any]:
    return {
        "include_prompt_step_markers": options.include_prompt_step_markers,
        "include_raw_prompt_snippets": options.include_raw_prompt_snippets,
        "max_prompt_snippet_bytes": options.max_prompt_snippet_bytes,
        "only_workflow_dirs": list(options.only_workflow_dirs),
        "max_records": options.max_records,
        "newest_first": options.newest_first,
        "not_before_timestamp": options.not_before_timestamp,
        "include_done_markers": options.include_done_markers,
        "include_workflow_state": options.include_workflow_state,
        "include_waiting": options.include_waiting,
        "only_projects": list(options.only_projects),
    }


def scan_agent_artifacts(
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return a snapshot of all agent artifact directories under *projects_root*.

    ``projects_root`` is required and is normally
    ``Path.home() / ".sase" / "projects"`` — passing it explicitly keeps the
    contract testable and lets future shells (server, mobile) supply a
    different root without Rust reading global config. The Rust binding
    releases the GIL during the filesystem walk.
    """
    opts = options or AgentArtifactScanOptionsWire()
    rust_scan = require_rust_binding("scan_agent_artifacts")
    payload: dict[str, Any] = rust_scan(str(projects_root), _options_to_dict(opts))
    return agent_scan_wire_from_dict(payload)


def default_agent_artifact_index_path(sase_home: Path | str | None = None) -> Path:
    """Return the default persistent artifact index path."""
    root = (
        Path(sase_home).expanduser() if sase_home is not None else Path.home() / ".sase"
    )
    return root / "agent_artifact_index.sqlite"


def rebuild_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Rebuild the persistent artifact index from source artifact files."""
    opts = options or AgentArtifactScanOptionsWire()
    rust_rebuild = require_rust_binding("rebuild_agent_artifact_index")
    payload: dict[str, Any] = rust_rebuild(
        str(index_path), str(projects_root), _options_to_dict(opts)
    )
    return agent_artifact_index_update_from_dict(payload)


# pyvision: public_api_methods.txt
def upsert_agent_artifact_index_row(
    index_path: Path | str,
    projects_root: Path | str,
    artifact_dir: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Reparse and upsert one artifact directory into the index."""
    opts = options or AgentArtifactScanOptionsWire()
    rust_upsert = require_rust_binding("upsert_agent_artifact_index_row")
    payload: dict[str, Any] = rust_upsert(
        str(index_path),
        str(projects_root),
        str(artifact_dir),
        _options_to_dict(opts),
    )
    return agent_artifact_index_update_from_dict(payload)


# pyvision: public_api_methods.txt
def delete_agent_artifact_index_row(
    index_path: Path | str,
    artifact_dir: Path | str,
) -> AgentArtifactIndexUpdateWire:
    """Remove one artifact directory row from the index."""
    rust_delete = require_rust_binding("delete_agent_artifact_index_row")
    payload: dict[str, Any] = rust_delete(str(index_path), str(artifact_dir))
    return agent_artifact_index_update_from_dict(payload)


def query_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    query: AgentArtifactIndexQueryWire | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return scanner-shaped records from the persistent artifact index."""
    opts = options or AgentArtifactScanOptionsWire()
    query_wire = query or AgentArtifactIndexQueryWire()
    rust_query = require_rust_binding("query_agent_artifact_index")
    payload: dict[str, Any] = rust_query(
        str(index_path),
        str(projects_root),
        agent_artifact_index_query_to_dict(query_wire),
        _options_to_dict(opts),
    )
    return agent_scan_wire_from_dict(payload)


def with_options(
    base: AgentArtifactScanOptionsWire,
    **overrides: Any,
) -> AgentArtifactScanOptionsWire:
    """Return a copy of *base* with *overrides* applied.

    Convenience for callers that want to derive a tweaked options record
    without juggling :func:`dataclasses.replace` imports.
    """
    return replace(base, **overrides)


__all__ = [
    "AgentArtifactRecordWire",
    "AgentArtifactIndexQueryWire",
    "AgentArtifactIndexUpdateWire",
    "AgentArtifactScanOptionsWire",
    "AgentArtifactScanStatsWire",
    "AgentArtifactScanWire",
    "AgentMetaWire",
    "DoneMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
    "default_agent_artifact_index_path",
    "delete_agent_artifact_index_row",
    "query_agent_artifact_index",
    "rebuild_agent_artifact_index",
    "scan_agent_artifacts",
    "upsert_agent_artifact_index_row",
    "with_options",
]
