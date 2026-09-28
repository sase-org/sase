"""Live-block tick predicates for the ``⚒ Runs`` card (epic sase-1bt).

``runs-card-live`` reuses FINAL's live gate (``decks/final/live.py``): a
pure 1 Hz repaint updates elapsed and bar growth from the cached detail
plus ``now`` — no stat, no SQLite open, no log read — while the card is
visible and its run is live. Detail is re-fetched only when the glance
store token drifts. Everything here is pure except the visibility and
gate reads, which never touch the ToolRun store.
"""

from __future__ import annotations

from typing import Any

#: The live repaint cadence in seconds: elapsed counters plus bar growth.
TOOL_RUNS_LIVE_TICK_SECONDS = 1.0


def tool_runs_rows_have_live(rows: Any) -> bool:
    """Return whether any row in *rows* is a live run (never raises)."""

    try:
        ordered = list(rows or ())
    except TypeError:
        return False
    from sase.ace.tui.tool_runs.deck import tool_run_display_bucket

    for row in ordered:
        try:
            if tool_run_display_bucket(row) == "running":
                return True
        except Exception:
            continue
    return False


def want_live_tick(
    *,
    visible: bool,
    has_live: bool,
    navigating: bool,
    typing: bool,
    in_flight: bool,
) -> bool:
    """Return whether the 1 Hz repaint may run (FINAL's live gate).

    The tick runs only while the Runs card is visible and holds a live
    run. It stands down while the user navigates or types and while a
    worker reload is still in flight (coalesced: the next tick retries).
    Side-effect free so the timer callback and tests share it.
    """

    if in_flight or typing or navigating:
        return False
    return bool(visible and has_live)


def live_host_visible(view: Any) -> bool:
    """Return whether a panel currently shows *view* (no I/O)."""

    try:
        from textual.containers import VerticalScroll

        node: Any = view.parent
        while node is not None:
            if isinstance(node, VerticalScroll):
                try:
                    if not node.has_class("-shown"):
                        return False
                except Exception:
                    return False
                try:
                    if not node.display:
                        return False
                except Exception:
                    pass
                return True
            node = getattr(node, "parent", None)
    except Exception:
        pass
    return False


def live_navigating(view: Any) -> bool:
    """Return whether the user is mid-navigation (250 ms gate)."""

    try:
        gate = getattr(getattr(view, "app", None), "_nav_gate", None)
        if gate is None:
            return False
        return bool(gate.is_navigating())
    except Exception:
        return False


def live_typing(view: Any) -> bool:
    """Return whether the user is typing in the prompt input."""

    try:
        active = getattr(getattr(view, "app", None), "_prompt_input_active", None)
        if callable(active):
            return bool(active())
    except Exception:
        pass
    return False


def live_detail_drifted(snapshot_token: Any, painted_token: Any) -> bool:
    """Return whether live details must be re-fetched (never raises).

    True only when a glance snapshot token exists and differs from the
    token the painted details were loaded under. A missing snapshot
    token means the tick keeps purely repainting: it never schedules a
    reload storm while the store is missing.
    """

    if snapshot_token is None:
        return False
    if painted_token is None:
        return True
    try:
        from sase.ace.tui.actions.event_refresh._surface_tokens import (
            surface_token_drifted,
        )

        return bool(surface_token_drifted(snapshot_token, painted_token))
    except Exception:
        return False


__all__ = [
    "TOOL_RUNS_LIVE_TICK_SECONDS",
    "live_detail_drifted",
    "live_host_visible",
    "live_navigating",
    "live_typing",
    "tool_runs_rows_have_live",
    "want_live_tick",
]
