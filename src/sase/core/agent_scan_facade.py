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

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVerifyWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    DismissedAgentIdentityWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_update_from_dict,
    agent_scan_wire_to_json_dict,
    agent_scan_wire_from_dict,
    dismissed_agent_identity_to_dict,
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


def _record_diagnostic_name(record: AgentArtifactRecordWire) -> str:
    if record.agent_meta is not None and record.agent_meta.name:
        return record.agent_meta.name
    if record.done is not None and record.done.name:
        return record.done.name
    if record.done is not None and record.done.cl_name:
        return record.done.cl_name
    if record.workflow_state is not None and record.workflow_state.cl_name:
        return record.workflow_state.cl_name
    if record.workflow_state is not None:
        return record.workflow_state.workflow_name
    return ""


def _record_matches_diagnostic_pattern(
    record: AgentArtifactRecordWire,
    pattern: str,
) -> bool:
    candidates = [
        record.timestamp,
        record.artifact_dir,
        record.workflow_dir_name,
        _record_diagnostic_name(record),
    ]
    wildcard = any(ch in pattern for ch in "*?[]")
    for candidate in candidates:
        if not candidate:
            continue
        if wildcard and fnmatchcase(candidate, pattern):
            return True
        if not wildcard and pattern in candidate:
            return True
    return False


def _diagnostic_rows_for_pattern(
    snapshot: AgentArtifactScanWire,
    pattern: str,
) -> list[dict[str, str]]:
    return [
        {
            "timestamp": record.timestamp,
            "name": _record_diagnostic_name(record),
            "workflow_dir_name": record.workflow_dir_name,
            "artifact_dir": record.artifact_dir,
        }
        for record in snapshot.records
        if _record_matches_diagnostic_pattern(record, pattern)
    ]


def diagnose_agent_artifact_index_timestamps(
    index_path: Path | str,
    projects_root: Path | str,
    pattern: str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> dict[str, object]:
    """Compare source artifact timestamps with indexed timestamps for *pattern*.

    This is a targeted, read-only diagnostic for Agents-tab freshness issues:
    when a specific agent family such as ``sase-3r`` exists under
    ``~/.sase/projects`` but is absent from the persistent sqlite index, the
    returned ``missing_timestamps`` list names the source rows the Tier 1 path
    cannot currently see.
    """
    index = Path(index_path).expanduser()
    root = Path(projects_root).expanduser()
    opts = options or AgentArtifactScanOptionsWire()
    source = scan_agent_artifacts(root, opts)
    source_rows = _diagnostic_rows_for_pattern(source, pattern)

    indexed_error: str | None = None
    if index.is_file():
        try:
            indexed = query_agent_artifact_index(
                index,
                root,
                AgentArtifactIndexQueryWire(
                    include_active=False,
                    include_recent_completed=False,
                    include_full_history=True,
                    recent_completed_limit=None,
                    include_hidden=True,
                    include_dismissed=True,
                ),
                opts,
            )
            indexed_rows = _diagnostic_rows_for_pattern(indexed, pattern)
        except (OSError, RuntimeError, ValueError, ImportError, AttributeError) as exc:
            indexed_error = str(exc)
            indexed_rows = []
    else:
        indexed_rows = []

    source_timestamps = sorted({row["timestamp"] for row in source_rows})
    indexed_timestamps = sorted({row["timestamp"] for row in indexed_rows})
    source_set = set(source_timestamps)
    indexed_set = set(indexed_timestamps)
    missing_timestamps = sorted(source_set - indexed_set)
    extra_timestamps = sorted(indexed_set - source_set)

    return {
        "ok": not missing_timestamps and not extra_timestamps and indexed_error is None,
        "pattern": pattern,
        "index_path": str(index),
        "projects_root": str(root),
        "source_rows": len(source.records),
        "indexed_rows": len(indexed_rows),
        "matched_source_rows": len(source_rows),
        "matched_indexed_rows": len(indexed_rows),
        "source_timestamps": source_timestamps,
        "indexed_timestamps": indexed_timestamps,
        "missing_timestamps": missing_timestamps,
        "extra_timestamps": extra_timestamps,
        "indexed_error": indexed_error,
        "source_matches": source_rows,
        "indexed_matches": indexed_rows,
    }


# pyvision: docs/rust_backend.md
def upsert_dismissed_agent_visibility(
    index_path: Path | str,
    identity: DismissedAgentIdentityWire,
) -> AgentArtifactIndexUpdateWire:
    """Upsert one dismissed-agent identity into the index sidecar.

    Added in Phase 2 of ``sase-3r`` (Fast Agents Tab Disk Loading). The
    sidecar lets the visibility-aware inbox query (Phase 3) exclude
    completed artifact rows whose identity matches a dismissed entry. The
    update is best-effort: missing or stale Rust bindings raise the usual
    ``ImportError`` / ``AttributeError``.
    """

    rust_upsert = require_rust_binding("upsert_dismissed_agent_visibility")
    payload: dict[str, Any] = rust_upsert(
        str(index_path),
        dismissed_agent_identity_to_dict(identity),
    )
    return agent_artifact_index_update_from_dict(payload)


# pyvision: docs/rust_backend.md
def delete_dismissed_agent_visibility(
    index_path: Path | str,
    agent_type: str,
    cl_name: str,
    raw_suffix: str | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Remove one dismissed-agent identity from the index sidecar.

    Revives the matching completed artifact rows in future visibility-aware
    queries. Identities are addressed by exact match on
    ``(agent_type, cl_name, raw_suffix)``; ``raw_suffix=None`` targets the
    "whole identity" sentinel row.
    """

    rust_delete = require_rust_binding("delete_dismissed_agent_visibility")
    payload: dict[str, Any] = rust_delete(
        str(index_path), agent_type, cl_name, raw_suffix
    )
    return agent_artifact_index_update_from_dict(payload)


def replace_dismissed_agent_visibility(
    index_path: Path | str,
    identities: list[DismissedAgentIdentityWire],
) -> AgentArtifactIndexUpdateWire:
    """Atomically replace the dismissed-agent sidecar contents.

    Mirrors the bulk-sync path the TUI uses when reading the legacy
    ``~/.sase/dismissed_agents.json`` file at startup.
    """

    rust_replace = require_rust_binding("replace_dismissed_agent_visibility")
    payload: dict[str, Any] = rust_replace(
        str(index_path),
        [dismissed_agent_identity_to_dict(identity) for identity in identities],
    )
    return agent_artifact_index_update_from_dict(payload)


def verify_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexVerifyWire:
    """Compare the persistent artifact index to source artifact files."""
    index = Path(index_path).expanduser()
    root = Path(projects_root).expanduser()
    opts = options or AgentArtifactScanOptionsWire()
    source = scan_agent_artifacts(root, opts)

    if not index.is_file():
        return AgentArtifactIndexVerifyWire(
            ok=not source.records,
            schema_version=0,
            index_path=str(index),
            projects_root=str(root),
            indexed_rows=0,
            source_rows=len(source.records),
            missing_rows=len(source.records),
            corrupt_rows=source.stats.json_decode_errors,
        )

    try:
        indexed = query_agent_artifact_index(
            index,
            root,
            AgentArtifactIndexQueryWire(
                include_active=False,
                include_recent_completed=False,
                include_full_history=True,
                recent_completed_limit=None,
                include_hidden=True,
                include_dismissed=True,
            ),
            opts,
        )
    except (OSError, RuntimeError, ValueError, ImportError, AttributeError):
        return AgentArtifactIndexVerifyWire(
            ok=False,
            schema_version=0,
            index_path=str(index),
            projects_root=str(root),
            source_rows=len(source.records),
            missing_rows=len(source.records),
            corrupt_rows=source.stats.json_decode_errors + 1,
        )

    source_by_dir = {
        record.artifact_dir: agent_scan_wire_to_json_dict(record)
        for record in source.records
    }
    indexed_by_dir = {
        record.artifact_dir: agent_scan_wire_to_json_dict(record)
        for record in indexed.records
    }
    source_dirs = set(source_by_dir)
    indexed_dirs = set(indexed_by_dir)
    common_dirs = source_dirs & indexed_dirs
    stale_rows = sum(
        1
        for artifact_dir in common_dirs
        if indexed_by_dir[artifact_dir] != source_by_dir[artifact_dir]
    )
    missing_rows = len(source_dirs - indexed_dirs)
    extra_rows = len(indexed_dirs - source_dirs)
    corrupt_rows = (
        indexed.stats.json_decode_errors
        + indexed.stats.os_errors
        + source.stats.json_decode_errors
        + source.stats.os_errors
    )

    return AgentArtifactIndexVerifyWire(
        ok=not (stale_rows or missing_rows or extra_rows or corrupt_rows),
        schema_version=AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
        index_path=str(index),
        projects_root=str(root),
        indexed_rows=len(indexed.records),
        source_rows=len(source.records),
        stale_rows=stale_rows,
        missing_rows=missing_rows,
        extra_rows=extra_rows,
        corrupt_rows=corrupt_rows,
    )


__all__ = [
    "AgentArtifactRecordWire",
    "AgentArtifactIndexQueryWire",
    "AgentArtifactIndexUpdateWire",
    "AgentArtifactIndexVerifyWire",
    "AgentArtifactScanOptionsWire",
    "AgentArtifactScanStatsWire",
    "AgentArtifactScanWire",
    "AgentMetaWire",
    "DismissedAgentIdentityWire",
    "DoneMarkerWire",
    "PendingQuestionMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
    "default_agent_artifact_index_path",
    "delete_agent_artifact_index_row",
    "delete_dismissed_agent_visibility",
    "diagnose_agent_artifact_index_timestamps",
    "query_agent_artifact_index",
    "rebuild_agent_artifact_index",
    "replace_dismissed_agent_visibility",
    "scan_agent_artifacts",
    "upsert_agent_artifact_index_row",
    "upsert_dismissed_agent_visibility",
    "verify_agent_artifact_index",
]
