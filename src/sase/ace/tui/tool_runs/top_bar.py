"""Pure top-bar ``tools:``/``bg:`` model (epic sase-1ih, phase top-bar-tools-bg).

One pure function of the glance snapshot (or ``None``), the disabled
reason, the proc lanes, ``now``, and the load-failure state. Render paths
call it with in-memory state plus ``now``; nothing here stats, opens
SQLite, or reads a log.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any

from sase.tool.view_vocabulary import (
    format_age,
    is_silent,
    row_chip_text,
)

_LIVE_STATES = frozenset({"created", "running"})

#: Seconds of continuous glance-load failure before the last snapshot
#: renders stale (dim chips with a trailing ``?``).
STALE_AFTER_S = 10.0

#: Maximum runs listed in the ``tools:`` tooltip.
_TOOLTIP_MAX_RUNS = 5


def _run_id(run: Any) -> str:
    return str(getattr(run, "run_id", "") or "")


def _is_live(run: Any) -> bool:
    return str(getattr(run, "state", "") or "") in _LIVE_STATES


def _fold_live_children(runs: list[Any]) -> list[Any]:
    """Fold a live child into its live parent; dedupe by run id."""
    ids = {_run_id(run) for run in runs}
    folded = [
        run
        for run in runs
        if not (
            getattr(run, "parent_run_id", None)
            and str(getattr(run, "parent_run_id", "") or "") in ids
        )
    ]
    seen: set[str] = set()
    unique: list[Any] = []
    for run in folded:
        run_id = _run_id(run)
        if run_id in seen:
            continue
        seen.add(run_id)
        unique.append(run)
    return unique


def _run_is_silent(run: Any, now_ts: float, silent_after_s: int) -> bool:
    try:
        last_activity = float(getattr(run, "last_activity_ts", 0) or 0)
    except (TypeError, ValueError):
        return False
    return is_silent(last_activity, now_ts, silent_after_s)


def _created_ts(run: Any) -> int:
    try:
        return int(getattr(run, "created_ts", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _elapsed_for_run(run: Any, now_ts: float) -> float:
    running_ts = getattr(run, "running_ts", None)
    created_ts = getattr(run, "created_ts", None)
    try:
        start = float(running_ts) if running_ts is not None else float(created_ts or 0)
    except (TypeError, ValueError):
        start = 0.0
    return max(0.0, now_ts - start)


def _silent_age_for_run(run: Any, now_ts: float) -> float:
    try:
        last_activity = float(getattr(run, "last_activity_ts", 0) or 0)
    except (TypeError, ValueError):
        last_activity = 0.0
    return max(0.0, now_ts - last_activity)


def tool_run_owner_proc_ids(snapshot: Any | None) -> frozenset[str]:
    """Return the ``owner_id`` of live runs owned by a proc.

    Feeds the proc partition so the ``: tool run`` Command Line owner is
    drawn once, in the tool lane.
    """
    if snapshot is None:
        return frozenset()
    ids: set[str] = set()
    for run in tuple(getattr(snapshot, "runs", None) or ()):
        if not _is_live(run):
            continue
        if getattr(run, "owner_kind", None) != "proc":
            continue
        owner_id = getattr(run, "owner_id", None)
        if owner_id:
            ids.add(str(owner_id))
    return frozenset(ids)


@dataclass(frozen=True)
class TopBarToolsModel:
    """Frozen top-bar ``tools:`` model for one refresh."""

    live: int = 0
    silent: int = 0
    truncated: bool = False
    stale: bool = False
    fallback: bool = False
    pre_load: bool = False
    bare_monitors: int = 0
    bare_monitor_names: tuple[str, ...] = ()
    tooltip: str = ""


def _hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "this machine"


def _tooltip_run_line(run: Any, now_ts: float, silent_after_s: int) -> str:
    label = str(getattr(run, "label", "") or "")
    if _run_is_silent(run, now_ts, silent_after_s):
        text = row_chip_text(
            label,
            silent_age_s=_silent_age_for_run(run, now_ts),
        )
        return f"  {text}"
    in_flight = bool(getattr(run, "current_stage", None)) or str(
        getattr(run, "state", "")
    ) in {"created", "running"}
    try:
        stages_expected = getattr(run, "stages_expected", None)
        stages_expected = int(stages_expected) if stages_expected is not None else None
    except (TypeError, ValueError):
        stages_expected = None
    try:
        stages_done = int(getattr(run, "stages_done", 0) or 0)
    except (TypeError, ValueError):
        stages_done = 0
    text = row_chip_text(
        label,
        state=str(getattr(run, "state", "running") or "running"),
        stages_done=stages_done,
        stages_expected=stages_expected,
        in_flight=in_flight,
        stop_requested=bool(getattr(run, "stop_requested", False)),
    )
    return f"  {text} · {format_age(_elapsed_for_run(run, now_ts))}"


def top_bar_tools_model(
    *,
    snapshot: Any | None,
    lanes: Any | None,
    now_ts: float,
    now_mono: float | None = None,
    failing_since_mono: float | None = None,
    disabled_reason: str | None = None,
) -> TopBarToolsModel:
    """Build the frozen ``tools:`` model from in-memory state plus ``now``.

    Counts are disjoint everywhere: ``live`` counts healthy live runs and
    ``silent`` counts silent ones, so the total is live+silent. A live
    child folds into its live parent. Before the first glance load the
    chips hide (never a false zero); after ≥10 s of load failure the last
    snapshot renders stale; without the binding a dim lower bound counts
    distinct run ids from carrier tags.
    """
    bare_monitors = int(getattr(lanes, "monitors", 0) or 0) if lanes is not None else 0
    try:
        bare_names = tuple(getattr(lanes, "monitor_names", None) or ())
    except Exception:
        bare_names = ()
    if disabled_reason is not None:
        tool_ids: Any = getattr(lanes, "tool_run_ids", frozenset()) or frozenset()
        try:
            lower = len(set(tool_ids))
        except TypeError:
            lower = 0
        return TopBarToolsModel(
            live=lower,
            silent=0,
            truncated=False,
            stale=False,
            fallback=True,
            pre_load=False,
            bare_monitors=bare_monitors,
            bare_monitor_names=tuple(bare_names),
            tooltip="ledger unavailable — counting tool procs",
        )
    if snapshot is None:
        return TopBarToolsModel(
            live=0,
            silent=0,
            truncated=False,
            stale=False,
            fallback=False,
            pre_load=True,
            bare_monitors=bare_monitors,
            bare_monitor_names=tuple(bare_names),
            tooltip="",
        )
    try:
        silent_after_s = int(getattr(snapshot, "silent_after_s", 60) or 60)
    except (TypeError, ValueError):
        silent_after_s = 60
    live_runs = _fold_live_children(
        [run for run in tuple(getattr(snapshot, "runs", None) or ()) if _is_live(run)]
    )
    # A live child with a settled parent stays visible: only live parents
    # fold, and settled runs never reach this list.
    silent_runs = [
        run for run in live_runs if _run_is_silent(run, now_ts, silent_after_s)
    ]
    healthy_runs = [
        run for run in live_runs if not _run_is_silent(run, now_ts, silent_after_s)
    ]
    stale = False
    if failing_since_mono is not None and now_mono is not None:
        try:
            stale = (float(now_mono) - float(failing_since_mono)) >= STALE_AFTER_S
        except (TypeError, ValueError):
            stale = False
    try:
        truncated = bool(getattr(snapshot, "truncated", False))
    except Exception:
        truncated = False
    # Tooltip: silent first, then oldest; at most five runs.
    ordered = sorted(silent_runs, key=_created_ts) + sorted(
        healthy_runs, key=_created_ts
    )
    total = len(live_runs)
    lines = [f"{total} live tool run{'s' if total != 1 else ''} on {_hostname()}"]
    for run in ordered[:_TOOLTIP_MAX_RUNS]:
        lines.append(_tooltip_run_line(run, now_ts, silent_after_s))
    if bare_monitors > 0:
        names = ", ".join(bare_names[:_TOOLTIP_MAX_RUNS]) if bare_names else ""
        noun = "monitor" if bare_monitors == 1 else "monitors"
        suffix = f": {names}" if names else ""
        lines.append(f"{bare_monitors} {noun} not running a tool{suffix}")
    if stale:
        lines.append("glance stale — showing the last snapshot")
    if truncated:
        lines.append("showing the first 200 runs")
    lines.append("Click to open Admin Center › Tools (all projects)")
    return TopBarToolsModel(
        live=len(healthy_runs),
        silent=len(silent_runs),
        truncated=truncated,
        stale=stale,
        fallback=False,
        pre_load=False,
        bare_monitors=bare_monitors,
        bare_monitor_names=tuple(bare_names),
        tooltip="\n".join(lines),
    )


def bg_tooltip_text(*, bg_rows: tuple[Any, ...] = ()) -> str:
    """Build the ``bg:`` tooltip: headline, up to 5 labels, click target.

    Rows are oldest first. A row whose origin is not ``ace`` shows its
    origin in parentheses.
    """
    rows = tuple(bg_rows or ())
    noun = "proc" if len(rows) == 1 else "procs"
    lines = [f"{len(rows)} TUI background {noun}"]
    for row in rows[:_TOOLTIP_MAX_RUNS]:
        label = str(getattr(row, "label", "") or "")
        origin = getattr(row, "origin", None)
        if origin and origin != "ace":
            lines.append(f"  {label} ({origin})")
        else:
            lines.append(f"  {label}")
    lines.append("Click to open the Procs tab")
    return "\n".join(lines)


__all__ = [
    "STALE_AFTER_S",
    "TopBarToolsModel",
    "bg_tooltip_text",
    "tool_run_owner_proc_ids",
    "top_bar_tools_model",
]
