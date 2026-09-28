"""Suffix rendering for run-links (LLM Calls, slow-tool, Context)."""

from __future__ import annotations

import time
from typing import Any

from rich.text import Text

from sase.ace.tui.tool_runs._links_shared import is_live_run, run_bucket
from sase.tool.view_vocabulary import (
    TOOL_RUN_ACCENT,
    TOOL_RUN_GLYPH,
    format_age,
    style_for_bucket,
)

__all__ = [
    "context_tool_run_line",
    "llm_call_run_suffix_text",
    "slow_tool_run_suffix_text",
    "suffix_text_with_jump",
]


def _elapsed_s(run: Any, now_ts: float) -> float:
    running_ts = getattr(run, "running_ts", None)
    created_ts = getattr(run, "created_ts", None)
    try:
        start = float(running_ts) if running_ts is not None else float(created_ts or 0)
    except (TypeError, ValueError):
        start = 0.0
    return max(0.0, now_ts - start)


def _last_activity_ts(run: Any) -> float:
    try:
        return float(getattr(run, "last_activity_ts", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _short_suffix_fragment(run: Any, *, now_ts: float) -> str:
    """Return the ``<label> <progress|bucket words>`` fragment for *run*."""

    from sase.tool.view_vocabulary import is_silent

    label = str(getattr(run, "label", "") or "run")
    if is_live_run(run):
        silent_after = 60
        try:
            from sase.ace.tui.tool_runs.snapshot import get_snapshot

            snapshot = get_snapshot()
            silent_after = int(getattr(snapshot, "silent_after_s", 60) or 60)
        except Exception:
            silent_after = 60
        if is_silent(_last_activity_ts(run), now_ts, silent_after):
            return f"{label} silent {format_age(max(0.0, now_ts - _last_activity_ts(run)))}"
        if str(getattr(run, "state", "")) == "created" and not bool(
            getattr(run, "stop_requested", False)
        ):
            return f"{label} starting"
        if bool(getattr(run, "stop_requested", False)):
            return f"{label} stopping"
        expected = getattr(run, "stages_expected", None)
        try:
            done = int(getattr(run, "stages_done", 0) or 0)
        except (TypeError, ValueError):
            done = 0
        in_flight = bool(getattr(run, "current_stage", None)) or is_live_run(run)
        position = done + 1 if in_flight else done
        try:
            expected_int = int(expected) if expected is not None else None
        except (TypeError, ValueError):
            expected_int = None
        if expected_int and 1 <= position <= expected_int:
            return f"{label} {position}/{expected_int}"
        return f"{label} {format_age(_elapsed_s(run, now_ts))}"
    bucket = run_bucket(run)
    style = style_for_bucket(bucket)
    verdict = getattr(run, "verdict", None)
    try:
        new = int(getattr(verdict, "new", 0) or 0)
    except (TypeError, ValueError):
        new = 0
    try:
        known = int(getattr(verdict, "known", 0) or 0)
    except (TypeError, ValueError):
        known = 0
    try:
        unknown = int(getattr(verdict, "unknown", 0) or 0)
    except (TypeError, ValueError):
        unknown = 0
    if bucket == "new_failures":
        rest = f"{new} NEW"
        if known:
            rest += f" · {known} KNOWN"
        return f"{label} {style.glyph} {rest}"
    if bucket == "known_only":
        return f"{label} {style.glyph} known only · {known} KNOWN"
    if bucket == "undetermined":
        reasons = getattr(verdict, "reasons", ()) if verdict is not None else ()
        try:
            untriaged = "not_triaged" in tuple(reasons or ())
        except TypeError:
            untriaged = False
        if untriaged:
            return f"{label} {style.glyph} untriaged"
        return f"{label} {style.glyph} {unknown} UNKNOWN"
    if bucket == "pass":
        return f"{label} {style.glyph}"
    if bucket == "killed":
        return f"{label} {style.glyph} killed"
    if bucket == "stopped":
        return f"{label} {style.glyph} stopped"
    if bucket == "lost":
        return f"{label} {style.glyph} lost"
    return f"{label} {style.glyph} {style.word}"


def llm_call_run_suffix_text(run: Any, *, now_ts: float | None = None) -> str:
    """Return the ``→ ⚒ <fragment>`` suffix for an LLM Calls row."""

    now = float(now_ts) if now_ts is not None else time.time()
    return f"→ {TOOL_RUN_GLYPH} {_short_suffix_fragment(run, now_ts=now)}"


def slow_tool_run_suffix_text(run: Any, *, now_ts: float | None = None) -> str:
    """Return the ``· ⚒ <fragment>`` suffix for a slow-tool row."""

    now = float(now_ts) if now_ts is not None else time.time()
    return f"· {TOOL_RUN_GLYPH} {_short_suffix_fragment(run, now_ts=now)}"


def context_tool_run_line(run: Any, *, now_ts: float | None = None) -> Text:
    """Return the Context card ``Tool run`` value for *run*.

    ``⚒ check ✗ 3 NEW · 04349ecf``: glyph, label, bucket words, and the
    8-hex short id. Pure: no store, no log, no clock beyond *now_ts*.
    """

    now = float(now_ts) if now_ts is not None else time.time()
    fragment = _short_suffix_fragment(run, now_ts=now)
    short_id = str(getattr(run, "run_id", "") or "")[:8]
    text = Text()
    text.append(f"{TOOL_RUN_GLYPH} {fragment}", style="")
    if short_id:
        text.append(f" · {short_id}", style="dim")
    _stamp_jump_meta(text, str(getattr(run, "run_id", "") or ""))
    return text


def _stamp_jump_meta(text: Text, run_id: str) -> None:
    """Stamp the run-block jump target onto *text* as click metadata."""

    if not run_id:
        return
    try:
        from rich.style import Style

        from sase.ace.tui.widgets.prompt_panel._section_navigation import (
            DECK_BLOCK_META_KEY,
        )

        text.stylize(
            Style(meta={DECK_BLOCK_META_KEY: run_id}),
            0,
            len(text.plain),
        )
    except Exception:
        return


def suffix_text_with_jump(
    run: Any, *, prefix: str, now_ts: float | None = None
) -> Text:
    """Return a styled suffix Text stamped with the run-block jump meta."""

    now = float(now_ts) if now_ts is not None else time.time()
    fragment = _short_suffix_fragment(run, now_ts=now)
    run_id = str(getattr(run, "run_id", "") or "")
    bucket = run_bucket(run)
    if is_live_run(run):
        try:
            from sase.tool.view_vocabulary import is_silent

            silent = is_silent(_last_activity_ts(run), now, _snapshot_silent_after_s())
        except Exception:
            silent = False
        style = "bold #FF5F5F" if silent else f"bold {TOOL_RUN_ACCENT}"
    else:
        try:
            style = str(style_for_bucket(bucket).color or "")
        except Exception:
            style = ""
    text = Text(f"{prefix} {TOOL_RUN_GLYPH} {fragment}", style=style)
    _stamp_jump_meta(text, run_id)
    return text


def _snapshot_silent_after_s() -> int:
    try:
        from sase.ace.tui.tool_runs.snapshot import get_snapshot

        return int(getattr(get_snapshot(), "silent_after_s", 60) or 60)
    except Exception:
        return 60
