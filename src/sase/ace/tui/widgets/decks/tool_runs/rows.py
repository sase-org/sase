"""Row merging and cache signatures for the ``⚒ Runs`` deck (epic sase-1bt)."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.tool_runs.summaries import node_live_runs


def tool_runs_cache_signature(
    selector_key: str, total_runs: int, live_ids: tuple[str, ...], truncated: bool
) -> str:
    """Return the stat-only signature for one painted Runs document."""
    return f"{selector_key}:{total_runs}:{','.join(live_ids)}:{int(truncated)}"


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
    "tool_runs_rows_for_document",
]
