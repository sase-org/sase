"""Pure Rich renderers for the capacity inspector modal."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from rich.cells import cell_len
from rich.text import Text

from sase.core.runner_slots import (
    CAPACITY_REPORT_STALE_AFTER_SECONDS,
    capacity_gauge_cells,
    format_capacity_duration,
)
from sase.ace.tui.widgets._usage_indicator_palette import (
    usage_percent_color,
    usage_rejected_style,
)


def format_capacity_number(value: float) -> str:
    """Format a capacity value without unnecessary decimal places."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def empty_charged_message(view: Any) -> str:
    """Return the Using-capacity empty state without treating unknown as free."""
    if view.admission_blocked:
        return "No known charged claims — free capacity is unknown"
    return f"Nothing holds capacity — all {format_capacity_number(view.limit)} units are free"


def middle_truncate(value: str, width: int) -> str:
    """Fit *value* to *width* terminal cells, keeping both ends visible."""
    if width <= 0:
        return ""
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"
    target = width - 1
    left_target = (target + 1) // 2
    right_target = target - left_target
    left = _take_cells(value, left_target)
    right = _take_cells(value, right_target, from_end=True)
    while cell_len(left) + cell_len(right) > target:
        if cell_len(left) >= cell_len(right) and left:
            left = left[:-1]
        elif right:
            right = right[1:]
        else:
            break
    return f"{left}…{right}"


def render_headline(
    view: Any | None, *, now: float, dark: bool, width: int | None = None
) -> Text:
    """Render the occupied/free headline and live freshness label."""
    if view is None:
        return Text("Waiting for the first authoritative report…", style="yellow")

    occupied = float(view.occupied)
    limit = float(view.limit)
    free = limit - occupied
    text = Text(
        f"{format_capacity_number(occupied)} / {format_capacity_number(limit)} units in use",
        style="bold",
    )
    if view.admission_blocked:
        free_text = "? free"
        free_style = usage_rejected_style(dark=dark)
    elif occupied > limit:
        free_text = f"{format_capacity_number(occupied - limit)} over"
        free_style = usage_rejected_style(dark=dark)
    else:
        free_text = f"{format_capacity_number(max(0.0, free))} free"
        free_percent = 0.0 if limit <= 0 else max(0.0, free / limit * 100.0)
        free_style = f"bold {usage_percent_color(free_percent, dark=dark)}"

    if not view.scan_current:
        freshness = "⟳ records changed · rescanning"
        freshness_style = "yellow"
    else:
        age = max(0, int(now - float(view.computed_at)))
        stale = age >= CAPACITY_REPORT_STALE_AFTER_SECONDS
        freshness = f"{'⟳ ' if stale else ''}updated {age}s ago"
        freshness_style = "yellow" if stale else "dim"

    summary_width = cell_len(text.plain) + cell_len(free_text) + cell_len(freshness) + 6
    separator = "\n" if width is not None and summary_width > width else "   "
    text.append(f"{separator}{free_text}", style=free_style)
    text.append(f"   {freshness}", style=freshness_style)
    return text


def render_gauge(
    view: Any | None,
    *,
    width: int,
    highlighted_owner: int | None,
    dark: bool,
    accent: str,
) -> Text:
    """Render gauge geometry from the core view without deriving capacity."""
    width = max(1, int(width))
    if view is None:
        return Text("░" * width, style="dim")
    cells = capacity_gauge_cells(view, width)
    if not cells:
        return Text("░" * width, style="dim")

    free_percent = 0.0 if view.limit <= 0 else max(0.0, view.free / view.limit * 100.0)
    fill_color = usage_percent_color(free_percent, dark=dark)

    def style_key(cell: Any) -> str:
        if cell.kind == "used":
            if highlighted_owner is not None and cell.owner == highlighted_owner:
                return f"bold {accent}"
            if view.admission_blocked:
                return usage_rejected_style(dark=dark)
            return f"bold {fill_color}"
        if cell.kind == "over":
            return usage_rejected_style(dark=dark)
        if cell.kind == "unknown":
            return usage_rejected_style(dark=dark)
        if cell.kind == "limit":
            return usage_rejected_style(dark=dark)
        return "dim"

    result = Text()
    run_style: str | None = None
    run_chars: list[str] = []
    for cell in cells:
        current_style = style_key(cell)
        if run_style is not None and current_style != run_style:
            result.append("".join(run_chars), style=run_style)
            run_chars.clear()
        run_style = current_style
        run_chars.append(cell.char)
    if run_chars:
        result.append("".join(run_chars), style=run_style or "dim")
    return result


def render_verdict(view: Any | None) -> Text:
    """Render the tone glyph, verdict title, and optional explanation."""
    if view is None or view.verdict is None:
        return Text("? Waiting for the first authoritative report…", style="yellow")
    verdict = view.verdict
    glyph, style = {
        "ok": ("✓", "bold green"),
        "tight": ("◔", "bold yellow"),
        "full": ("■", "bold #FF9D57"),
        "over": ("▲", "bold red"),
        "blocked": ("!", "bold red"),
        "unknown": ("?", "bold yellow"),
    }.get(verdict.tone, ("?", "bold yellow"))
    text = Text(f"{glyph} {verdict.title}", style=style)
    if verdict.detail:
        text.append(f"\n  {verdict.detail}", style="dim")
    return text


def render_facts(view: Any | None, *, width: int | None = None) -> Text:
    """Render limit provenance and running/charged facts."""
    if view is None:
        return Text(
            "The inspector never estimates capacity from visible rows.", style="dim"
        )
    info = view.limit_info
    parts = [f"limit {format_capacity_number(view.limit)}"]
    if info is not None and info.override_source is not None:
        age = max(0.0, float(info.override_age_seconds or 0.0))
        duration = _override_age(age)
        warning = " ⚠" if info.override_long_lived else ""
        config = (
            f" (config {format_capacity_number(info.configured)})"
            if info.configured is not None
            else ""
        )
        parts.append(f"{info.override_source} override for {duration}{warning}{config}")
    elif info is not None and info.configured is not None:
        parts.append(f"from config {format_capacity_number(info.configured)}")
    provenance = " · ".join(parts)
    if view.running_line is None:
        return Text(provenance, style="dim")
    at_zero = len(view.zero_weight) + len(view.riders)
    running = (
        f"{view.running_line.split(' running')[0]} running · "
        f"{len(view.charged)} charged · {at_zero} at 0"
    )
    combined = cell_len(provenance) + 5 + cell_len(running)
    if width is not None and combined > width:
        return Text(f"{provenance}\n{running}", style="dim")
    gap = (
        5 if width is None else max(5, width - cell_len(provenance) - cell_len(running))
    )
    return Text(f"{provenance}{' ' * gap}{running}", style="dim")


def render_section_header(label: str, summary: str, *, width: int) -> Text:
    """Render a section title, rule, and right-aligned count summary."""
    title = label.upper()
    gap = max(1, width - cell_len(title) - cell_len(summary) - 2)
    text = Text(title, style="bold #87D7FF")
    text.append(" " + "─" * gap + " ", style="dim")
    text.append(summary, style="dim")
    return text


def render_capacity_row(
    *,
    mark: str,
    name: str,
    kind: str = "",
    note: str = "",
    age: str = "",
    width: int,
    mark_style: str = "bold",
    name_style: str = "bold",
    note_style: str = "dim",
) -> Text:
    """Render one row at the wide or narrow column breakpoint."""
    width = max(20, int(width))
    wide = width >= 96
    mark_width = 4
    kind_width = 16 if wide else 0
    name_cap = 40 if wide else 28
    age_width = 8 if age else 0
    sep_after_mark = 1
    sep_after_name = 2
    sep_after_kind = 2 if wide else 0
    sep_before_age = 1 if age_width else 0
    overhead = (
        mark_width
        + sep_after_mark
        + sep_after_name
        + kind_width
        + sep_after_kind
        + sep_before_age
        + age_width
    )
    name_width = min(name_cap, max(8, width - overhead))
    note_width = max(0, width - overhead - name_width)
    name_text = _pad_cells(middle_truncate(name, name_width), name_width)
    note_text = _take_cells(note, note_width)
    kind_text = _pad_cells(_take_cells(kind, kind_width), kind_width)
    text = Text(_pad_cells(mark, mark_width), style=mark_style)
    text.append(" " + name_text, style=name_style)
    if wide:
        text.append("  " + kind_text, style="cyan")
    if note_width:
        text.append("  " + _pad_cells(note_text, note_width), style=note_style)
    if age_width:
        used = cell_len(text.plain)
        padding = max(sep_before_age, width - used - age_width)
        text.append(" " * padding + _pad_cells_left(age, age_width), style="dim")
    if cell_len(text.plain) > width:
        text = Text(_take_cells(text.plain, width), style=mark_style)
    return text


def render_footer() -> Text:
    """Render the keyboard footer with key names called out."""
    text = Text()
    parts = (
        ("j/k", " move · "),
        ("Enter", " jump / expand · "),
        ("h/l", " fold · "),
        ("y", " copy JSON · "),
        ("Esc", " close"),
    )
    for key, suffix in parts:
        text.append(key, style="bold")
        text.append(suffix, style="dim")
    return text


def render_detail(
    *,
    view: Any | None,
    target_kind: str | None,
    row: Any | None,
    group: Any | None,
    snapshot: Any | None = None,
) -> Text:
    """Render the three-line detail strip for a highlighted row."""
    if view is None or row is None and group is None:
        return Text(
            "Choose a row to see why it uses or waits for capacity.\n"
            "The report is authoritative; this panel does no I/O.\n",
            style="dim",
        )
    if target_kind in {"holder", "zero"} and row is not None:
        project = _project_label(
            str(getattr(row, "project_key", "") or ""), snapshot=snapshot
        )
        first = " · ".join(part for part in (row.name, row.kind, project) if part)
        weight = format_capacity_number(row.charged_weight)
        source = {
            "default": "default weight",
            "inherited": "weight inherited from its starter",
            "explicit": "explicit weight",
            "explicit_zero": "explicit zero weight — never charges",
            "invalid": "invalid weight",
        }.get(row.weight_source, row.weight_source.replace("_", " "))
        since = _absolute_since(row.since)
        running = format_capacity_duration(row.running_seconds)
        second = f"charges {weight} {'unit' if row.charged_weight == 1 else 'units'} ({source}) · running {running}"
        if since:
            second += f", since {since}"
        third = (
            "shared with " + ", ".join(row.rider_names)
            if row.rider_names
            else "claim held alone"
        )
        if row.authored_budget is not None:
            third += f" · launched with %queue(capacity={row.authored_budget})"
        third += " · Enter jumps to this agent"
        return _three_lines(first, second, third)
    if target_kind == "rider" and row is not None:
        project = _project_label(
            str(getattr(row, "project_key", "") or ""), snapshot=snapshot
        )
        first = " · ".join(part for part in (row.name, "rider", project) if part)
        second = f"rides the claim charged through {row.holder_name}"
        third = "Serial session members share one claim · Enter jumps to this agent"
        return _three_lines(first, second, third)
    if target_kind == "queued" and row is not None:
        project = _project_label(
            str(getattr(row, "project_key", "") or ""), snapshot=snapshot
        )
        first = " · ".join(part for part in (row.name, project) if part)
        waiting = format_capacity_duration(row.waiting_seconds)
        second = (
            f"queue #{row.queue_position} · requests "
            f"{format_capacity_number(row.requested_weight)} · waiting {waiting}"
        )
        blockers = "; ".join(row.blockers) if row.blockers else row.blocker
        return _three_lines(first, second, f"{blockers} · Enter jumps to this agent")
    if group is not None:
        first = str(getattr(group, "reason_label", "Capacity group"))
        second = str(getattr(group, "explanation", ""))
        if target_kind == "member" and row is not None:
            third = f"{row.name} · Enter jumps to this agent"
        elif group.reason_code in {"not_live", "done", "not_agent_record"}:
            third = "Enter or l expands · h folds this group"
        else:
            third = "Enter or l expands · h folds this group"
        return _three_lines(first, second, third)
    return Text("This row has no additional detail.", style="dim")


def _three_lines(first: str, second: str, third: str) -> Text:
    text = Text(first, style="bold")
    text.append("\n" + second, style="dim")
    text.append("\n" + third, style="dim")
    return text


def _project_label(project_key: str, snapshot: Any | None = None) -> str:
    if not project_key:
        return ""
    from sase.project_display_names import (
        project_display_name_for,
        project_display_snapshot_is_warm,
    )

    if snapshot is None and not project_display_snapshot_is_warm():
        return project_key
    return project_display_name_for(project_key, snapshot=snapshot)


def _absolute_since(stamp: object) -> str | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    raw = stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _override_age(seconds: float) -> str:
    days = int(seconds // 86400)
    if days:
        return f"{days}d"
    return format_capacity_duration(seconds)


def _take_cells(value: str, width: int, *, from_end: bool = False) -> str:
    if width <= 0:
        return ""
    result = ""
    iterable = reversed(value) if from_end else iter(value)
    for char in iterable:
        if cell_len(result) + cell_len(char) > width:
            break
        result = f"{char}{result}" if from_end else f"{result}{char}"
    return result


def _pad_cells(value: str, width: int) -> str:
    return value + " " * max(0, width - cell_len(value))


def _pad_cells_left(value: str, width: int) -> str:
    return " " * max(0, width - cell_len(value)) + value


__all__ = [
    "empty_charged_message",
    "format_capacity_number",
    "middle_truncate",
    "render_capacity_row",
    "render_detail",
    "render_facts",
    "render_footer",
    "render_gauge",
    "render_headline",
    "render_section_header",
    "render_verdict",
]
