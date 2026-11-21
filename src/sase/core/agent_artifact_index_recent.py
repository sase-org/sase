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
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sase.core.agent_scan_facade import query_agent_artifact_index_payload
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)

#: Predicate over one raw index record dict (the PyO3 payload shape).
RawRecordFilter = Callable[[Mapping[str, Any]], bool]

#: First page size. One page covers a typical week of completed rows.
DEFAULT_RECENT_COMPLETED_PAGE = 512


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
    "RawRecordFilter",
    "query_index_payload_records",
    "query_recently_completed_payload_records",
]
