"""Shared helpers for the ``⚒ Runs`` deck view split (epic sase-1bt).

This is the already-private (``_``-prefixed) module that owns helpers
needed by more than one of the new view-split modules. Every helper
here carries a public (non-``_``) name so the new modules can import it
without importing a ``_``-prefixed name across files.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.tool_runs.detail import (
    LoadedToolRunDetail,
    cached_tool_run_detail,
)


def tool_runs_render_width(view: Any) -> int:
    """Return the block render width for *view* (narrow-safe, never raises)."""

    try:
        width = int(view.size.width or 0)
    except Exception:
        width = 0
    return width if width > 0 else 100


def tool_runs_hint_numbers(view: Any) -> dict[str, int] | None:
    """Return mapped run-id → ``v`` hint numbers while hint mode is active.

    Single source of truth is the app's ``_hint_mappings``; the tail
    header shows a ``[N]`` marker only for targets mapped right now.
    Never raises.
    """

    try:
        app = view.app
    except Exception:
        return None
    try:
        if not bool(getattr(app, "_hint_mode_active", False)):
            return None
        mappings = getattr(app, "_hint_mappings", None)
    except Exception:
        return None
    if not mappings:
        return None
    try:
        from sase.ace.tui.tool_runs.hints import run_id_from_hint_target

        numbers: dict[str, int] = {}
        for number, target in dict(mappings).items():
            run_id = run_id_from_hint_target(target)
            if run_id and run_id not in numbers:
                numbers[run_id] = int(number)
    except Exception:
        return None
    return numbers or None


def cached_block_details(
    rows: tuple[Any, ...] | list[Any],
    store_token: Any | None,
) -> dict[str, LoadedToolRunDetail]:
    """Return LRU-cached details for *rows* (memory-only, never raises)."""

    details: dict[str, LoadedToolRunDetail] = {}
    for row in rows or ():
        run_id = str(getattr(row, "run_id", "") or "")
        if not run_id:
            continue
        try:
            hit = cached_tool_run_detail(run_id, row, store_token)
        except Exception:
            hit = None
        if hit is not None:
            details[run_id] = hit
    return details


def count_silent_rows(rows: Any, now_s: float) -> int:
    """Count silent live rows at *now_s* (never raises)."""

    from sase.ace.tui.tool_runs.deck import tool_run_is_silent

    silent = 0
    try:
        ordered = list(rows or ())
    except TypeError:
        return 0
    for row in ordered:
        try:
            if tool_run_is_silent(row, now_s):
                silent += 1
        except Exception:
            continue
    return silent


__all__ = [
    "cached_block_details",
    "count_silent_rows",
    "tool_runs_hint_numbers",
    "tool_runs_render_width",
]
