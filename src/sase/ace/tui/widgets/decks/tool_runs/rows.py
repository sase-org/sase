"""Row merging and cache signatures for the ``⚒ Runs`` deck (epic sase-1bt)."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.tool_runs.summaries import node_live_runs


def tool_runs_cache_signature(
    selector_key: str, total_runs: int, live_ids: tuple[str, ...], truncated: bool
) -> str:
    """Return the stat-only signature for one painted Runs document."""
    return f"{selector_key}:{total_runs}:{','.join(live_ids)}:{int(truncated)}"


def _tool_runs_detail_paint_token(details: Any | None) -> str:
    """Return a cheap content token for loaded block details.

    Availability and bounded content facts only: never Rich object
    identity, elapsed clocks, or renderable hashes.
    """
    if not details:
        return ""
    try:
        items = list(details.items())
    except Exception:
        return ""
    parts: list[str] = []
    for run_id, loaded in sorted(items, key=lambda item: str(item[0])):
        parts.append(_one_detail_paint_token(str(run_id), loaded))
    return ";".join(parts)


def _one_detail_paint_token(run_id: str, loaded: Any) -> str:
    live = int(bool(getattr(loaded, "live", False)))
    detail = getattr(loaded, "detail", None)
    found = int(bool(getattr(detail, "found", False)))
    pruned = int(bool(getattr(detail, "detail_pruned", False)))
    try:
        n_stages = len(getattr(detail, "stages", ()) or ())
    except Exception:
        n_stages = 0
    try:
        n_items = len(getattr(detail, "triage_items", ()) or ())
    except Exception:
        n_items = 0
    tail = getattr(loaded, "tail", None)
    try:
        n_tail = len(getattr(tail, "lines", ()) or ())
    except Exception:
        n_tail = 0
    last_stage = ""
    try:
        stages = tuple(getattr(detail, "stages", ()) or ())
        if stages:
            last_stage = str(getattr(stages[-1], "description", "") or "")
    except Exception:
        last_stage = ""
    return (
        f"{run_id}:{live}:{found}:{pruned}:{n_stages}:{n_items}:{n_tail}:{last_stage}"
    )


def _tool_runs_hint_token(hint_numbers: Any | None) -> str:
    """Return a stable token for mapped ``v`` hint numbers."""
    if not hint_numbers:
        return ""
    try:
        items = sorted(
            (str(run_id), int(number)) for run_id, number in hint_numbers.items()
        )
    except Exception:
        return ""
    return ",".join(f"{run_id}={number}" for run_id, number in items)


def tool_runs_render_digest(
    summary_signature: str,
    *,
    details: Any | None = None,
    level: int = 1,
    width: int = 100,
    hint_numbers: Any | None = None,
    store_token: Any | None = None,
) -> str:
    """Return the painted-content identity for one Runs document.

    Summary freshness stays in ``summary_signature``. This digest adds
    every input that changes the visible body: loaded detail
    availability/content, the view's detail level, render width, hint
    numbers, and the glance store token.
    """
    try:
        level_i = int(level)
    except (TypeError, ValueError):
        level_i = 1
    try:
        width_i = int(width)
    except (TypeError, ValueError):
        width_i = 100
    token = "" if store_token is None else str(store_token)
    return (
        f"{summary_signature}"
        f":d={_tool_runs_detail_paint_token(details)}"
        f":lv={level_i}"
        f":w={width_i}"
        f":h={_tool_runs_hint_token(hint_numbers)}"
        f":st={token}"
    )


def tool_runs_rows_for_document(
    summary: Any, snapshot_runs: tuple[Any, ...] | list[Any] | None
) -> tuple[tuple[Any, ...], int, bool]:
    """Return ``(rows, total_runs, truncated)`` for one node summary.

    Merges the summary's settled history with the glance snapshot's
    live rows for the same selector, deduped by ``run_id`` and ordered
    oldest first so the cursor lands on the newest block.
    """
    history = list(getattr(summary, "runs", ()) or ())
    live_rows = list(getattr(summary, "live", ()) or ())
    if snapshot_runs:
        try:
            from sase.ace.tui.tool_runs.summaries import ToolRunSelector

            selector = ToolRunSelector(key=str(getattr(summary, "key", "") or ""))
            scoped = node_live_runs(tuple(snapshot_runs), selector)
        except Exception:
            scoped = ()
        seen_live = {str(getattr(run, "run_id", "")) for run in live_rows}
        for run in scoped:
            run_id = str(getattr(run, "run_id", "") or "")
            if run_id and run_id not in seen_live:
                live_rows.append(run)
                seen_live.add(run_id)
    seen: set[str] = set()
    merged: list[Any] = []
    for row in (*history, *live_rows):
        run_id = str(getattr(row, "run_id", "") or "")
        if not run_id or run_id in seen:
            continue
        seen.add(run_id)
        merged.append(row)
    try:
        merged.sort(key=lambda row: int(getattr(row, "created_ts", 0) or 0))
    except Exception:
        pass
    try:
        total = max(int(getattr(summary, "total_runs", 0) or 0), len(merged))
    except (TypeError, ValueError):
        total = len(merged)
    try:
        truncated = bool(getattr(summary, "truncated", False))
    except Exception:
        truncated = False
    return (tuple(merged), total, truncated)


__all__ = [
    "tool_runs_cache_signature",
    "tool_runs_render_digest",
    "tool_runs_rows_for_document",
]
