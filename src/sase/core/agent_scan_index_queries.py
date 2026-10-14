"""Reads against the persistent agent artifact index.

These entry points query history, selectors, rows, and related
directories through ``sase_core_rs`` under the artifact index operation
lock, plus the read-only
:func:`verify_agent_artifact_index` comparison between the index and a
fresh filesystem scan. Index writes live in
:mod:`sase.core.agent_scan_index_mutations`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core._agent_scan_shared import DEFAULT_READ_LOCK_TIMEOUT_SECONDS
from sase.core._agent_scan_shared import options_to_dict
from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_artifact_index_lock import try_agent_artifact_index_operation_lock
from sase.core.agent_alias_history_wire import AgentAliasHistoryQueryWire
from sase.core.agent_alias_history_wire import AgentAliasHistoryWire
from sase.core.agent_alias_history_wire import agent_alias_history_from_dict
from sase.core.agent_alias_history_wire import agent_alias_history_query_to_dict
from sase.core.agent_output_variable_history_wire import (
    AgentOutputVariableHistoryQueryWire,
)
from sase.core.agent_output_variable_history_wire import AgentOutputVariableHistoryWire
from sase.core.agent_output_variable_history_wire import (
    agent_output_variable_history_from_dict,
)
from sase.core.agent_output_variable_history_wire import (
    agent_output_variable_history_query_to_dict,
)
from sase.core.agent_output_variable_selector_wire import (
    AgentOutputVariableSelectorQueryWire,
)
from sase.core.agent_output_variable_selector_wire import (
    AgentOutputVariableSelectorResultWire,
)
from sase.core.agent_output_variable_selector_wire import (
    agent_output_variable_selector_query_to_dict,
)
from sase.core.agent_output_variable_selector_wire import (
    agent_output_variable_selector_result_from_dict,
)
from sase.core.agent_scan_source import scan_agent_artifacts
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION
from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire
from sase.core.agent_scan_wire import AgentArtifactIndexVerifyWire
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.core.agent_scan_wire import agent_artifact_index_query_to_dict
from sase.core.agent_scan_wire import agent_artifact_records_from_dicts
from sase.core.agent_scan_wire import agent_scan_wire_from_dict
from sase.core.agent_scan_wire import agent_scan_wire_to_json_dict
from sase.core.rust import require_rust_binding


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
            options_to_dict(opts),
        )
    return agent_scan_wire_from_dict(payload)


def query_agent_artifact_index_bounded(
    index_path: Path | str,
    projects_root: Path | str,
    query: AgentArtifactIndexQueryWire | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> AgentArtifactScanWire | None:
    """Query index rows, or ``None`` when the process-local lock is busy."""
    opts = options or AgentArtifactScanOptionsWire()
    query_wire = query or AgentArtifactIndexQueryWire()
    with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
        if not acquired:
            return None
        rust_query = require_rust_binding("query_agent_artifact_index")
        payload: dict[str, Any] = rust_query(
            str(index_path),
            str(projects_root),
            agent_artifact_index_query_to_dict(query_wire),
            options_to_dict(opts),
        )
    return agent_scan_wire_from_dict(payload)


def load_agent_artifact_records_bounded(
    index_path: Path | str,
    artifact_dirs: Sequence[Path | str],
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> list[AgentArtifactRecordWire] | None:
    """Load exact index records, or ``None`` when the local lock is busy."""
    index = Path(index_path).expanduser()
    dirs = [str(Path(path).expanduser()) for path in artifact_dirs]
    if not dirs:
        return []
    with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
        if not acquired:
            return None
        rust_load = require_rust_binding("load_agent_artifact_records")
        payload: list[dict[str, Any]] = rust_load(str(index), dirs)
    return agent_artifact_records_from_dicts(payload)


def find_gate_turn_by_gate_id(
    index_path: Path | str,
    project_name: str | None,
    gate_id: str,
) -> AgentArtifactRecordWire | None:
    """Return the newest real gate-turn record for *gate_id*, or ``None``.

    Uses the persistent index's indexed ``gate_turn_id`` column for an
    O(1) SQL lookup instead of decoding every historical record. A ``None``
    project searches every project. A clean ``None`` result is authoritative
    (no matching gate-turn member exists); callers whose index is missing
    or unusable see an exception instead, so they can distinguish "not
    found" from "could not look up" and fall back accordingly.
    """
    with agent_artifact_index_operation_lock():
        try:
            rust_find = require_rust_binding("find_gate_turn_by_gate_id")
        except (ImportError, AttributeError):
            # legacy sase-shell spelling: pre-cutover core builds expose
            # only the old binding name.
            rust_find = require_rust_binding("find_gate_shell_by_gate_id")
        payload: dict[str, Any] | None = rust_find(
            str(index_path), project_name, str(gate_id)
        )
    if payload is None:
        return None
    return agent_artifact_records_from_dicts([payload])[0]


def query_related_agent_artifact_dirs_bounded(
    index_path: Path | str,
    artifact_dir: Path | str,
    seed_timestamps: Sequence[str],
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> list[Path] | None:
    """Return related artifact dirs, or ``None`` when the local lock is busy."""
    index = Path(index_path).expanduser()
    artifact = Path(artifact_dir).expanduser()
    seeds = [str(value) for value in seed_timestamps if value]
    with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
        if not acquired:
            return None
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
    "find_gate_turn_by_gate_id",
    "load_agent_artifact_records_bounded",
    "query_agent_alias_history",
    "query_agent_artifact_index",
    "query_agent_artifact_index_bounded",
    "query_agent_output_variable_history",
    "query_agent_output_variable_selectors",
    "query_related_agent_artifact_dirs_bounded",
    "verify_agent_artifact_index",
]
