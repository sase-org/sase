"""Bounded, filter-first reads of the persistent agent artifact index.

Background jobs that only care about a few kinds of rows used to ask the index
for full history (or walk every artifact directory), rehydrate every record
into wire dataclasses, and then discard almost all of them. Rehydration costs
about as much CPU as the Rust query itself, so these helpers return the raw
record dicts a caller predicate keeps; callers rehydrate only what they still
need with :func:`sase.core.agent_scan_wire.agent_artifact_records_from_dicts`.

:func:`query_recently_completed_payload_records` also bounds the read in time.
It pages the index's completed tier, which sase-core orders by ``finished_at``
newest first, and stops as soon as a page reaches a row that finished before
the caller's floor. The result is every completed row that finished at or
after the floor. Rows whose done marker has no ``finished_at`` sort by
``agent_meta.stopped_at`` or last in sase-core, so they never decide where
paging stops; they are kept whenever a fetched page contains them.

:func:`load_ace_run_index_listing` answers "which ``ace-run`` directories
exist, and which hold ``waiting.json``" from scalar index columns alone, with
no record JSON decode, so a caller can stop walking every artifact directory.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.agent_scan_facade import (
    load_agent_artifact_index_projection,
    query_agent_artifact_index_payload,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)

#: Predicate over one raw index record dict (the PyO3 payload shape).
RawRecordFilter = Callable[[Mapping[str, Any]], bool]

#: First page size. One page covers a typical week of completed rows.
DEFAULT_RECENT_COMPLETED_PAGE = 512

#: Scalar ``agent_artifacts`` columns the ace-run listing reads.
_ACE_RUN_LISTING_COLUMNS = ("artifact_dir", "workflow_dir_name", "has_waiting_marker")
_ARTIFACTS_SEGMENT = f"artifacts{os.sep}"


@dataclass(frozen=True)
class AceRunIndexListing:
    """Every indexed ``ace-run`` artifact directory under one projects root.

    Both maps are keyed by project directory name, taken from the artifact
    path rather than the row's project column. Directories are in sorted
    path order, which is the filesystem walk's listing order for both the
    legacy and the day-sharded layouts.
    """

    dirs_by_project: dict[str, list[str]]
    waiting_dirs_by_project: dict[str, list[str]]


def load_ace_run_index_listing(
    index_path: Path | str,
    projects_root: Path | str,
) -> AceRunIndexListing:
    """List indexed ``ace-run`` dirs under *projects_root* and their waiters.

    Reads only scalar columns (no record JSON decode). Rows stored under a
    different projects root are ignored. ``has_waiting_marker`` is the index's
    copy of the ``waiting.json`` marker, so callers must still read the
    marker itself before acting on it. Errors propagate so the caller can
    fail open to its filesystem walk.
    """

    prefix = os.path.join(str(projects_root), "")
    payload = load_agent_artifact_index_projection(index_path, _ACE_RUN_LISTING_COLUMNS)
    dirs_by_project: dict[str, list[str]] = {}
    waiting_dirs_by_project: dict[str, list[str]] = {}
    for row in payload.get("rows") or ():
        artifact_dir, workflow_dir_name, has_waiting_marker = row
        if workflow_dir_name != "ace-run" or not isinstance(artifact_dir, str):
            continue
        if not artifact_dir.startswith(prefix):
            continue
        project_name, sep, rest = artifact_dir[len(prefix) :].partition(os.sep)
        if not sep or not project_name or not rest.startswith(_ARTIFACTS_SEGMENT):
            continue
        dirs_by_project.setdefault(project_name, []).append(artifact_dir)
        if has_waiting_marker:
            waiting_dirs_by_project.setdefault(project_name, []).append(artifact_dir)
    for dirs in (*dirs_by_project.values(), *waiting_dirs_by_project.values()):
        dirs.sort()
    return AceRunIndexListing(
        dirs_by_project=dirs_by_project,
        waiting_dirs_by_project=waiting_dirs_by_project,
    )


def query_index_payload_records(
    index_path: Path | str,
    projects_root: Path | str,
    query: AgentArtifactIndexQueryWire,
    *,
    keep: RawRecordFilter | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
) -> list[Mapping[str, Any]]:
    """Run one index query and return the raw records *keep* accepts.

    Query errors propagate so the caller can fail open to its own fallback.
    """

    payload = query_agent_artifact_index_payload(
        index_path, projects_root, query, options
    )
    return _kept_records(_raw_records(payload), keep)


def query_recently_completed_payload_records(
    index_path: Path | str,
    projects_root: Path | str,
    *,
    finished_after: float,
    keep: RawRecordFilter | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
    include_hidden: bool = True,
    first_page: int = DEFAULT_RECENT_COMPLETED_PAGE,
) -> list[Mapping[str, Any]]:
    """Return raw completed index rows that finished at or after *finished_after*.

    Only rows *keep* accepts are returned; paging always looks at every
    fetched row. ``options`` must keep done markers (the default) so each
    row's ``done.finished_at`` can end the paging. Query errors propagate so
    the caller can fail open to its own fallback.
    """

    limit = max(1, first_page)
    while True:
        payload = query_agent_artifact_index_payload(
            index_path,
            projects_root,
            _recently_completed_index_query(limit, include_hidden=include_hidden),
            options,
        )
        raw = _raw_records(payload)
        if _rows_fetched(payload, raw) < limit or any(
            _finished_before(record, finished_after) for record in raw
        ):
            in_window = [
                record for record in raw if not _finished_before(record, finished_after)
            ]
            return _kept_records(in_window, keep)
        limit *= 2


def _recently_completed_index_query(
    limit: int, *, include_hidden: bool
) -> AgentArtifactIndexQueryWire:
    return AgentArtifactIndexQueryWire(
        include_active=False,
        include_recent_completed=True,
        include_full_history=False,
        active_limit=None,
        recent_completed_limit=limit,
        include_hidden=include_hidden,
        freshness="cached",
    )


def _raw_records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        record for record in payload.get("records") or [] if isinstance(record, Mapping)
    ]


def _kept_records(
    raw: list[Mapping[str, Any]], keep: RawRecordFilter | None
) -> list[Mapping[str, Any]]:
    return raw if keep is None else [record for record in raw if keep(record)]


def _rows_fetched(payload: Mapping[str, Any], raw: list[Mapping[str, Any]]) -> int:
    """Rows the SQL page returned, before sase-core's post-decode filters."""

    stats = payload.get("stats")
    fetched = 0
    if isinstance(stats, Mapping):
        for key in ("record_json_decoded", "json_decode_errors"):
            value = stats.get(key)
            if isinstance(value, int):
                fetched += value
    return max(fetched, len(raw))


def _finished_before(record: Mapping[str, Any], floor: float) -> bool:
    """Return whether the row's done marker says it finished before *floor*."""

    done = record.get("done")
    finished = done.get("finished_at") if isinstance(done, Mapping) else None
    return (
        isinstance(finished, (int, float))
        and not isinstance(finished, bool)
        and finished < floor
    )


__all__ = [
    "DEFAULT_RECENT_COMPLETED_PAGE",
    "AceRunIndexListing",
    "RawRecordFilter",
    "load_ace_run_index_listing",
    "query_index_payload_records",
    "query_recently_completed_payload_records",
]
