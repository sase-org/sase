"""Stable import path for the agent/artifact filesystem snapshot scan.

The implementations live in sibling modules to keep each file under the
500-line cap, and are re-exported here:

- :mod:`sase.core.agent_scan_source` — lock-free filesystem scans and the
  output-variable selector parser.
- :mod:`sase.core.agent_scan_index` — index identity, layout aliases,
  metadata, status, and the source-reconcile watermark.
- :mod:`sase.core.agent_scan_index_mutations` — persistent index row
  writes (rebuild, upsert, delete, terminalize, prune, reconcile).
- :mod:`sase.core.agent_scan_index_queries` — persistent index reads
  (history, selectors, rows, related dirs) and index verification.
- :mod:`sase.core._agent_scan_shared` — scan-option rendering shared by
  the sibling modules.

The scanner is read-only: it does not check process liveness (that lives
in :mod:`sase.ace.hooks.processes` and ``/proc`` guards), does not parse
RUNNING-field claims (that lives in :mod:`sase.running_field`), and does
not mutate filesystem state. The Rust extension is a hard runtime
dependency; a missing or stale wheel surfaces as :class:`ImportError` /
:class:`AttributeError`.

This module keeps every historic monkeypatch seam as a settable
attribute and copies the live values into the implementation modules
before each delegated call, so patching
``sase.core.agent_scan_facade.<name>`` behaves exactly as it did when
this file held the implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Any

from sase.core.agent_alias_history_wire import AgentAliasHistoryQueryWire
from sase.core.agent_alias_history_wire import AgentAliasHistoryWire
from sase.core.agent_artifact_index_lock import DEFAULT_READ_LOCK_TIMEOUT_SECONDS
from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_artifact_index_lock import try_agent_artifact_index_operation_lock
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_output_variable_history_wire import (
    AgentOutputVariableHistoryQueryWire,
)
from sase.core.agent_output_variable_history_wire import AgentOutputVariableHistoryWire
from sase.core.agent_output_variable_selector_wire import (
    AgentOutputVariableSelectorQueryWire,
)
from sase.core.agent_output_variable_selector_wire import (
    AgentOutputVariableSelectorResultWire,
)
from sase.core.agent_output_variable_selector_wire import OutputVariableSelectorWire
from sase.core.agent_scan_wire import AgentArtifactIndexDismissalReconcileWire
from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire
from sase.core.agent_scan_wire import AgentArtifactIndexStatusWire
from sase.core.agent_scan_wire import AgentArtifactIndexUpdateWire
from sase.core.agent_scan_wire import AgentArtifactIndexVacuumWire
from sase.core.agent_scan_wire import AgentArtifactIndexVerifyWire
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.agent_scan_wire import AgentArtifactScanStatsWire
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.core.agent_scan_wire import AgentClanContextWire
from sase.core.agent_scan_wire import AgentMetaWire
from sase.core.agent_scan_wire import DoneMarkerWire
from sase.core.agent_scan_wire import PendingQuestionMarkerWire
from sase.core.agent_scan_wire import PlanPathMarkerWire
from sase.core.agent_scan_wire import PromptStepMarkerWire
from sase.core.agent_scan_wire import RunningMarkerWire
from sase.core.agent_scan_wire import WaitingMarkerWire
from sase.core.agent_scan_wire import WorkflowStateWire
from sase.core.agent_scan_wire import WorkflowStepStateWire
from sase.core.agent_scan_wire import agent_scan_wire_from_dict
from sase.core.rust import require_rust_binding

index_impl: Any = None
mutations_impl: Any = None
queries_impl: Any = None
source_impl: Any = None


def __getattr__(name: str) -> Any:
    """Load an implementation constant only when callers request it."""
    if name == "SOURCE_RECONCILE_OK_META_KEY":
        from sase.core.agent_scan_index import SOURCE_RECONCILE_OK_META_KEY

        return SOURCE_RECONCILE_OK_META_KEY
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Symvision cannot see Python's module-level lazy lookup hook.
_PACKAGE_GETATTR = __getattr__


def _sync_source_patchables() -> None:
    global source_impl
    if source_impl is None:
        source_impl = import_module("sase.core.agent_scan_source")
    source_impl.require_rust_binding = require_rust_binding


def _sync_index_patchables() -> None:
    global index_impl
    if index_impl is None:
        index_impl = import_module("sase.core.agent_scan_index")
    index_impl.require_rust_binding = require_rust_binding
    index_impl.agent_artifact_index_operation_lock = agent_artifact_index_operation_lock
    index_impl.try_agent_artifact_index_operation_lock = (
        try_agent_artifact_index_operation_lock
    )


def _sync_mutations_patchables() -> None:
    global mutations_impl
    if mutations_impl is None:
        mutations_impl = import_module("sase.core.agent_scan_index_mutations")
    mutations_impl.require_rust_binding = require_rust_binding
    mutations_impl.agent_artifact_index_operation_lock = (
        agent_artifact_index_operation_lock
    )
    mutations_impl.try_agent_artifact_index_operation_lock = (
        try_agent_artifact_index_operation_lock
    )


def _sync_queries_patchables() -> None:
    global queries_impl
    if queries_impl is None:
        queries_impl = import_module("sase.core.agent_scan_index_queries")
    queries_impl.require_rust_binding = require_rust_binding
    queries_impl.agent_artifact_index_operation_lock = (
        agent_artifact_index_operation_lock
    )
    queries_impl.try_agent_artifact_index_operation_lock = (
        try_agent_artifact_index_operation_lock
    )


def scan_agent_artifacts(
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    _sync_source_patchables()
    return source_impl.scan_agent_artifacts(projects_root, options)


def scan_agent_artifact_dirs(
    projects_root: Path | str,
    artifact_dirs: Sequence[Path | str],
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    _sync_source_patchables()
    return source_impl.scan_agent_artifact_dirs(projects_root, artifact_dirs, options)


def default_agent_artifact_index_path(sase_home: Path | str | None = None) -> Path:
    _sync_index_patchables()
    return index_impl.default_agent_artifact_index_path(sase_home)


def read_agent_artifact_index_schema_version(index_path: Path | str) -> int | None:
    _sync_index_patchables()
    return index_impl.read_agent_artifact_index_schema_version(index_path)


def load_agent_artifact_index_projection(
    index_path: Path | str,
    columns: Sequence[str],
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    _sync_index_patchables()
    return index_impl.load_agent_artifact_index_projection(
        index_path, columns, busy_timeout_ms=busy_timeout_ms
    )


def upsert_agent_artifact_alias(
    index_path: Path | str, alias_path: str, artifact_dir: str
) -> None:
    _sync_index_patchables()
    index_impl.upsert_agent_artifact_alias(index_path, alias_path, artifact_dir)


def delete_agent_artifact_alias(
    index_path: Path | str, alias_path: str, artifact_dir: str
) -> None:
    _sync_index_patchables()
    index_impl.delete_agent_artifact_alias(index_path, alias_path, artifact_dir)


def list_agent_artifact_aliases(index_path: Path | str) -> dict[str, str]:
    _sync_index_patchables()
    return index_impl.list_agent_artifact_aliases(index_path)


def rebuild_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    _sync_mutations_patchables()
    return mutations_impl.rebuild_agent_artifact_index(
        index_path, projects_root, options
    )


def upsert_agent_artifact_index_row(
    index_path: Path | str,
    projects_root: Path | str,
    artifact_dir: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    _sync_mutations_patchables()
    return mutations_impl.upsert_agent_artifact_index_row(
        index_path, projects_root, artifact_dir, options
    )


def delete_agent_artifact_index_row(
    index_path: Path | str,
    artifact_dir: Path | str,
) -> AgentArtifactIndexUpdateWire:
    _sync_mutations_patchables()
    return mutations_impl.delete_agent_artifact_index_row(index_path, artifact_dir)


def delete_agent_artifact_index_row_bounded(
    index_path: Path | str,
    artifact_dir: Path | str,
    *,
    lock_timeout_seconds: float,
    busy_timeout_seconds: float,
) -> AgentArtifactIndexUpdateWire | None:
    _sync_mutations_patchables()
    return mutations_impl.delete_agent_artifact_index_row_bounded(
        index_path,
        artifact_dir,
        lock_timeout_seconds=lock_timeout_seconds,
        busy_timeout_seconds=busy_timeout_seconds,
    )


def terminalize_stale_active_agent_artifact_index_rows(
    index_path: Path | str,
    projects_root: Path | str,
    *,
    stale_after_seconds: int,
    max_rows: int | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    _sync_mutations_patchables()
    return mutations_impl.terminalize_stale_active_agent_artifact_index_rows(
        index_path,
        projects_root,
        stale_after_seconds=stale_after_seconds,
        max_rows=max_rows,
        options=options,
    )


def prune_hidden_terminal_agent_artifact_index_rows(
    index_path: Path | str,
    *,
    hot_rows: int | None = None,
) -> AgentArtifactIndexUpdateWire:
    _sync_mutations_patchables()
    return mutations_impl.prune_hidden_terminal_agent_artifact_index_rows(
        index_path, hot_rows=hot_rows
    )


def replace_agent_artifact_index_dismissed_agents(
    index_path: Path | str,
    dismissed: Sequence[AgentCleanupIdentityWire],
    *,
    force: bool = False,
) -> AgentArtifactIndexUpdateWire:
    _sync_mutations_patchables()
    return mutations_impl.replace_agent_artifact_index_dismissed_agents(
        index_path, dismissed, force=force
    )


def reconcile_agent_artifact_index_dismissed_agent_session_members(
    index_path: Path | str,
    *,
    dry_run: bool = False,
) -> AgentArtifactIndexDismissalReconcileWire:
    _sync_mutations_patchables()
    return (
        mutations_impl.reconcile_agent_artifact_index_dismissed_agent_session_members(
            index_path, dry_run=dry_run
        )
    )


def read_agent_artifact_index_meta(
    index_path: Path | str,
    key: str,
) -> str | None:
    _sync_index_patchables()
    return index_impl.read_agent_artifact_index_meta(index_path, key)


def write_agent_artifact_index_meta(
    index_path: Path | str,
    key: str,
    value: str,
) -> None:
    _sync_index_patchables()
    index_impl.write_agent_artifact_index_meta(index_path, key, value)


def invalidate_agent_artifact_index_source_reconcile(
    index_path: Path | str | None = None,
) -> None:
    _sync_index_patchables()
    index_impl.invalidate_agent_artifact_index_source_reconcile(index_path)


def agent_artifact_index_status(
    index_path: Path | str,
) -> AgentArtifactIndexStatusWire:
    _sync_index_patchables()
    return index_impl.agent_artifact_index_status(index_path)


def agent_artifact_index_status_bounded(
    index_path: Path | str,
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> AgentArtifactIndexStatusWire | None:
    _sync_index_patchables()
    return index_impl.agent_artifact_index_status_bounded(
        index_path, lock_timeout_seconds=lock_timeout_seconds
    )


def vacuum_agent_artifact_index(
    index_path: Path | str,
) -> AgentArtifactIndexVacuumWire:
    _sync_index_patchables()
    return index_impl.vacuum_agent_artifact_index(index_path)


def query_agent_output_variable_history(
    index_path: Path | str,
    query: AgentOutputVariableHistoryQueryWire | None = None,
) -> AgentOutputVariableHistoryWire:
    _sync_queries_patchables()
    return queries_impl.query_agent_output_variable_history(index_path, query)


def query_agent_alias_history(
    index_path: Path | str,
    query: AgentAliasHistoryQueryWire,
) -> AgentAliasHistoryWire:
    _sync_queries_patchables()
    return queries_impl.query_agent_alias_history(index_path, query)


def parse_output_variable_selector(selector: str) -> OutputVariableSelectorWire:
    _sync_source_patchables()
    return source_impl.parse_output_variable_selector(selector)


def query_agent_output_variable_selectors(
    index_path: Path | str,
    query: AgentOutputVariableSelectorQueryWire | None = None,
) -> AgentOutputVariableSelectorResultWire:
    _sync_queries_patchables()
    return queries_impl.query_agent_output_variable_selectors(index_path, query)


def query_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    query: AgentArtifactIndexQueryWire | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    _sync_queries_patchables()
    return queries_impl.query_agent_artifact_index(
        index_path, projects_root, query, options
    )


def query_agent_artifact_index_bounded(
    index_path: Path | str,
    projects_root: Path | str,
    query: AgentArtifactIndexQueryWire | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> AgentArtifactScanWire | None:
    _sync_queries_patchables()
    return queries_impl.query_agent_artifact_index_bounded(
        index_path,
        projects_root,
        query,
        options,
        lock_timeout_seconds=lock_timeout_seconds,
    )


def load_agent_artifact_records_bounded(
    index_path: Path | str,
    artifact_dirs: Sequence[Path | str],
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> list[AgentArtifactRecordWire] | None:
    _sync_queries_patchables()
    return queries_impl.load_agent_artifact_records_bounded(
        index_path, artifact_dirs, lock_timeout_seconds=lock_timeout_seconds
    )


def find_gate_turn_by_gate_id(
    index_path: Path | str,
    project_name: str | None,
    gate_id: str,
) -> AgentArtifactRecordWire | None:
    _sync_queries_patchables()
    return queries_impl.find_gate_turn_by_gate_id(index_path, project_name, gate_id)


def query_related_agent_artifact_dirs_bounded(
    index_path: Path | str,
    artifact_dir: Path | str,
    seed_timestamps: Sequence[str],
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> list[Path] | None:
    _sync_queries_patchables()
    return queries_impl.query_related_agent_artifact_dirs_bounded(
        index_path,
        artifact_dir,
        seed_timestamps,
        lock_timeout_seconds=lock_timeout_seconds,
    )


def verify_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexVerifyWire:
    _sync_queries_patchables()
    _sync_source_patchables()
    return queries_impl.verify_agent_artifact_index(index_path, projects_root, options)


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
    "agent_artifact_index_status_bounded",
    "default_agent_artifact_index_path",
    "delete_agent_artifact_index_row",
    "delete_agent_artifact_index_row_bounded",
    "find_gate_turn_by_gate_id",
    "invalidate_agent_artifact_index_source_reconcile",
    "load_agent_artifact_records_bounded",
    "parse_output_variable_selector",
    "prune_hidden_terminal_agent_artifact_index_rows",
    "query_agent_alias_history",
    "query_agent_artifact_index",
    "query_agent_artifact_index_bounded",
    "query_agent_output_variable_history",
    "query_agent_output_variable_selectors",
    "query_related_agent_artifact_dirs_bounded",
    "read_agent_artifact_index_meta",
    "rebuild_agent_artifact_index",
    "reconcile_agent_artifact_index_dismissed_agent_session_members",
    "replace_agent_artifact_index_dismissed_agents",
    "scan_agent_artifact_dirs",
    "scan_agent_artifacts",
    "terminalize_stale_active_agent_artifact_index_rows",
    "upsert_agent_artifact_index_row",
    "verify_agent_artifact_index",
    "write_agent_artifact_index_meta",
]
