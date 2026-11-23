"""Query the Archive corpus handle for requested rows and summaries."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ...models.agent_archive_controller import (
    ArchiveLoadedWindow,
    ArchiveRequestSnapshot,
)
from ...models.agent_archive_list import archive_row_key

log = logging.getLogger(__name__)


def row_identity(row: Mapping[str, Any]) -> str | None:
    """Return the stable Archive identity for one core light row."""
    return archive_row_key(row)


def _match_query(query: str) -> str | None:
    """Strip the host ``in:`` scope token: it selects the view, not rows.

    The core corpus only knows row fields, so the scope must be extracted
    before every summary, rows, and count call (the CLI does the same).
    """
    from sase.ace.query.profile_reference_support import ProfileQueryError
    from sase.ace.query.scope_token import ScopeTokenError, extract_scope

    try:
        remainder, _scope = extract_scope(query)
    except (ScopeTokenError, ProfileQueryError, ValueError):
        log.debug("archive query scope rejected: %r", query, exc_info=True)
        return None
    return remainder


def query_handle(
    corpus: Any,
    profile: Any,
    snapshot: ArchiveRequestSnapshot,
    *,
    telemetry: dict[str, Any] | None = None,
) -> tuple[
    Mapping[str, Any] | None,
    tuple[ArchiveLoadedWindow, ...],
    tuple[str, ...],
    int,
]:
    if corpus is None:
        return None, (), (), 0
    query = _match_query(snapshot.query)
    if query is None:
        return None, (), (), 0
    summary: Mapping[str, Any] | None = None
    if telemetry is not None:
        telemetry["corpus_summary_query_count"] = 1
    try:
        summary = corpus.summary(query, group_by=snapshot.grouping, profile=profile)
    except Exception:
        log.debug("archive corpus summary failed", exc_info=True)
        summary = None
    windows: list[ArchiveLoadedWindow] = []
    identities: list[str] = []
    for window in snapshot.windows:
        if telemetry is not None:
            telemetry["corpus_window_query_count"] += 1
        try:
            payload = corpus.rows(
                query,
                group_by=snapshot.grouping,
                group_key=window.group_key,
                offset=window.offset,
                limit=window.limit,
                expanded_container_keys=snapshot.expanded_containers,
                profile=profile,
            )
        except Exception:
            log.debug("archive corpus rows failed", exc_info=True)
            continue
        rows = tuple(
            dict(row) for row in payload.get("rows", ()) if isinstance(row, Mapping)
        )
        windows.append(
            ArchiveLoadedWindow(
                group_key=window.group_key,
                offset=window.offset,
                limit=window.limit,
                rows=rows,
                total=int(payload.get("total", len(rows)) or 0),
            )
        )
        for row in rows:
            identity = row_identity(row)
            if identity is not None:
                identities.append(identity)
    count = 0
    if telemetry is not None:
        telemetry["corpus_count_query_count"] = 1
    try:
        count = int(corpus.count(query, profile=profile))
    except Exception:
        if isinstance(summary, Mapping):
            count = int(summary.get("total", 0) or 0)
    return summary, tuple(windows), tuple(identities), count


__all__ = ["query_handle", "row_identity"]
