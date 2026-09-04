"""Shared agent-artifact index access for incremental chop scans.

Both wait_checks and bead_claim_checks prefer the persistent artifact index
when it exists and answers the query. Missing, unreadable, or unexpected
index state fails open to the caller's filesystem path.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)

_FULL_WALK_ENV = "SASE_CHOP_SCAN_FULL_WALK"

_ACE_RUN_INDEX_OPTIONS = AgentArtifactScanOptionsWire(
    only_workflow_dirs=("ace-run",),
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    include_done_markers=True,
    include_workflow_state=True,
    include_waiting=True,
)

_FULL_HISTORY_QUERY = AgentArtifactIndexQueryWire(
    include_active=True,
    include_recent_completed=True,
    include_full_history=True,
    active_limit=None,
    recent_completed_limit=None,
    include_hidden=True,
    freshness="cached",
)


def chop_scan_full_walk(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether chops should use the legacy full filesystem walk."""

    env = os.environ if environ is None else environ
    value = env.get(_FULL_WALK_ENV)
    return bool(value and value.strip().lower() not in {"0", "false", "no", "off"})


def query_ace_run_index_records(
    projects_root: Path,
    *,
    index_path: Path | None = None,
) -> list[AgentArtifactRecordWire] | None:
    """Return ace-run index records, or ``None`` when the index cannot be used."""

    path = default_agent_artifact_index_path() if index_path is None else index_path
    if not path.is_file():
        return None
    try:
        snapshot = query_agent_artifact_index(
            path,
            projects_root,
            _FULL_HISTORY_QUERY,
            options=_ACE_RUN_INDEX_OPTIONS,
        )
    except Exception:  # noqa: BLE001 - fail open to the filesystem scan.
        return None
    return [
        record for record in snapshot.records if record.workflow_dir_name == "ace-run"
    ]


def _agent_meta_mapping(record: AgentArtifactRecordWire) -> dict[str, Any] | None:
    """Project one index record's agent meta into a wait-index mapping."""

    if record.agent_meta is None:
        return None
    return asdict(record.agent_meta)


def wait_rows_from_index_records(
    records: list[AgentArtifactRecordWire],
) -> list[tuple[Path, dict[str, Any], str]]:
    """Convert ace-run index records into ``WaitDependencyIndex.add_many`` rows."""

    rows: list[tuple[Path, dict[str, Any], str]] = []
    for record in records:
        meta = _agent_meta_mapping(record)
        if meta is None:
            continue
        rows.append((Path(record.artifact_dir), meta, record.project_name))
    return rows
