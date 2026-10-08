"""Shared agent-artifact index access for incremental chop scans.

bead_claim_checks prefers the persistent artifact index when it exists and
answers the query. Missing, unreadable, or unexpected index state fails open
to the caller's filesystem path. wait_checks resolves from filesystem rows
instead (see :mod:`sase.scripts._chop_wait_checks_run`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

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
