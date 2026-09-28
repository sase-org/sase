"""Shared ToolRun state vocabulary (plan §3.2, epic sase-1bt).

One glyph + word + color mapping so the Agents-tab glance surfaces, the
Runs card, and the Admin Center Tools pane agree. Colors reuse the
finalizer palette where one exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sase.finalizers.view_vocabulary import (
    FAILURE_COLOR,
    REFUSED_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
)

#: Tools-deck accent: the running chip points at its detail card.
TOOL_RUN_ACCENT = "#87D7FF"

#: Single-cell ToolRun glyph (plan D1).
TOOL_RUN_GLYPH = "⚒"

#: Single-cell silent marker; always paired with the word "silent".
SILENT_GLYPH = "⚠"

#: Calm green for known-only rows: the known red, not yours.
KNOWN_ONLY_COLOR = "#87AF87"

#: Maximum row-chip width in cells; the label truncates with … first.
ROW_CHIP_MAX_CELLS = 20


@dataclass(frozen=True)
class ToolRunStateStyle:
    """Glyph, word, and color for one ToolRun state bucket."""

    glyph: str
    word: str
    color: str


#: §3.2 bucket styles keyed by the core verdict-bucket word, plus the
#: TUI-derived ``silent`` state (a live run past the silence threshold).
BUCKET_STYLES: dict[str, ToolRunStateStyle] = {
    "running": ToolRunStateStyle(
        glyph=TOOL_RUN_GLYPH, word="running", color=f"bold {TOOL_RUN_ACCENT}"
    ),
    "silent": ToolRunStateStyle(
        glyph=f"{TOOL_RUN_GLYPH}{SILENT_GLYPH}",
        word="silent",
        color=f"bold {FAILURE_COLOR}",
    ),
    "pass": ToolRunStateStyle(glyph="✓", word="pass", color=SUCCESS_COLOR),
    "new_failures": ToolRunStateStyle(glyph="✗", word="NEW", color=FAILURE_COLOR),
    "known_only": ToolRunStateStyle(
        glyph="≈", word="known only", color=KNOWN_ONLY_COLOR
    ),
    "undetermined": ToolRunStateStyle(glyph="?", word="UNKNOWN", color=WARNING_COLOR),
    "killed": ToolRunStateStyle(glyph="⊘", word="killed", color=REFUSED_COLOR),
    "stopped": ToolRunStateStyle(glyph="⊘", word="stopped", color="dim"),
    "lost": ToolRunStateStyle(glyph="⊘", word="lost", color=f"dim {FAILURE_COLOR}"),
}

#: Severity worst-first: used to pick one chip among several tools and for
#: session inheritance of settled verdicts. Live always outranks settled,
#: and silent outranks live (applied by the caller, not this order).
SEVERITY_ORDER: tuple[str, ...] = (
    "new_failures",
    "undetermined",
    "killed",
    "lost",
    "stopped",
    "known_only",
    "pass",
)


def style_for_bucket(bucket: str | None) -> ToolRunStateStyle:
    """Return the shared style for a §3.2 verdict *bucket*.

    Unknown buckets fall back to ``undetermined`` so a newer core never
    breaks an older reader's render path.
    """

    return BUCKET_STYLES.get(bucket or "", BUCKET_STYLES["undetermined"])


def severity_rank(bucket: str | None) -> int:
    """Return the severity rank of *bucket* (lower is more severe)."""

    try:
        return SEVERITY_ORDER.index(bucket or "")
    except ValueError:
        return SEVERITY_ORDER.index("undetermined")


def is_silent(last_activity_ts: float, now_ts: float, silent_after_s: int = 60) -> bool:
    """Return True when a live run has been quiet past the silent threshold."""

    return now_ts - last_activity_ts >= silent_after_s


def format_age(seconds: float) -> str:
    """Format a silent/elapsed age as ``<1m``, ``Nm``, ``Nh``, or ``Nd``."""

    if seconds < 60:
        return "<1m"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 72:
        return f"{hours}h"
    return f"{hours // 24}d"


def format_min_sec(total_seconds: float) -> str:
    """Format a duration as ``MmSSs`` (``9m00s``, ``1m02s``, ``4m12s``)."""

    total = max(0, int(total_seconds))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}m{seconds:02d}s"


def format_settled_ts(settled_ts: float) -> str:
    """Format a settle timestamp as an absolute local ``HH:MM``."""

    return datetime.fromtimestamp(settled_ts).strftime("%H:%M")


def _truncate_label(label: str, max_cells: int) -> str:
    """Truncate *label* with … so it fits *max_cells* cells."""

    if len(label) <= max_cells:
        return label
    if max_cells <= 1:
        return "…"
    return label[: max_cells - 1] + "…"


def row_chip_text(
    label: str,
    *,
    state: str = "running",
    stages_done: int = 0,
    stages_expected: int | None = None,
    in_flight: bool = True,
    stop_requested: bool = False,
    silent_age_s: float | None = None,
    elapsed_s: float = 0,
    extra_live: int = 0,
) -> str:
    """Build the live-only Agents-tab row chip text (§3.6).

    ``silent_age_s`` marks a silent run; otherwise progress shows ``k/n``
    when a reference run supplies ``stages_expected`` (and ``k <= n``),
    ``starting`` for ``created``, ``stopping`` on a stop request, and a
    minute age as the elapsed fallback. The position is ``stages_done + 1``
    while a stage is in flight, otherwise ``stages_done`` (§3.1).
    """

    if silent_age_s is not None:
        head = f"{TOOL_RUN_GLYPH}{SILENT_GLYPH} "
        tail = f" silent {format_age(silent_age_s)}"
    elif state == "created" and not stop_requested:
        head = f"{TOOL_RUN_GLYPH} "
        tail = " starting"
    elif stop_requested:
        head = f"{TOOL_RUN_GLYPH} "
        tail = " stopping"
    elif stages_expected is not None and stages_expected > 0:
        position = stages_done + 1 if in_flight else stages_done
        if position > stages_expected or position < 1:
            # Progress past the reference run falls back to elapsed (§3.1).
            head = f"{TOOL_RUN_GLYPH} "
            tail = f" {format_age(elapsed_s)}"
        else:
            head = f"{TOOL_RUN_GLYPH} "
            tail = f" {position}/{stages_expected}"
    else:
        head = f"{TOOL_RUN_GLYPH} "
        tail = f" {format_age(elapsed_s)}"
    if extra_live > 0:
        tail = f"{tail}+{extra_live}"
    width = ROW_CHIP_MAX_CELLS - len(head) - len(tail)
    short = _truncate_label(label, width) if width < len(label) else label
    text = f"{head}{short}{tail}"
    if len(text) <= ROW_CHIP_MAX_CELLS:
        return text
    return text[: ROW_CHIP_MAX_CELLS - 1] + "…"


def header_chip_text(
    label: str,
    bucket: str,
    *,
    stage: str | None = None,
    stages_done: int = 0,
    stages_expected: int | None = None,
    elapsed_s: float = 0,
    typical_ms: int | None = None,
    duration_ms: int | None = None,
    settled_ts: float | None = None,
    new: int = 0,
    known: int = 0,
    unknown: int = 0,
    untriaged: bool = False,
    terminal_cause: str | None = None,
    silent_age_s: float | None = None,
    extra_labels: int = 0,
) -> str:
    """Build the selection header chip text (§3.7) for one label's run."""

    suffix = f"+{extra_labels}" if extra_labels > 0 else ""
    if silent_age_s is not None:
        detail = f"{stage} · " if stage else ""
        return (
            f"{TOOL_RUN_GLYPH}{SILENT_GLYPH} {label} · {detail}"
            f"silent {format_age(silent_age_s)}{suffix}"
        )
    if bucket == "running":
        if (
            stages_expected is not None
            and stages_expected > 0
            and stages_done + 1 <= stages_expected
        ):
            progress = f"{stages_done + 1}/{stages_expected}"
        else:
            progress = format_age(elapsed_s)
        detail = f"{stage} {progress}" if stage else progress
        elapsed = format_min_sec(elapsed_s)
        if typical_ms is not None:
            return (
                f"{TOOL_RUN_GLYPH} {label} · {detail} · "
                f"{elapsed} / typ {format_min_sec(typical_ms / 1000)}{suffix}"
            )
        return f"{TOOL_RUN_GLYPH} {label} · {detail} · {elapsed}{suffix}"
    style = style_for_bucket(bucket)
    settled = f" · {format_settled_ts(settled_ts)}" if settled_ts else ""
    if bucket == "pass":
        duration = format_min_sec((duration_ms or 0) / 1000)
        return f"{TOOL_RUN_GLYPH} {label} {style.glyph} {duration}{settled}{suffix}"
    if bucket == "new_failures":
        duration = (
            f" · {format_min_sec(duration_ms / 1000)}"
            if duration_ms is not None
            else ""
        )
        return (
            f"{TOOL_RUN_GLYPH} {label} {style.glyph} {new} NEW · "
            f"{known} KNOWN{duration}{settled}{suffix}"
        )
    if bucket == "known_only":
        duration = (
            f" · {format_min_sec(duration_ms / 1000)}"
            if duration_ms is not None
            else ""
        )
        return (
            f"{TOOL_RUN_GLYPH} {label} {style.glyph} known only · "
            f"{known} KNOWN{duration}{settled}{suffix}"
        )
    if bucket == "undetermined":
        if untriaged:
            return f"{TOOL_RUN_GLYPH} {label} {style.glyph} untriaged{settled}{suffix}"
        duration = (
            f" · {format_min_sec(duration_ms / 1000)}"
            if duration_ms is not None
            else ""
        )
        return (
            f"{TOOL_RUN_GLYPH} {label} {style.glyph} {unknown} UNKNOWN"
            f"{duration}{settled}{suffix}"
        )
    if bucket in ("killed", "stopped", "lost"):
        if bucket == "killed":
            cause = terminal_cause or "signal"
            when = format_min_sec((duration_ms or 0) / 1000)
            word = (
                f"timed out at {when}"
                if cause == "timeout"
                else f"killed at {when} · {cause}"
            )
        elif bucket == "stopped":
            when = format_min_sec((duration_ms or 0) / 1000)
            word = f"stopped at {when}"
        else:
            cause = terminal_cause or ""
            word = f"lost · {cause}" if cause else "lost"
        return f"{TOOL_RUN_GLYPH} {label} {style.glyph} {word}{settled}{suffix}"
    return f"{TOOL_RUN_GLYPH} {label} {style.glyph} {style.word}{settled}{suffix}"


def switcher_runs_text(run_count: int) -> str:
    """Build the ``⚒N`` part of the Tools switcher segment (D8)."""

    return f"{TOOL_RUN_GLYPH}{max(0, run_count)}"


__all__ = [
    "BUCKET_STYLES",
    "KNOWN_ONLY_COLOR",
    "ROW_CHIP_MAX_CELLS",
    "SEVERITY_ORDER",
    "SILENT_GLYPH",
    "TOOL_RUN_ACCENT",
    "TOOL_RUN_GLYPH",
    "ToolRunStateStyle",
    "format_age",
    "format_min_sec",
    "format_settled_ts",
    "header_chip_text",
    "is_silent",
    "row_chip_text",
    "severity_rank",
    "style_for_bucket",
    "switcher_runs_text",
]
