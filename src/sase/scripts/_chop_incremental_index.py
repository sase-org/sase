"""Shared agent-artifact index access for incremental chop scans.

bead_claim_checks prefers the persistent artifact index when it exists and
answers the query. Missing, unreadable, or unexpected index state fails open
to the caller's filesystem path. wait_checks resolves from filesystem rows
instead (see :mod:`sase.scripts._chop_wait_checks_run`).

Both claim reads return raw index record dicts for claim-bearing rows only
(``ace-run`` rows whose ``agent_meta`` names an agent and a bead), so the
caller can drop more rows before paying to rehydrate them.
:func:`query_claim_window_payloads` is the bounded per-tick read: the
normally visible active tier plus every completed row, hidden and dismissed
included, that finished inside :data:`CLAIM_RECENT_WINDOW_SECONDS`.
:func:`query_claim_history_payloads` is the full-history read the claim
pre-pass widens to on its periodic sweep.

``SASE_CHOP_SCAN_FULL_WALK=1`` also sends ``bead_task_triage``'s
live-agent read back to the full walk.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_artifact_index_recent import (
    query_index_payload_records,
    query_recently_completed_payload_records,
)
from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
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

#: Completed rows stay in every bounded claim read for this long after they
#: finish. A dead claim owner is reconciled on the first tick that reads its
#: project, and the hourly full-history sweep covers anything older, so a day
#: leaves a wide margin for bead-store outages.
CLAIM_RECENT_WINDOW_SECONDS = 24 * 3600

#: First completed-tier page for the claim window; about a day of rows.
_CLAIM_RECENT_FIRST_PAGE = 256

# Hidden rows (``%hide``, auto-dismiss) and TUI-dismissed rows are left out:
# with ``include_hidden=True`` the active tier also returns every dismissed
# row that never wrote a done marker, thousands on a long-lived host.
_VISIBLE_ACTIVE_QUERY = AgentArtifactIndexQueryWire(
    include_active=True,
    include_recent_completed=False,
    include_full_history=False,
    active_limit=None,
    recent_completed_limit=0,
    include_hidden=False,
    freshness="cached",
)


def chop_scan_full_walk(environ: Mapping[str, str] | None = None) -> bool:
    """Return whether chops should use the legacy full filesystem walk."""

    env = os.environ if environ is None else environ
    value = env.get(_FULL_WALK_ENV)
    return bool(value and value.strip().lower() not in {"0", "false", "no", "off"})


def query_claim_history_payloads(
    projects_root: Path,
    *,
    index_path: Path | None = None,
) -> list[Mapping[str, Any]] | None:
    """Return every claim-bearing raw index row, or ``None`` when the index cannot be used."""

    path = default_agent_artifact_index_path() if index_path is None else index_path
    if not path.is_file():
        return None
    try:
        return query_index_payload_records(
            path,
            projects_root,
            _FULL_HISTORY_QUERY,
            keep=_is_claim_bearing_payload,
            options=_ACE_RUN_INDEX_OPTIONS,
        )
    except Exception:  # noqa: BLE001 - fail open to the filesystem scan.
        return None


def query_claim_window_payloads(
    projects_root: Path,
    *,
    now: float | None = None,
    index_path: Path | None = None,
) -> list[Mapping[str, Any]] | None:
    """Return the bounded claim read, or ``None`` when the index cannot be used.

    The read is the visible active tier plus completed rows that finished
    within :data:`CLAIM_RECENT_WINDOW_SECONDS`, hidden and dismissed rows
    included. Active hidden or dismissed rows and older completed rows are
    only seen by :func:`query_claim_history_payloads`.
    """

    path = default_agent_artifact_index_path() if index_path is None else index_path
    if not path.is_file():
        return None
    at = time.time() if now is None else now
    try:
        active = query_index_payload_records(
            path,
            projects_root,
            _VISIBLE_ACTIVE_QUERY,
            keep=_is_claim_bearing_payload,
            options=_ACE_RUN_INDEX_OPTIONS,
        )
        completed = query_recently_completed_payload_records(
            path,
            projects_root,
            finished_after=at - CLAIM_RECENT_WINDOW_SECONDS,
            keep=_is_claim_bearing_payload,
            options=_ACE_RUN_INDEX_OPTIONS,
            include_hidden=True,
            first_page=_CLAIM_RECENT_FIRST_PAGE,
        )
    except Exception:  # noqa: BLE001 - fail open to the filesystem scan.
        return None
    by_dir: dict[str, Mapping[str, Any]] = {}
    for record in [*active, *completed]:
        by_dir.setdefault(str(record.get("artifact_dir")), record)
    return list(by_dir.values())


def _is_claim_bearing_payload(record: Mapping[str, Any]) -> bool:
    """Mirror ``claim_artifact_from_record``'s row test on a raw record dict."""

    if record.get("workflow_dir_name") != "ace-run":
        return False
    meta = record.get("agent_meta")
    return (
        isinstance(meta, Mapping)
        and bool(meta.get("name"))
        and bool(meta.get("bead_id"))
    )
