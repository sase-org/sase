"""Pure live-only row-chip math (plan §3.6).

All time handling is minute-quantized: the chip text only changes when the
minute bucket changes, so the 1 s runtime tick repaints cheaply. Render and
cache paths call these helpers with in-memory snapshot state plus ``now``;
nothing here stats, opens SQLite, or reads a log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.tool.view_vocabulary import TOOL_RUN_ACCENT, is_silent, row_chip_text

if TYPE_CHECKING:
    from sase.core.tool_run import ToolRunGlance

FAILURE_COLOR = "#FF5F5F"

#: Progress changes width by at most one cell, within patch_row's slack.
#: Appearing, disappearing, and turning silent may exceed it and use the
#: existing rebuild escalation.
_ROW_CHIP_PATCH_SLACK_CELLS = 1


def _minute_bucket(now_ts: float) -> int:
    """Return the minute bucket for *now_ts* (chip time quantization)."""

    return int(now_ts // 60)


def _run_is_silent(run: ToolRunGlance, now_ts: float, silent_after_s: int = 60) -> bool:
    """Return True when a live run is past the silence threshold (D4)."""

    try:
        last_activity = float(getattr(run, "last_activity_ts", 0) or 0)
    except (TypeError, ValueError):
        return False
    return is_silent(last_activity, now_ts, silent_after_s)


def _elapsed_for_run(run: ToolRunGlance, now_ts: float) -> float:
    """Return seconds since the run started (running stamp wins)."""

    running_ts = getattr(run, "running_ts", None)
    created_ts = getattr(run, "created_ts", None)
    try:
        start = float(running_ts) if running_ts is not None else float(created_ts or 0)
    except (TypeError, ValueError):
        start = 0.0
    return max(0.0, now_ts - start)


def _silent_age_for_run(run: ToolRunGlance, now_ts: float) -> float:
    """Return seconds since the run's last activity."""

    try:
        last_activity = float(getattr(run, "last_activity_ts", 0) or 0)
    except (TypeError, ValueError):
        last_activity = 0.0
    return max(0.0, now_ts - last_activity)


def _order_live_runs(
    selected: tuple[ToolRunGlance, ...] | list[ToolRunGlance],
    now_ts: float,
    silent_after_s: int = 60,
) -> tuple[ToolRunGlance, ...]:
    """Order selected live runs with the primary chip run first.

    Silent outranks live; a stop request outranks a plain live run; the
    earliest created run wins remaining ties so the choice is stable.
    """

    def _key(run: ToolRunGlance) -> tuple[int, int, Any]:
        silent = 0 if _run_is_silent(run, now_ts, silent_after_s) else 1
        stopping = 0 if bool(getattr(run, "stop_requested", False)) else 1
        try:
            created = int(getattr(run, "created_ts", 0) or 0)
        except (TypeError, ValueError):
            created = 0
        return (silent, stopping, created)

    return tuple(sorted(selected, key=_key))


def row_chip_for_runs(
    selected: tuple[ToolRunGlance, ...] | list[ToolRunGlance],
    now_ts: float,
    silent_after_s: int = 60,
) -> tuple[str, str] | None:
    """Return ``(text, style)`` for the live-only row chip, or None.

    Text comes from the shared :func:`row_chip_text` vocabulary so the row,
    header, and card agree. Silent carries ``⚠`` plus the word and red;
    live uses the Tools accent.
    """

    ordered = _order_live_runs(tuple(selected), now_ts, silent_after_s)
    if not ordered:
        return None
    primary = ordered[0]
    extra = len(ordered) - 1
    if _run_is_silent(primary, now_ts, silent_after_s):
        text = row_chip_text(
            str(getattr(primary, "label", "") or ""),
            silent_age_s=_silent_age_for_run(primary, now_ts),
            extra_live=extra,
        )
        return (text, f"bold {FAILURE_COLOR}")
    in_flight = bool(getattr(primary, "current_stage", None)) or str(
        getattr(primary, "state", "")
    ) in {"created", "running"}
    text = row_chip_text(
        str(getattr(primary, "label", "") or ""),
        state=str(getattr(primary, "state", "running") or "running"),
        stages_done=int(getattr(primary, "stages_done", 0) or 0),
        stages_expected=getattr(primary, "stages_expected", None),
        in_flight=in_flight,
        stop_requested=bool(getattr(primary, "stop_requested", False)),
        elapsed_s=_elapsed_for_run(primary, now_ts),
        extra_live=extra,
    )
    return (text, f"bold {TOOL_RUN_ACCENT}")


def tool_run_chip_token(
    selected: tuple[ToolRunGlance, ...] | list[ToolRunGlance],
    now_ts: float,
    silent_after_s: int = 60,
) -> tuple[Any, ...] | None:
    """Return a hashable token for the chip, or None when no chip shows.

    The minute bucket is part of the token so a 1 s tick repaints only when
    the text can have changed. Progress, state, stop requests, and the
    primary run id complete the key.
    """

    ordered = _order_live_runs(tuple(selected), now_ts, silent_after_s)
    if not ordered:
        return None
    primary = ordered[0]
    silent = _run_is_silent(primary, now_ts, silent_after_s)
    bucket = _minute_bucket(now_ts)
    if silent:
        age_bucket = _minute_bucket(_silent_age_for_run(primary, now_ts))
        return (
            str(getattr(primary, "run_id", "")),
            len(ordered) - 1,
            True,
            bucket,
            age_bucket,
            str(getattr(primary, "label", "")),
        )
    in_flight = bool(getattr(primary, "current_stage", None)) or str(
        getattr(primary, "state", "")
    ) in {"created", "running"}
    if getattr(primary, "stages_expected", None):
        age_part: Any = None
    else:
        age_part = _minute_bucket(_elapsed_for_run(primary, now_ts))
    return (
        str(getattr(primary, "run_id", "")),
        len(ordered) - 1,
        False,
        bucket,
        age_part,
        str(getattr(primary, "state", "")),
        int(getattr(primary, "stages_done", 0) or 0),
        getattr(primary, "stages_expected", None),
        bool(getattr(primary, "stop_requested", False)),
        in_flight,
        str(getattr(primary, "label", "")),
    )


def chip_uses_elapsed_fallback(
    selected: tuple[ToolRunGlance, ...] | list[ToolRunGlance],
    now_ts: float,
    silent_after_s: int = 60,
) -> bool:
    """Return True when the chip text depends on wall-clock time.

    Progress ``k/n`` chips are stable; elapsed fallbacks and silent ages
    tick. Callers join the 1 s runtime patch set when this is True.
    """

    ordered = _order_live_runs(tuple(selected), now_ts, silent_after_s)
    if not ordered:
        return False
    primary = ordered[0]
    if _run_is_silent(primary, now_ts, silent_after_s):
        return True
    if bool(getattr(primary, "stop_requested", False)):
        return False
    if str(getattr(primary, "state", "")) == "created":
        return False
    expected = getattr(primary, "stages_expected", None)
    if expected is not None and expected > 0:
        try:
            done = int(getattr(primary, "stages_done", 0) or 0)
        except (TypeError, ValueError):
            done = 0
        in_flight = bool(getattr(primary, "current_stage", None)) or str(
            getattr(primary, "state", "")
        ) in {"created", "running"}
        position = done + 1 if in_flight else done
        if 1 <= position <= int(expected):
            return False
    return True


__all__ = [
    "chip_uses_elapsed_fallback",
    "row_chip_for_runs",
    "tool_run_chip_token",
]
