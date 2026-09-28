"""Off-thread ``⚒ Runs`` deck loader (epic sase-1bt)."""

from __future__ import annotations

import logging
import time
from typing import Any

from sase.ace.tui.tool_runs.deck import (
    DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    ToolRunsDetailLevel,
    tool_run_display_bucket,
)
from sase.ace.tui.tool_runs.detail import (
    LoadedToolRunDetail,
    load_tool_run_detail_blocking,
)
from sase.ace.tui.tool_runs.summaries import (
    resolve_tool_run_summary,
    selector_for_agent,
)

from ._shared import count_silent_rows
from .document import build_tool_runs_document
from .messages import ToolRunsDeckLoadResult
from .rows import tool_runs_cache_signature, tool_runs_rows_for_document

log = logging.getLogger(__name__)


def _load_block_details(
    rows: tuple[Any, ...] | list[Any],
    store_token: Any | None,
    *,
    is_current: Any | None = None,
) -> dict[str, LoadedToolRunDetail]:
    """Load every row's detail plus tail on a worker thread (never raises).

    Settled hits never re-read; live rows refetch only when the store
    token drifted (their LRU key carries the token). ``is_current``
    rejects the whole batch when the subject moved on mid-load.
    """

    details: dict[str, LoadedToolRunDetail] = {}
    for row in rows or ():
        run_id = str(getattr(row, "run_id", "") or "")
        if not run_id:
            continue
        try:
            loaded = load_tool_run_detail_blocking(
                run_id, row, store_token, is_current=is_current
            )
        except Exception:
            loaded = None
        if loaded is None:
            if is_current is not None:
                try:
                    if not is_current():
                        return details
                except Exception:
                    return details
            continue
        details[run_id] = loaded
    return details


def _empty_tool_runs_result(
    *,
    subject: object | None,
    subject_identity: object | None,
    generation: int,
    selector_key: str = "",
) -> ToolRunsDeckLoadResult:
    """Return an empty (no runs) load result for one subject."""
    signature = tool_runs_cache_signature(selector_key, 0, (), False)
    return ToolRunsDeckLoadResult(
        subject_identity=subject_identity,
        generation=generation,
        signature=signature,
        document=build_tool_runs_document((), subject=subject, digest=signature),
        runs=(),
        total_runs=0,
        truncated=False,
        live_count=0,
        silent_count=0,
    )


def load_tool_runs_deck(
    agent: Any,
    *,
    subject: object | None,
    subject_identity: object | None,
    generation: int,
    level: ToolRunsDetailLevel | int = DEFAULT_TOOL_RUNS_DETAIL_LEVEL,
    width: int = 100,
    hint_numbers: dict[str, int] | None = None,
) -> ToolRunsDeckLoadResult:
    """Load one ``⚒ Runs`` document on a worker thread; never raise.

    The same worker call loads each visible block's detail plus its
    bounded log tail through the detail LRU (§3.5.3).
    """
    try:
        selector = selector_for_agent(agent)
        selector_key = selector.key if selector is not None else ""
    except Exception:
        selector_key = ""
    try:
        summary = resolve_tool_run_summary(agent)
    except Exception as exc:
        log.debug("ToolRuns deck load failed, keeping last state: %s", exc)
        summary = None
    if summary is None:
        return _empty_tool_runs_result(
            subject=subject,
            subject_identity=subject_identity,
            generation=generation,
            selector_key=selector_key,
        )
    try:
        from sase.ace.tui.tool_runs.snapshot import get_snapshot

        snapshot = get_snapshot()
        snapshot_runs = tuple(snapshot.runs or ()) if snapshot else ()
    except Exception:
        snapshot_runs = ()
    rows, total, truncated = tool_runs_rows_for_document(summary, snapshot_runs)
    live_ids = tuple(
        str(getattr(row, "run_id", ""))
        for row in rows
        if tool_run_display_bucket(row) == "running"
    )
    try:
        selector = selector_for_agent(agent)
        selector_key = selector.key if selector is not None else ""
    except Exception:
        selector_key = ""
    signature = tool_runs_cache_signature(selector_key, total, live_ids, truncated)
    now_s = time.time()
    try:
        store_token = snapshot.store_token if snapshot else None
    except Exception:
        store_token = None
    details = _load_block_details(rows, store_token)
    try:
        render_width = max(20, int(width))
    except (TypeError, ValueError):
        render_width = 100
    return ToolRunsDeckLoadResult(
        subject_identity=subject_identity,
        generation=generation,
        signature=signature,
        document=build_tool_runs_document(
            rows,
            subject=subject,
            digest=signature,
            total_runs=total,
            truncated=truncated,
            details=details,
            level=level,
            width=render_width,
            now_s=now_s,
            hint_numbers=hint_numbers,
        ),
        runs=rows,
        total_runs=total,
        truncated=truncated,
        live_count=len(live_ids),
        silent_count=count_silent_rows(rows, now_s),
    )


__all__ = ["load_tool_runs_deck"]
