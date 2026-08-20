"""sase.core facade for the agent/artifact filesystem snapshot scan.

:func:`scan_agent_artifacts` and :func:`scan_agent_artifact_dirs` call
``sase_core_rs`` directly through :func:`sase.core.rust.require_rust_binding`
and rehydrate returned dicts into typed wire records. The Rust extension is
a hard runtime dependency; a missing or stale wheel surfaces as
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
from collections.abc import Sequence
from typing import Any

from sase.core.agent_alias_history_wire import (
    AgentAliasHistoryQueryWire,
    AgentAliasHistoryWire,
    agent_alias_history_from_dict,
    agent_alias_history_query_to_dict,
)
from sase.core.agent_cleanup_wire import (
    AgentCleanupIdentityWire,
    agent_cleanup_wire_to_json_dict,
)
from sase.core.agent_artifact_index_lock import (
    agent_artifact_index_operation_lock,
    try_agent_artifact_index_operation_lock,
)
from sase.core.agent_output_variable_history_wire import (
    AgentOutputVariableHistoryQueryWire,
    AgentOutputVariableHistoryWire,
    agent_output_variable_history_from_dict,
    agent_output_variable_history_query_to_dict,
)
from sase.core.agent_output_variable_selector_wire import (
    AgentOutputVariableSelectorQueryWire,
    AgentOutputVariableSelectorResultWire,
    OutputVariableSelectorWire,
    agent_output_variable_selector_query_to_dict,
    agent_output_variable_selector_result_from_dict,
    output_variable_selector_from_dict,
)
from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexUpdateWire,
    AgentArtifactIndexVerifyWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentClanContextWire,
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
    WorkflowStepStateWire,
    agent_artifact_index_query_to_dict,
    agent_artifact_index_status_from_dict,
    agent_artifact_index_update_from_dict,
    agent_scan_wire_to_json_dict,
    agent_scan_wire_from_dict,
)
from sase.core.paths import sase_home as _sase_home
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
        "include_project_states": list(options.include_project_states),
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


def scan_agent_artifact_dirs(
    projects_root: Path | str,
    artifact_dirs: Sequence[Path | str],
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return a scanner-shaped snapshot for exact artifact directories."""
    opts = options or AgentArtifactScanOptionsWire()
    rust_scan = require_rust_binding("scan_agent_artifact_dirs")
    payload: dict[str, Any] = rust_scan(
        str(projects_root),
        [str(Path(path).expanduser()) for path in artifact_dirs],
        _options_to_dict(opts),
    )
    return agent_scan_wire_from_dict(payload)


def default_agent_artifact_index_path(sase_home: Path | str | None = None) -> Path:
    """Return the default persistent artifact index path."""
    root = Path(sase_home).expanduser() if sase_home is not None else _sase_home()
    return root / "agent_artifact_index.sqlite"


def rebuild_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Rebuild the persistent artifact index from source artifact files."""
    opts = options or AgentArtifactScanOptionsWire()
    with agent_artifact_index_operation_lock():
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
    with agent_artifact_index_operation_lock():
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
    with agent_artifact_index_operation_lock():
        rust_delete = require_rust_binding("delete_agent_artifact_index_row")
        payload: dict[str, Any] = rust_delete(str(index_path), str(artifact_dir))
    return agent_artifact_index_update_from_dict(payload)


def delete_agent_artifact_index_row_bounded(
    index_path: Path | str,
    artifact_dir: Path | str,
    *,
    lock_timeout_seconds: float,
    busy_timeout_seconds: float,
) -> AgentArtifactIndexUpdateWire | None:
    """Delete one row without waiting indefinitely on process/SQLite locks.

    ``None`` means the process-local lock was busy and the caller should retry
    later. SQLite timeout errors remain exceptions so lifecycle callers can
    distinguish a skipped mutation from a successful zero-row delete.
    """
    with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
        if not acquired:
            return None
        rust_delete = require_rust_binding("delete_agent_artifact_index_row_bounded")
        payload: dict[str, Any] = rust_delete(
            str(index_path),
            str(artifact_dir),
            max(0, round(busy_timeout_seconds * 1000.0)),
        )
    return agent_artifact_index_update_from_dict(payload)


def terminalize_stale_active_agent_artifact_index_rows(
    index_path: Path | str,
    projects_root: Path | str,
    *,
    stale_after_seconds: int,
    max_rows: int | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Mark stale, unclaimed no-marker active rows terminal in the index."""
    opts = options or AgentArtifactScanOptionsWire()
    with agent_artifact_index_operation_lock():
        rust_terminalize = require_rust_binding(
            "terminalize_stale_active_agent_artifact_index_rows"
        )
        payload: dict[str, Any] = rust_terminalize(
            str(index_path),
            str(projects_root),
            int(stale_after_seconds),
            max_rows,
            _options_to_dict(opts),
        )
    return agent_artifact_index_update_from_dict(payload)


def prune_hidden_terminal_agent_artifact_index_rows(
    index_path: Path | str,
    *,
    hot_rows: int | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Prune old hidden terminal rows from the hot artifact index view."""
    with agent_artifact_index_operation_lock():
        rust_prune = require_rust_binding(
            "prune_hidden_terminal_agent_artifact_index_rows"
        )
        payload: dict[str, Any] = rust_prune(str(index_path), hot_rows)
    return agent_artifact_index_update_from_dict(payload)


def replace_agent_artifact_index_dismissed_agents(
    index_path: Path | str,
    dismissed: Sequence[AgentCleanupIdentityWire],
) -> AgentArtifactIndexUpdateWire:
    """Replace the artifact index's dismissed identity table."""
    with agent_artifact_index_operation_lock():
        rust_replace = require_rust_binding(
            "replace_agent_artifact_index_dismissed_agents"
        )
        payload: dict[str, Any] = rust_replace(
            str(index_path),
            agent_cleanup_wire_to_json_dict(list(dismissed)),
        )
    return agent_artifact_index_update_from_dict(payload)


def read_agent_artifact_index_meta(
    index_path: Path | str,
    key: str,
) -> str | None:
    """Read one metadata value from the persistent artifact index."""
    with agent_artifact_index_operation_lock():
        rust_read = require_rust_binding("read_agent_artifact_index_meta")
        value = rust_read(str(index_path), str(key))
    return None if value is None else str(value)


def write_agent_artifact_index_meta(
    index_path: Path | str,
    key: str,
    value: str,
) -> None:
    """Write one metadata value in the persistent artifact index."""
    with agent_artifact_index_operation_lock():
        rust_write = require_rust_binding("write_agent_artifact_index_meta")
        rust_write(str(index_path), str(key), str(value))


def agent_artifact_index_status(
    index_path: Path | str,
) -> AgentArtifactIndexStatusWire:
    """Return lightweight row-count status for the persistent artifact index."""
    with agent_artifact_index_operation_lock():
        rust_status = require_rust_binding("agent_artifact_index_status")
        payload: dict[str, Any] = rust_status(str(index_path))
    return agent_artifact_index_status_from_dict(payload)


def query_agent_output_variable_history(
    index_path: Path | str,
    query: AgentOutputVariableHistoryQueryWire | None = None,
) -> AgentOutputVariableHistoryWire:
    """Return grouped output-variable history from the persistent artifact index."""
    query_wire = query or AgentOutputVariableHistoryQueryWire()
    with agent_artifact_index_operation_lock():
        rust_query = require_rust_binding("query_agent_output_variable_history")
        payload: dict[str, Any] = rust_query(
            str(index_path),
            agent_output_variable_history_query_to_dict(query_wire),
        )
    return agent_output_variable_history_from_dict(payload)


def query_agent_alias_history(
    index_path: Path | str,
    query: AgentAliasHistoryQueryWire,
) -> AgentAliasHistoryWire:
    """Return bounded per-alias agent history from the persistent artifact index."""
    with agent_artifact_index_operation_lock():
        rust_query = require_rust_binding("query_agent_alias_history")
        payload: dict[str, Any] = rust_query(
            str(index_path),
            agent_alias_history_query_to_dict(query),
        )
    return agent_alias_history_from_dict(payload)


def parse_output_variable_selector(selector: str) -> OutputVariableSelectorWire:
    """Parse one ``sase var get`` selector through the Rust domain parser."""
    rust_parse = require_rust_binding("parse_output_variable_selector")
    payload: dict[str, Any] = rust_parse(selector)
    return output_variable_selector_from_dict(payload)


def query_agent_output_variable_selectors(
    index_path: Path | str,
    query: AgentOutputVariableSelectorQueryWire | None = None,
) -> AgentOutputVariableSelectorResultWire:
    """Resolve output-variable selectors against the persistent artifact index."""
    query_wire = query or AgentOutputVariableSelectorQueryWire()
    with agent_artifact_index_operation_lock():
        rust_query = require_rust_binding("query_agent_output_variable_selectors")
        payload: dict[str, Any] = rust_query(
            str(index_path),
            agent_output_variable_selector_query_to_dict(query_wire),
        )
    return agent_output_variable_selector_result_from_dict(payload)


def query_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    query: AgentArtifactIndexQueryWire | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Return scanner-shaped records from the persistent artifact index."""
    opts = options or AgentArtifactScanOptionsWire()
    query_wire = query or AgentArtifactIndexQueryWire()
    with agent_artifact_index_operation_lock():
        rust_query = require_rust_binding("query_agent_artifact_index")
        payload: dict[str, Any] = rust_query(
            str(index_path),
            str(projects_root),
            agent_artifact_index_query_to_dict(query_wire),
            _options_to_dict(opts),
        )
    return agent_scan_wire_from_dict(payload)


def query_related_agent_artifact_dirs(
    index_path: Path | str,
    artifact_dir: Path | str,
    seed_timestamps: Sequence[str],
) -> list[Path]:
    """Return index-backed artifact dirs for one related agent lineage."""
    index = Path(index_path).expanduser()
    artifact = Path(artifact_dir).expanduser()
    seeds = [str(value) for value in seed_timestamps if value]
    with agent_artifact_index_operation_lock():
        rust_query = require_rust_binding("query_related_agent_artifact_dirs")
        payload: list[str] = rust_query(str(index), str(artifact), seeds)
    return [Path(path) for path in payload]


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
                active_limit=None,
                recent_completed_limit=None,
                include_hidden=True,
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
    "AgentArtifactIndexStatusWire",
    "AgentArtifactIndexQueryWire",
    "AgentArtifactIndexUpdateWire",
    "AgentArtifactIndexVerifyWire",
    "AgentArtifactScanOptionsWire",
    "AgentArtifactScanStatsWire",
    "AgentArtifactScanWire",
    "AgentClanContextWire",
    "AgentMetaWire",
    "DoneMarkerWire",
    "PendingQuestionMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
    "agent_artifact_index_status",
    "default_agent_artifact_index_path",
    "delete_agent_artifact_index_row",
    "delete_agent_artifact_index_row_bounded",
    "parse_output_variable_selector",
    "prune_hidden_terminal_agent_artifact_index_rows",
    "query_agent_alias_history",
    "query_agent_artifact_index",
    "query_agent_output_variable_history",
    "query_agent_output_variable_selectors",
    "query_related_agent_artifact_dirs",
    "read_agent_artifact_index_meta",
    "rebuild_agent_artifact_index",
    "replace_agent_artifact_index_dismissed_agents",
    "scan_agent_artifact_dirs",
    "scan_agent_artifacts",
    "terminalize_stale_active_agent_artifact_index_rows",
    "upsert_agent_artifact_index_row",
    "verify_agent_artifact_index",
    "write_agent_artifact_index_meta",
]
