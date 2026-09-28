"""Agent-scoped wiring for run-links (no I/O)."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text

from sase.ace.tui.tool_runs.links_matching import (
    match_llm_calls_to_runs,
    pick_context_run,
    slow_suffixes_for_entries,
)
from sase.ace.tui.tool_runs.links_suffixes import context_tool_run_line

__all__ = [
    "context_row_for_agent",
    "context_row_for_agent_cached",
    "node_runs_for_agent",
    "run_links_for_agent_entries",
    "slow_suffixes_for_agent_sources",
]


def context_row_for_agent(
    agent: object,
    summary: Any | None,
    *,
    snapshot_runs: Any = (),
    snapshot_silent_after_s: int = 60,
    now_ts: float | None = None,
) -> Text | None:
    """Return the Context card ``Tool run`` value for *agent*, or None.

    Pure: settled facts come from the ``tool-runs`` lane, live facts
    overlay from the glance snapshot, and remote/clan rows never carry
    a row (D15). Returns None when the node has no selector or no runs.
    """

    if getattr(agent, "fleet_origin_alias", None):
        return None
    if bool(getattr(agent, "is_clan_container", False)):
        return None
    try:
        from sase.ace.tui.tool_runs.summaries import (
            node_live_runs as _overlay,
        )
        from sase.ace.tui.tool_runs.summaries import selector_for_agent
    except Exception:
        return None
    try:
        selector = selector_for_agent(agent)
    except Exception:
        return None
    if selector is None:
        return None
    now = float(now_ts) if now_ts is not None else time.time()
    try:
        live = _overlay(tuple(snapshot_runs or ()), selector)
    except Exception:
        live = ()
    settled: tuple[Any, ...] = ()
    if summary is not None:
        try:
            settled = tuple(getattr(summary, "latest_by_tool", ()) or ()) or tuple(
                getattr(summary, "runs", ()) or ()
            )
        except Exception:
            settled = ()
    live_ids = {str(getattr(run, "run_id", "")) for run in live}
    extra = [run for run in settled if str(getattr(run, "run_id", "")) not in live_ids]
    combined = (*live, *extra)
    if not combined:
        return None
    picked = pick_context_run(combined, now_ts=now)
    if picked is None:
        return None
    try:
        return context_tool_run_line(picked, now_ts=now)
    except Exception:
        return None


def _live_snapshot_runs() -> tuple[Any, ...]:
    """Return the in-memory glance runs, or () when unavailable."""

    try:
        from sase.ace.tui.tool_runs.snapshot import get_snapshot

        snapshot = get_snapshot()
        return tuple(getattr(snapshot, "runs", ()) or ())
    except Exception:
        return ()


def node_runs_for_agent(
    agent: object,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
) -> tuple[Any, ...]:
    """Return the agent-scoped runs for link matching (no I/O).

    Settled facts come from *node_summary* (falling back to the LRU-only
    cached entry, never a store load); live facts overlay from the
    in-memory glance snapshot. Returns () when the node has no selector
    or it has no runs.
    """

    try:
        from sase.ace.tui.tool_runs.summaries import (
            cached_node_summary_for_selector,
        )
        from sase.ace.tui.tool_runs.summaries import node_live_runs as _overlay
        from sase.ace.tui.tool_runs.summaries import selector_for_agent
    except Exception:
        return ()
    try:
        selector = selector_for_agent(agent)
    except Exception:
        return ()
    if selector is None:
        return ()
    summary = node_summary
    if summary is None:
        try:
            summary = cached_node_summary_for_selector(selector)
        except Exception:
            summary = None
    runs = tuple(snapshot_runs) if snapshot_runs is not None else _live_snapshot_runs()
    try:
        live = _overlay(runs, selector)
    except Exception:
        live = ()
    settled: tuple[Any, ...] = ()
    if summary is not None:
        try:
            settled = tuple(getattr(summary, "latest_by_tool", ()) or ()) or tuple(
                getattr(summary, "runs", ()) or ()
            )
        except Exception:
            settled = ()
    live_ids = {str(getattr(run, "run_id", "")) for run in live}
    extra = tuple(
        run for run in settled if str(getattr(run, "run_id", "")) not in live_ids
    )
    return (*live, *extra)


def run_links_for_agent_entries(
    agent: object,
    entries: Any,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
    now_ts: float | None = None,
) -> dict[int, Any]:
    """Return ``{id(entry): run}`` for *agent*'s LLM Calls rows (no I/O)."""

    try:
        runs = node_runs_for_agent(agent, node_summary, snapshot_runs=snapshot_runs)
    except Exception:
        return {}
    if not runs:
        return {}
    try:
        return match_llm_calls_to_runs(entries, runs, now_ts=now_ts)
    except Exception:
        return {}


def slow_suffixes_for_agent_sources(
    agent: object,
    sources: Any,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
    now_ts: float | None = None,
) -> dict[int, Text]:
    """Return ``{id(entry): suffix}`` for *agent*'s slow-tool rows (no I/O)."""

    try:
        runs = node_runs_for_agent(agent, node_summary, snapshot_runs=snapshot_runs)
    except Exception:
        return {}
    if not runs:
        return {}
    entries: list[Any] = []
    for source in sources or ():
        try:
            entries.extend(tuple(getattr(source, "entries", ()) or ()))
        except Exception:
            continue
    try:
        return slow_suffixes_for_entries(entries, runs, now_ts=now_ts)
    except Exception:
        return {}


def context_row_for_agent_cached(
    agent: object,
    node_summary: Any | None = None,
    *,
    snapshot_runs: Any | None = None,
    now_ts: float | None = None,
) -> Text | None:
    """Return the Context card ``Tool run`` value using cached state (no I/O).

    Like :func:`context_row_for_agent` but resolves the node summary from
    the LRU and the live runs from the glance snapshot when the caller
    has no ``tool-runs`` lane at hand, so render paths without lane
    access stay keystroke-safe.
    """

    try:
        runs = node_runs_for_agent(agent, node_summary, snapshot_runs=snapshot_runs)
    except Exception:
        return None
    if not runs:
        return None
    try:
        picked = pick_context_run(runs, now_ts=now_ts)
    except Exception:
        return None
    if picked is None:
        return None
    try:
        return context_tool_run_line(picked, now_ts=now_ts)
    except Exception:
        return None
