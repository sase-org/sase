"""Two-card Tools deck helpers (epic sase-1bt, ``tools-deck-cards``).

Pure helpers for the Tools deck's two card hosts: the ``⚒ Runs`` card
(``ToolRunsDeckView``) and the unchanged ``LLM Calls`` panel. Render paths
take in-memory summaries plus ``now`` and never touch the store; only
:func:`probe_tool_runs_card` reads the node-summary LRU and the glance
snapshot, and it never opens SQLite.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from rich.text import Text

from sase.tool.view_vocabulary import (
    TOOL_RUN_ACCENT,
    TOOL_RUN_GLYPH,
    format_age,
    format_min_sec,
    format_settled_ts,
    is_silent,
    style_for_bucket,
    switcher_runs_text,
)

#: Card id of the ``⚒ Runs`` card inside the Tools deck.
TOOLS_RUNS_CARD_ID = "runs"

#: Card id of the unchanged LLM Calls card inside the Tools deck.
TOOLS_LLM_CALLS_CARD_ID = "llm-calls"

#: Tab titles for the two Tools cards.
TOOLS_RUNS_TAB_TITLE = "⚒ Runs"
TOOLS_LLM_CALLS_TAB_TITLE = "LLM Calls"


class ToolRunsDetailLevel(IntEnum):
    """Progressive disclosure levels for the ``⚒ Runs`` card."""

    COMPACT = 0
    STANDARD = 1
    FULL = 2


#: Default ``⚒ Runs`` detail level (plan §3.8).
DEFAULT_TOOL_RUNS_DETAIL_LEVEL = ToolRunsDetailLevel.STANDARD


def coerce_tool_runs_detail_level(level: object) -> ToolRunsDetailLevel:
    """Return ``level`` as a :class:`ToolRunsDetailLevel` (defaults STANDARD)."""
    if isinstance(level, ToolRunsDetailLevel):
        return level
    if isinstance(level, int):
        try:
            return ToolRunsDetailLevel(level)
        except ValueError:
            return DEFAULT_TOOL_RUNS_DETAIL_LEVEL
    try:
        numeric = int(str(level))
    except (TypeError, ValueError):
        return DEFAULT_TOOL_RUNS_DETAIL_LEVEL
    try:
        return ToolRunsDetailLevel(numeric)
    except ValueError:
        return DEFAULT_TOOL_RUNS_DETAIL_LEVEL


def tools_card_ids(has_runs: bool, has_calls: bool) -> tuple[str, ...]:
    """Return the Tools card ids in tab order (``runs`` first)."""
    ids: list[str] = []
    if has_runs:
        ids.append(TOOLS_RUNS_CARD_ID)
    if has_calls:
        ids.append(TOOLS_LLM_CALLS_CARD_ID)
    if not ids:
        ids.append(TOOLS_LLM_CALLS_CARD_ID)
    return tuple(ids)


def tools_default_card(
    card_ids: tuple[str, ...] | list[str],
    preferred: str | None,
) -> str | None:
    """Return the default Tools card (plan D7).

    In order: the panel's sticky Tools preference when that card exists
    for this node, else ``runs`` when the node has runs, else
    ``llm-calls``.
    """
    ids = tuple(card_ids)
    if not ids:
        return None
    if preferred is not None and preferred in ids:
        return preferred
    if TOOLS_RUNS_CARD_ID in ids:
        return TOOLS_RUNS_CARD_ID
    if TOOLS_LLM_CALLS_CARD_ID in ids:
        return TOOLS_LLM_CALLS_CARD_ID
    return ids[0]


def tools_tabs(has_runs: bool, has_calls: bool) -> tuple[Any, ...]:
    """Return the Tools ``CardTab`` entries in tab order (``runs`` first)."""
    from sase.ace.tui.widgets.decks.titles import CardTab

    tabs: list[Any] = []
    if has_runs:
        tabs.append(CardTab(TOOLS_RUNS_CARD_ID, TOOLS_RUNS_TAB_TITLE))
    if has_calls or not tabs:
        tabs.append(CardTab(TOOLS_LLM_CALLS_CARD_ID, TOOLS_LLM_CALLS_TAB_TITLE))
    return tuple(tabs)


def tools_picker_label(n_runs: int | None, n_calls: int | None) -> str:
    """Return the Tools picker count label (``2 runs · 57 calls``)."""
    runs = max(0, int(n_runs)) if n_runs is not None else None
    calls = max(0, int(n_calls)) if n_calls is not None else None
    if runs is not None and calls is not None:
        run_noun = "run" if runs == 1 else "runs"
        call_noun = "call" if calls == 1 else "calls"
        return f"{runs} {run_noun} · {calls} {call_noun}"
    if runs is not None:
        return f"{runs} {'run' if runs == 1 else 'runs'}"
    if calls is not None:
        return f"{calls} {'call' if calls == 1 else 'calls'}"
    return ""


def _tools_switcher_text(n_runs: int, n_calls: int | None = None) -> str:
    """Return the Tools switcher text (plan D8).

    ``tools ⚒N M`` (N runs, M calls), or ``tools ⚒N`` when there are no
    calls. The segment never contains ``" · "``: the switcher joins decks
    with that separator, so an inner one would read as two decks.
    """
    runs_part = switcher_runs_text(n_runs)
    if n_calls is None or int(n_calls) <= 0:
        return f"tools {runs_part}"
    return f"tools {runs_part} {max(0, int(n_calls))}"


def tools_switcher_segment(
    n_runs: int,
    n_calls: int | None = None,
    *,
    live: bool = False,
    silent: bool = False,
) -> Text:
    """Return the styled Tools switcher segment (plan D8).

    Bold Tools accent while a run is live, red while silent. The plain
    text never contains ``" · "``.
    """
    text = _tools_switcher_text(n_runs, n_calls)
    if silent:
        return Text(text, style="bold #FF5F5F")
    if live:
        return Text(text, style=f"bold {TOOL_RUN_ACCENT}")
    return Text(text, style="")


def _live_number(value: Any) -> int | None:
    """Return *value* as an int, or None when it is missing or garbage."""

    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _live_ts(value: Any) -> float | None:
    """Return *value* as an epoch-seconds float, or None when unusable."""

    if value is None or isinstance(value, bool):
        return None
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return None
    return stamp if stamp > 0 else None


def _live_last_activity_ts(brief: Any) -> float | None:
    """Return the last-activity epoch seconds for one run row, if any.

    Glance rows carry ``last_activity_ts``; brief rows fall back to the
    running/created stamp. Pure: a silent block renders from ``now``
    alone (plan §4.8).
    """

    stamp = _live_ts(getattr(brief, "last_activity_ts", None))
    if stamp is not None:
        return stamp
    stamp = _live_ts(getattr(brief, "running_ts", None))
    if stamp is not None:
        return stamp
    return _live_ts(getattr(brief, "created_ts", None))


def tool_run_is_silent(
    brief: Any, now_s: float | None, silent_after_s: int = 60
) -> bool:
    """Return whether a live run row is silent at *now_s* (never raises)."""

    if tool_run_display_bucket(brief) != "running" or now_s is None:
        return False
    try:
        threshold = int(silent_after_s)
    except (TypeError, ValueError):
        threshold = 60
    last_activity = _live_last_activity_ts(brief)
    if last_activity is None:
        return False
    try:
        return is_silent(last_activity, float(now_s), threshold)
    except (TypeError, ValueError):
        return False


def _live_progress(
    brief: Any, detail: Any | None
) -> tuple[
    str | None,
    int | None,
    int | None,
    bool,
]:
    """Return ``(stage, done, expected, in_flight)`` for a live run.

    Glance fields win (``current_stage``, ``stages_done``,
    ``stages_expected``); otherwise the in-flight stage, the finished
    count, and stages plus pending expected stages come from *detail*.
    Missing facts stay None so the caller falls back to elapsed. Pure.
    """

    stage: str | None = None
    glance_stage = getattr(brief, "current_stage", None)
    if glance_stage is not None:
        desc = getattr(glance_stage, "description", None)
        if desc:
            stage = str(desc)
    done = _live_number(getattr(brief, "stages_done", None))
    expected = _live_number(getattr(brief, "stages_expected", None))
    in_flight = glance_stage is not None or str(getattr(brief, "state", "") or "") in (
        "created",
        "running",
    )
    stages = tuple(getattr(detail, "stages", ()) or ()) if detail is not None else ()
    pending = (
        tuple(getattr(detail, "expected_stages", ()) or ())
        if detail is not None
        else ()
    )
    if stages:
        finished = sum(
            1 for entry in stages if getattr(entry, "finished_ms", None) is not None
        )
        flight = next(
            (
                entry
                for entry in stages
                if getattr(entry, "started_ms", None) is not None
                and getattr(entry, "finished_ms", None) is None
            ),
            None,
        )
        if done is None:
            done = finished
        if flight is not None:
            if stage is None:
                flight_desc = getattr(flight, "description", None)
                if flight_desc:
                    stage = str(flight_desc)
            in_flight = True
        elif done is not None and expected is not None and done >= expected:
            in_flight = False
        if expected is None and (stages or pending):
            seen = {str(getattr(entry, "description", "") or "") for entry in stages}
            missing = sum(
                1
                for entry in pending
                if str(getattr(entry, "description", "") or "") not in seen
            )
            expected = len(stages) + missing
    return (stage, done, expected, in_flight)


def _live_outcome_line(
    brief: Any,
    detail: Any | None = None,
    *,
    now_s: float | None = None,
    silent_after_s: int = 60,
) -> Text | None:
    """Return the live-block outcome line, or None when not live/clockless.

    Live reads ``⚒ check ▶ running · test (scoped) 7/11 · 2m13s /
    typ 4m13s`` and silent reads ``⚒⚠ check silent 2d · last activity
    09-25 16:03 · test (scoped)`` (plan §3.8). Progress ``k/n`` shows
    only when ``k <= n``; otherwise the chip falls back to elapsed
    (§3.1). Pure: takes the in-memory row plus ``now``.
    """

    if tool_run_display_bucket(brief) != "running" or now_s is None:
        return None
    try:
        moment = float(now_s)
    except (TypeError, ValueError):
        return None
    label = str(getattr(brief, "label", "") or "run")
    if str(getattr(brief, "state", "") or "") == "created" and not bool(
        getattr(brief, "stop_requested", False)
    ):
        return Text(f"{TOOL_RUN_GLYPH} {label} starting", style="")
    if bool(getattr(brief, "stop_requested", False)):
        return Text(f"{TOOL_RUN_GLYPH} {label} stopping", style="")
    if tool_run_is_silent(brief, moment, silent_after_s):
        style = style_for_bucket("silent")
        last_activity = _live_last_activity_ts(brief)
        line = Text()
        line.append(f"{TOOL_RUN_GLYPH}⚠ {label} ", style="")
        try:
            age = format_age(max(0.0, moment - float(last_activity or moment)))
        except (TypeError, ValueError):
            age = format_age(0.0)
        line.append(f"silent {age}", style=style.color)
        if last_activity is not None:
            from sase.core.time import format_local

            line.append(
                f" · last activity {format_local(last_activity, '%m-%d %H:%M')}",
                style="dim",
            )
        stage, _, _, _ = _live_progress(brief, detail)
        if stage:
            line.append(f" · {stage}", style="")
        return line
    stage, done, expected, in_flight = _live_progress(brief, detail)
    position: int | None = None
    if done is not None and expected is not None and expected > 0:
        candidate = done + (1 if in_flight else 0)
        if 1 <= candidate <= expected:
            position = candidate
    running_ts = _live_ts(getattr(brief, "running_ts", None))
    created_ts = _live_ts(getattr(brief, "created_ts", None))
    start = running_ts if running_ts is not None else created_ts
    elapsed_s = max(0.0, moment - start) if start is not None else 0.0
    typical_ms = _live_number(getattr(brief, "typical_ms", None))
    line = Text()
    line.append(f"{TOOL_RUN_GLYPH} {label} ", style="")
    line.append("▶ running", style=style_for_bucket("running").color)
    if stage:
        line.append(f" · {stage}", style="")
    if position is not None and expected is not None:
        line.append(f" {position}/{expected}", style="")
    elif expected is None:
        line.append(f" · {format_age(elapsed_s)}", style="")
    elapsed_part = format_min_sec(elapsed_s)
    if typical_ms is not None:
        line.append(
            f" · {elapsed_part} / typ {format_min_sec(typical_ms / 1000)}",
            style="dim",
        )
    else:
        line.append(f" · {elapsed_part}", style="dim")
    return line


def tool_run_outcome_line(
    brief: Any,
    detail: Any | None = None,
    *,
    now_s: float | None = None,
    silent_after_s: int = 60,
) -> Text:
    """Return the outcome line for one run block (anatomy comes later).

    ``tools-deck-cards`` carries the outcome line only: glyph, label,
    bucket words and counts, duration against typical, and absolute
    settle time. The waterfall, triage items, child runs, log tail, and
    honest absence arrive with ``runs-card-anatomy``. Live rows with a
    clock render the in-place progress line (plan §4.8); settled rows
    and clockless callers keep the exact settled text.
    """
    live = _live_outcome_line(brief, detail, now_s=now_s, silent_after_s=silent_after_s)
    if live is not None:
        return live
    label = str(getattr(brief, "label", "") or "run")
    bucket = tool_run_display_bucket(brief)
    style = style_for_bucket(bucket)
    text = Text()
    text.append(f"{TOOL_RUN_GLYPH} {label} ", style="")
    text.append(style.glyph, style=style.color)
    words = tool_run_bucket_words(brief, bucket)
    if words:
        text.append(f" {words}", style="")
    duration_ms = getattr(brief, "duration_ms", None)
    typical_ms = getattr(brief, "typical_ms", None)
    duration_part = tool_run_duration_part(duration_ms, typical_ms)
    if duration_part:
        text.append(f" {duration_part}", style="dim")
    settled_ts = getattr(brief, "settled_ts", None)
    if settled_ts:
        try:
            text.append(f" · {format_settled_ts(float(settled_ts))}", style="dim")
        except (TypeError, ValueError):
            pass
    if not text.plain.strip():
        return Text(f"{TOOL_RUN_GLYPH} {label}", style="")
    return text


def tool_run_display_bucket(brief: Any) -> str:
    """Return the §3.2 display bucket for one summary row.

    Settled briefs carry the core precedence bucket on their verdict.
    Live glance rows carry no verdict, so a ``created``/``running``
    state resolves to ``running`` here instead of ``undetermined``.
    """
    verdict = getattr(brief, "verdict", None)
    bucket = str(getattr(verdict, "bucket", "") or "")
    if bucket:
        return bucket
    state = str(getattr(brief, "state", "") or "")
    if state in ("created", "running"):
        return "running"
    return "undetermined"


def tool_run_bucket_words(brief: Any, bucket: str) -> str:
    """Return the bucket words and counts for one outcome line."""
    verdict = getattr(brief, "verdict", None)
    style_words = style_for_bucket(bucket).word
    if bucket == "running":
        return "running"
    if bucket == "pass":
        return str(style_words or "pass")
    if bucket == "new_failures":
        new = _count(getattr(verdict, "new", 0))
        known = _count(getattr(verdict, "known", 0))
        return f"{new} NEW · {known} KNOWN"
    if bucket == "known_only":
        known = _count(getattr(verdict, "known", 0))
        return f"known only · {known} KNOWN"
    if bucket == "undetermined":
        unknown = _count(getattr(verdict, "unknown", 0))
        if unknown:
            return f"{unknown} UNKNOWN"
        return "untriaged"
    if bucket == "killed":
        cause = str(getattr(brief, "terminal_cause", "") or "signal")
        duration_ms = getattr(brief, "duration_ms", None)
        if duration_ms is not None:
            return f"killed at {format_min_sec(duration_ms / 1000)} · {cause}"
        return f"killed · {cause}"
    if bucket == "stopped":
        duration_ms = getattr(brief, "duration_ms", None)
        if duration_ms is not None:
            return f"stopped at {format_min_sec(duration_ms / 1000)}"
        return "stopped"
    if bucket == "lost":
        cause = str(getattr(brief, "terminal_cause", "") or "")
        return f"lost · {cause}" if cause else "lost"
    return str(style_words or bucket)


def tool_run_duration_part(duration_ms: Any, typical_ms: Any) -> str:
    """Return the ``4m12s (typ 4m13s)`` duration fragment, if any."""
    try:
        duration = float(duration_ms) if duration_ms is not None else None
    except (TypeError, ValueError):
        duration = None
    if duration is None:
        return ""
    try:
        typical = float(typical_ms) if typical_ms is not None else None
    except (TypeError, ValueError):
        typical = None
    if typical is not None:
        return (
            f"{format_min_sec(duration / 1000)} (typ {format_min_sec(typical / 1000)})"
        )
    return format_min_sec(duration / 1000)


def _count(value: Any) -> int:
    """Return ``value`` as a non-negative int (0 on garbage)."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def tool_run_block_meta(index: int, brief: Any) -> Any:
    """Return roster-matched :class:`BlockMeta` for one run block.

    ``number`` is the 1-based roster index, ``label`` the run label, the
    glyph and accent come from the §3.2 bucket style, and the status
    bucket is the verdict bucket, so the rail reads
    ``1 ⊘ check  2 ✗ check  3 ✗ check``.
    """
    from sase.ace.tui.widgets.decks.card_block import BlockMeta

    bucket = tool_run_display_bucket(brief)
    style = style_for_bucket(bucket)
    label = str(getattr(brief, "label", "") or "run")
    return BlockMeta(
        number=str(max(1, int(index) + 1)),
        label=label,
        glyph=style.glyph,
        accent=style.color,
        status_bucket=bucket,
        kind="tool_run",
    )


def tool_run_block_header_text(
    _index: int,
    brief: Any,
    detail: Any | None = None,
    *,
    now_s: float | None = None,
    silent_after_s: int = 60,
) -> Text:
    """Return the block header line with the anchor meta stamped.

    Headers carry ``DECK_BLOCK_META_KEY`` like FINAL's run headers, so
    the generalized block host can anchor rows back to run ids. Live
    headers carry the same in-place progress line as the block body.
    """
    from rich.style import Style

    from sase.ace.tui.widgets.prompt_panel._section_navigation import (
        DECK_BLOCK_META_KEY,
    )

    run_id = str(getattr(brief, "run_id", "") or "")
    line = tool_run_outcome_line(
        brief, detail, now_s=now_s, silent_after_s=silent_after_s
    )
    header = Text(line.plain)
    header.stylize(line.style if isinstance(line.style, str) else "")
    for span in line.spans:
        try:
            header.stylize(span.style, span.start, span.end)
        except Exception:
            continue
    header.append("\n")
    if run_id:
        header.stylize(
            Style(meta={DECK_BLOCK_META_KEY: run_id}),
            0,
            len(header.plain),
        )
    return header


def tool_runs_card_search_text(renderables: Any) -> str:
    """Return searchable text for rendered Runs card lines (never raises)."""
    try:
        from sase.ace.tui.widgets.renderable_text import renderable_to_text
        from rich.console import Group

        return renderable_to_text(Group(*tuple(renderables or ()))) or ""
    except Exception:
        return ""


def probe_tool_runs_card(
    agent: object, *, attempt_number: int | None = None
) -> tuple[bool | None, int]:
    """Probe Runs-card availability without I/O.

    Reads the node-summary LRU plus the glance snapshot: ``(True, n)``
    when the node has runs, ``(False, 0)`` when its history is known
    empty, and ``(None, 0)`` while the first load is still in flight.
    Pinned attempts, clans, tribes, and remote rows stay without Runs.
    """
    from sase.ace.tui.tool_runs import summaries as _summaries
    from sase.ace.tui.tool_runs.attribution import row_identity_from_agent
    from sase.ace.tui.tool_runs.snapshot import get_snapshot

    if attempt_number is not None:
        return (False, 0)
    try:
        row = row_identity_from_agent(agent)
    except Exception:
        return (None, 0)
    if row.is_remote or row.is_clan:
        return (False, 0)
    try:
        selector = _summaries.selector_for_agent(agent)
    except Exception:
        return (None, 0)
    if selector is None:
        return (False, 0)
    try:
        summary = _summaries.cached_node_summary_for_selector(selector)
    except Exception:
        summary = None
    try:
        snapshot = get_snapshot()
    except Exception:
        snapshot = None
    live: tuple[Any, ...] = ()
    if snapshot is not None:
        try:
            live = _summaries.node_live_runs(tuple(snapshot.runs or ()), selector)
        except Exception:
            live = ()
    if summary is None:
        if live:
            return (True, len(live))
        if snapshot is None:
            return (None, 0)
        return (None, 0)
    combined: dict[str, Any] = {}
    for brief in summary.runs or ():
        run_id = str(getattr(brief, "run_id", "") or "")
        if run_id:
            combined[run_id] = brief
    for run in live:
        run_id = str(getattr(run, "run_id", "") or "")
        if run_id and run_id not in combined:
            combined[run_id] = run
    total = _count(getattr(summary, "total_runs", 0))
    total = max(total, len(combined))
    if combined or total > 0:
        return (True, total)
    return (False, 0)


def tools_empty_copy(is_remote: bool, machine: str | None = None) -> str:
    """Return the Tools empty-state copy (plan §3.8, D15)."""
    if is_remote:
        if machine:
            return f"ToolRun history lives on `{machine}`"
        return "ToolRun history lives on the agent's machine"
    return "No tool runs or LLM calls for this node"


def tools_truncated_line(hidden: int) -> str:
    """Return the card tail when the node summary is truncated."""
    count = max(0, int(hidden))
    return f"+{count} older runs · Admin Center → Tools"


__all__ = [
    "DEFAULT_TOOL_RUNS_DETAIL_LEVEL",
    "TOOLS_LLM_CALLS_CARD_ID",
    "TOOLS_LLM_CALLS_TAB_TITLE",
    "TOOLS_RUNS_CARD_ID",
    "TOOLS_RUNS_TAB_TITLE",
    "ToolRunsDetailLevel",
    "coerce_tool_runs_detail_level",
    "probe_tool_runs_card",
    "tool_run_block_header_text",
    "tool_run_block_meta",
    "tool_run_bucket_words",
    "tool_run_display_bucket",
    "tool_run_duration_part",
    "tool_run_is_silent",
    "tool_run_outcome_line",
    "tool_runs_card_search_text",
    "tools_card_ids",
    "tools_default_card",
    "tools_empty_copy",
    "tools_picker_label",
    "tools_switcher_segment",
    "tools_tabs",
    "tools_truncated_line",
]
