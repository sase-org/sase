"""Full ``⚒ Runs`` block anatomy (epic sase-1bt, ``runs-card-anatomy``).

Pure functions of in-memory briefs, details, and tails plus ``now``:
nothing stats, opens SQLite, or reads a log on a render path. The
Admin Center Tools pane reuses :func:`render_tool_run_block` directly
(plan §4.7 step 3).
"""

from __future__ import annotations

import shlex
from datetime import datetime
from typing import Any

from rich.text import Text

from sase.tool.render import format_duration_ms

from .deck import (
    ToolRunsDetailLevel,
    tool_run_bucket_words,
    tool_run_duration_part,
    tool_run_display_bucket,
    tool_run_outcome_line,
)
from .waterfall import waterfall_rows

#: STANDARD shows at most this many triage items before ``+N more``.
STANDARD_MAX_ITEMS = 20

#: COMPACT shows at most this many triage items.
COMPACT_MAX_ITEMS = 3

#: STANDARD log-tail line cap; FULL raises it.
STANDARD_TAIL_LINES = 12
FULL_TAIL_LINES = 60

_ITEM_CLASS_STYLES: dict[str | None, str] = {
    "NEW": "#FF5F5F",
    "UNKNOWN": "#FFAF5F",
    "KNOWN": "#87AF87",
    "FLAKY": "dim",
    None: "dim",
}


def _truncate(text: str, max_cells: int) -> str:
    """Truncate *text* with … so it fits *max_cells* cells."""

    if max_cells <= 1:
        return "…"
    if len(text) <= max_cells:
        return text
    return text[: max_cells - 1] + "…"


def _format_bytes(total_bytes: int) -> str:
    """Format a byte count as ``1.2 MB``/``34 KB``/``512 B``."""

    total = max(0, int(total_bytes))
    if total >= 1_000_000:
        return f"{total / 1_000_000:.1f} MB"
    if total >= 1_000:
        return f"{total / 1_000:.0f} KB"
    return f"{total} B"


def _short_run_id(run_id: str) -> str:
    """Return the 8-hex display prefix of *run_id*."""

    return (run_id or "")[:8]


def _context_line(brief: Any) -> Text:
    """Return the dim context line (id, launch mode, turn, bead, ws)."""

    run_id = str(getattr(brief, "run_id", "") or "")
    owner_kind = str(getattr(brief, "owner_kind", "") or "")
    owner_id = str(getattr(brief, "owner_id", "") or "")
    if owner_kind == "monitor" and owner_id:
        launch = f"→ monitor {owner_id}"
    elif owner_kind == "proc" and owner_id:
        launch = f"→ proc {owner_id}"
    else:
        launch = "inline"
    parts = [f"run {_short_run_id(run_id)}", launch]
    agent = getattr(brief, "agent", None)
    if agent:
        parts.append(f"turn {agent}")
    bead = getattr(brief, "bead", None)
    if bead:
        parts.append(f"bead {bead}")
    workspace = getattr(brief, "workspace", None)
    if workspace:
        parts.append(f"ws {workspace}")
    return Text("  " + " · ".join(parts), style="dim")


def _argv_line(
    display_argv: tuple[str, ...] | list[str],
    *,
    level: ToolRunsDetailLevel,
    width: int,
) -> Text | None:
    """Return the ``$ <display_argv>`` line, or None when there is no argv."""

    argv = [str(item) for item in (display_argv or ())]
    if not argv:
        return None
    try:
        joined = shlex.join(argv)
    except Exception:
        joined = " ".join(argv)
    if level != ToolRunsDetailLevel.FULL:
        joined = _truncate(joined, max(8, width - 6))
    return Text(f"  $ {joined}", style="")


def _killed_note() -> Text:
    """Return the dim killed-run explanation line (§3.8)."""

    return Text(
        "  the caller killed the command; this is not a test failure",
        style="dim",
    )


def _triage_item_lines(
    item: Any,
    *,
    level: ToolRunsDetailLevel,
    width: int,
) -> list[Text]:
    """Return the class/stage/display line plus the dim witness line."""

    raw_class = getattr(item, "item_class", None)
    item_class = str(raw_class).upper() if raw_class else None
    style = _ITEM_CLASS_STYLES.get(item_class, "dim")
    tag = item_class or "UNLABELED"
    stage_key = str(getattr(item, "stage_key", "") or "")
    display = str(getattr(item, "display", "") or "")
    head = Text()
    head.append(f"  {tag}  ", style=style)
    if stage_key:
        head.append(f"{stage_key}  ", style="dim")
    head.append(_truncate(display, max(8, width - len(tag) - len(stage_key) - 8)))
    witness_runs = int(getattr(item, "witness_runs", 0) or 0)
    witness_agents = int(getattr(item, "witness_agents", 0) or 0)
    first_seen = getattr(item, "first_seen_ts", None)
    witness = f"{witness_runs} runs · {witness_agents} agents"
    if first_seen:
        try:
            witness += datetime.fromtimestamp(float(first_seen)).strftime(
                " · since %m-%d"
            )
        except (TypeError, ValueError, OSError, OverflowError):
            pass
    lines = [head, Text(f"      {witness}", style="dim")]
    if level == ToolRunsDetailLevel.FULL:
        for path in tuple(getattr(item, "locator_paths", ()) or ()):
            lines.append(Text(f"      {path}", style="dim"))
    return lines


def _child_run_line(child: Any) -> Text:
    """Return one ``↳ child run`` line with its own bucket (§3.8, D9)."""

    from sase.tool.view_vocabulary import style_for_bucket

    run_id = str(getattr(child, "run_id", "") or "")
    label = str(getattr(child, "label", "") or "run")
    bucket = tool_run_display_bucket(child)
    style = style_for_bucket(bucket)
    line = Text()
    line.append("  ↳ ", style="dim")
    line.append(f"child run {_short_run_id(run_id)} {label} ", style="dim")
    line.append(style.glyph, style=style.color)
    words = tool_run_bucket_words(child, bucket)
    if words:
        line.append(f" {words}", style="")
    duration_part = tool_run_duration_part(
        getattr(child, "duration_ms", None), getattr(child, "typical_ms", None)
    )
    if duration_part:
        line.append(f" {duration_part}", style="dim")
    return line


def _tail_header(tail: Any, hint_number: int | None = None) -> Text:
    """Return the log-tail header stating count, size, and truncation."""

    lines = tuple(getattr(tail, "lines", ()) or ())
    size = _format_bytes(int(getattr(tail, "total_bytes", 0) or 0))
    truncated = bool(getattr(tail, "truncated", False))
    head = f"  ── log tail · {len(lines)} lines · {size} retained"
    if truncated:
        head += " · truncated"
    if hint_number is not None:
        head += f" · [{hint_number}] ⚒ run log"
    return Text(head + " ──", style="dim")


def _absence_line(kind: str) -> Text:
    """Return the honest-absence line for *kind* (never an empty success)."""

    words = {
        "detail-pruned": "detail pruned · summary retained",
        "detail-missing": "run detail unavailable · summary retained",
        "log-pruned": "log pruned (retention)",
        "owner-missing": "owner log unavailable",
        "not-recorded": "no log recorded",
    }
    return Text(f"  {words.get(kind, 'no log recorded')}", style="dim")


def _tail_availability_kind(tail: Any) -> str:
    """Map a :class:`ToolRunLogTail` availability to an absence kind."""

    availability = str(getattr(tail, "availability", "not-recorded") or "")
    if availability in ("available", "truncated"):
        return ""
    if availability == "pruned":
        return "log-pruned"
    if availability == "owner-missing":
        return "owner-missing"
    return "not-recorded"


def _compact_passed_line(stages: tuple[Any, ...] | list[Any]) -> Text | None:
    """Return the ``✓ N stages passed · <total>`` roll-up, if any passed."""

    passed = [
        stage
        for stage in stages
        if (getattr(stage, "exit_code", None) in (0, None))
        and getattr(stage, "finished_ms", None) is not None
    ]
    if not passed:
        return None
    total = 0
    for stage in passed:
        elapsed = getattr(stage, "elapsed_ms", None)
        if elapsed is None:
            started = getattr(stage, "started_ms", None)
            finished = getattr(stage, "finished_ms", None)
            if started is not None and finished is not None:
                elapsed = int(finished) - int(started)
        if elapsed is not None:
            try:
                total += int(elapsed)
            except (TypeError, ValueError):
                pass
    noun = "stage" if len(passed) == 1 else "stages"
    return Text(
        f"  ✓ {len(passed)} {noun} passed · {format_duration_ms(total)}",
        style="dim #5FD75F",
    )


def render_tool_run_block(
    brief: Any,
    detail: Any | None,
    *,
    level: ToolRunsDetailLevel = ToolRunsDetailLevel.STANDARD,
    width: int = 100,
    now_ms: int | None = None,
    tail: Any | None = None,
    tail_lines: int | None = None,
    include_outcome: bool = True,
    hint_numbers: Any | None = None,
) -> Text:
    """Render one run block: outcome, context, waterfall, triage, tail.

    Pure: takes the in-memory brief, the loaded detail (or None when
    the load missed), and the bounded tail read by the shared
    ``tool_run_log_tail`` helper. ``level`` selects COMPACT, STANDARD,
    or FULL disclosure (§3.8). ``include_outcome`` drops the outcome
    line when the caller already paints it as the block header.
    ``hint_numbers`` maps run ids to ``v`` hint numbers; a mapped
    block's tail header shows its ``[N]`` marker. Never renders
    ``private_argv``: only ``display_argv`` is read.
    """

    try:
        level = ToolRunsDetailLevel(level)
    except ValueError:
        level = ToolRunsDetailLevel.STANDARD
    text = Text()
    if include_outcome:
        text.append_text(tool_run_outcome_line(brief))
        if not text.plain.endswith("\n"):
            text.append("\n")
    bucket = tool_run_display_bucket(brief)
    text.append_text(_context_line(brief))
    text.append("\n")
    if bucket == "killed":
        text.append_text(_killed_note())
        text.append("\n")
    if detail is None or not bool(getattr(detail, "found", False)):
        if (
            bool(getattr(detail, "detail_pruned", False))
            if detail is not None
            else False
        ):
            text.append_text(_absence_line("detail-pruned"))
        else:
            text.append_text(_absence_line("detail-missing"))
        text.append("\n")
        return text
    if bool(getattr(detail, "detail_pruned", False)):
        text.append_text(_absence_line("detail-pruned"))
        text.append("\n")
        return text
    argv_line = _argv_line(
        tuple(getattr(detail, "display_argv", ()) or ()),
        level=level,
        width=width,
    )
    if argv_line is not None:
        text.append_text(argv_line)
        text.append("\n")
    stages = tuple(getattr(detail, "stages", ()) or ())
    expected = tuple(getattr(detail, "expected_stages", ()) or ())
    is_live = bucket == "running"
    if level == ToolRunsDetailLevel.COMPACT:
        failing = [
            stage
            for stage in stages
            if (getattr(stage, "exit_code", None) not in (0, None))
            or getattr(stage, "started_ms", None) is None
            or getattr(stage, "finished_ms", None) is None
        ]
        if failing or expected:
            text.append_text(
                waterfall_rows(
                    failing, expected, width=width, is_live=is_live, now_ms=now_ms
                )
            )
        passed_line = _compact_passed_line(stages)
        if passed_line is not None:
            text.append_text(passed_line)
            text.append("\n")
    else:
        if stages or expected:
            text.append_text(
                waterfall_rows(
                    stages, expected, width=width, is_live=is_live, now_ms=now_ms
                )
            )
    items = tuple(getattr(detail, "triage_items", ()) or ())
    if items:
        if level == ToolRunsDetailLevel.COMPACT:
            shown, cap = items[:COMPACT_MAX_ITEMS], COMPACT_MAX_ITEMS
        elif level == ToolRunsDetailLevel.FULL:
            shown, cap = items, len(items)
        else:
            shown, cap = items[:STANDARD_MAX_ITEMS], STANDARD_MAX_ITEMS
        for item in shown:
            for line in _triage_item_lines(item, level=level, width=width):
                text.append_text(line)
                text.append("\n")
        hidden = len(items) - len(shown)
        truncated = bool(getattr(detail, "items_truncated", False))
        if hidden > 0 or truncated:
            text.append(Text(f"  +{hidden} more", style="dim"))
            text.append("\n")
    for child in tuple(getattr(detail, "child_runs", ()) or ()):
        text.append_text(_child_run_line(child))
        text.append("\n")
    if level != ToolRunsDetailLevel.COMPACT:
        kind = _tail_availability_kind(tail) if tail is not None else "not-recorded"
        if kind:
            text.append_text(_absence_line(kind))
            text.append("\n")
        else:
            assert tail is not None
            cap = (
                FULL_TAIL_LINES
                if level == ToolRunsDetailLevel.FULL
                else STANDARD_TAIL_LINES
            )
            if tail_lines is not None:
                cap = max(1, int(tail_lines))
            hint_number: int | None = None
            try:
                run_id = str(getattr(brief, "run_id", "") or "")
                if hint_numbers is not None and run_id:
                    found = hint_numbers.get(run_id)
                    hint_number = int(found) if found is not None else None
            except (TypeError, ValueError, AttributeError):
                hint_number = None
            text.append_text(_tail_header(tail, hint_number))
            text.append("\n")
            for line in tuple(getattr(tail, "lines", ()) or ())[-cap:]:
                text.append(Text(f"  {line}", style=""))
                text.append("\n")
    return text


__all__ = [
    "COMPACT_MAX_ITEMS",
    "FULL_TAIL_LINES",
    "STANDARD_MAX_ITEMS",
    "STANDARD_TAIL_LINES",
    "render_tool_run_block",
]
