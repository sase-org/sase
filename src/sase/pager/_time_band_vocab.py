"""Vocabulary, sparkline, and budget primitives for the pager time band.

Holds the ``#pager-time`` constants, the per-class glyph and hidden-class
tables, and the pure helpers that need no timeline model: relative ages,
subject display names, the log-scaled sparkline, and the trail/time row
budget. The timeline model lives in
:mod:`sase.pager._time_band_model` and row rendering in
:mod:`sase.pager._time_band_render`; :mod:`sase.pager._time_band`
re-exports the public entry points.

Glyphmirror note: the per-class glyphs intentionally mirror
``sase.memory.history.vocabulary.CLASS_GLYPHS`` so pager core keeps its
no-memory-imports seam (the pager must work before any memory provider
is discovered). ``tests/pager/test_time_band.py`` asserts the two tables
stay identical.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text

#: Bar heights for the log-scaled per-version word volume (one cell each).
SPARKLINE_BLOCKS = "▁▂▃▄▅▆▇█"

#: Cell drawn for hidden-by-default versions inside the sparkline.
HIDDEN_CELL = "·"

#: Style roles for band chrome. The past accent stays violet, never amber:
#: amber already means uncommitted or unpublished (matches ``_chrome.py``).
PAST_STYLE = "#9d7cd8"
UNCOMMITTED_STYLE = "yellow"
DELETED_STYLE = "red"
DIM_STYLE = "dim"
BAND_LABEL_STYLE = "bold black on #FFD75F"

#: Classes hidden unless ``-a/--all`` is passed. Mirrors
#: ``sase.memory.history.vocabulary.HIDDEN_CLASSES``.
HIDDEN_CLASSES: frozenset[str] = frozenset(("moved", "reflow", "whitespace"))

#: Glyph per core version class. Mirrors
#: ``sase.memory.history.vocabulary.CLASS_GLYPHS``.
CLASS_GLYPHS: dict[str, str] = {
    "created": "✚",
    "authored": "◆",
    "promoted": "⇧",
    "demoted": "⇩",
    "frontmatter": "▣",
    "rendered": "⟳",
    "regenerated": "⟳",
    "config": "⚙",
    "regen_only": "⚙",
    "reflow": "≈",
    "whitespace": "≈",
    "moved": "↦",
    "deleted": "✖",
    "uncommitted": "◌",
    "staged": "◌",
    "unclassified": "?",
}

#: Compact chip text for the aliased/diverged instruction states.
ALIAS_SEPARATOR = "≡"
DIVERGED_CHIP = "⚠ diverged"

TimeState = Literal["hidden", "now", "past"]


def is_hidden_class(class_name: str) -> bool:
    """Return whether a class is hidden unless ``-a/--all`` is passed."""
    return class_name in HIDDEN_CLASSES


def format_age(now_epoch: int, then_epoch: int) -> str:
    """Return a compact relative age (``3d``, ``8d``, ``5mo``).

    Mirrors ``sase.memory.history.render_text.format_age`` for pager-core
    use without importing memory modules.
    """
    delta = max(0, now_epoch - then_epoch)
    if delta < 60:
        return f"{delta}s"
    if delta < 3600:
        return f"{delta // 60}m"
    if delta < 86400:
        return f"{delta // 3600}h"
    if delta < 30 * 86400:
        return f"{delta // 86400}d"
    if delta < 365 * 86400:
        return f"{delta // (30 * 86400)}mo"
    return f"{delta // (365 * 86400)}y"


def short_display_for_subject_id(subject_id: str) -> str:
    """Return a compact display name for a subject id.

    Mirrors ``sase.memory.history.render_text.short_display_for_subject_id``
    so cause-row sources read exactly like the CLI renders them.
    """
    kind, _, rest = subject_id.partition(":")
    name = rest.split("/", 1)[1] if "/" in rest else rest
    if kind == "strand":
        return name.replace("/", ":")
    if kind == "instructions":
        if name in (".", ""):
            return "AGENTS.md"
        return f"{name}/AGENTS.md"
    if kind in ("web", "asset"):
        return name
    return name


def render_sparkline(
    volumes: list[int],
    classes: list[str],
    current: int | None,
    width: int,
) -> Text:
    """Render one sparkline cell per version, bucketing down to *width*.

    Bar height is the log-scaled word volume. Promotions and demotions use
    the past accent, deletions the error colour, regenerations dim, and
    hidden versions a dim dot. The current version's cell is drawn in the
    past accent with reverse video.
    """
    text = Text(no_wrap=True, overflow="crop")
    width = max(0, int(width))
    count = min(len(volumes), len(classes))
    if width == 0 or count == 0:
        return text
    cells = min(count, width)
    peak = max((max(0, int(volume)) for volume in volumes[:count]), default=0)
    for cell in range(cells):
        start = (cell * count) // cells
        end = max(((cell + 1) * count) // cells, start + 1)
        bucket_volumes = [max(0, int(volumes[index])) for index in range(start, end)]
        bucket_classes = [classes[index] for index in range(start, end)]
        bucket = max(range(len(bucket_volumes)), key=lambda i: bucket_volumes[i])
        volume = bucket_volumes[bucket]
        class_name = bucket_classes[bucket]
        is_current = (
            current is not None and start <= current < end and cells == count
        ) or (
            current is not None and cells < count and (current * cells) // count == cell
        )
        if all(is_hidden_class(name) for name in bucket_classes):
            text.append(HIDDEN_CELL, style=DIM_STYLE)
            continue
        if peak <= 0:
            char = SPARKLINE_BLOCKS[0]
        else:
            import math

            ratio = math.log1p(volume) / math.log1p(peak)
            char = SPARKLINE_BLOCKS[min(int(round(ratio * 7)), 7)]
        style = _spark_style(class_name, is_current=is_current)
        text.append(char, style=style)
    return text


def _spark_style(class_name: str, *, is_current: bool) -> str:
    """Return the sparkline cell style for one version class."""
    if is_current:
        return f"{PAST_STYLE} reverse"
    if class_name == "deleted":
        return DELETED_STYLE
    if class_name in ("promoted", "demoted"):
        return PAST_STYLE
    if class_name in ("rendered", "regenerated", "regen_only", "config"):
        return DIM_STYLE
    return ""


def chrome_row_budget(
    height: int,
    trail_visible: bool,
    time_state: TimeState | str | None,
) -> tuple[int, int]:
    """Decide row counts for the trail band and the time band together.

    Returns ``(trail_rows, time_rows)``. The past band drops its time row
    below about 30 rows of height, or when the trail band is visible below
    about 40; at 12 rows or fewer the band folds into the subject chip.
    This replaces the trail band's standalone height rule so the two bands
    degrade as one unit.
    """
    screen_height = max(int(height), 1)
    trail_rows = 0
    if trail_visible:
        trail_rows = 1 if screen_height <= 12 else 2
    state = str(time_state or "hidden")
    if state in ("hidden", "folded") or screen_height <= 12:
        return (trail_rows, 0)
    if state == "now":
        return (trail_rows, 1)
    if screen_height < 30 or (trail_visible and screen_height < 40):
        return (trail_rows, 1)
    return (trail_rows, 2)


#: Honest states with no usable history: the band collapses to one row.
NO_HISTORY_HONEST = frozenset({"untracked", "ignored", "no_vcs", "unavailable"})


__all__ = [
    "ALIAS_SEPARATOR",
    "BAND_LABEL_STYLE",
    "CLASS_GLYPHS",
    "DELETED_STYLE",
    "DIM_STYLE",
    "DIVERGED_CHIP",
    "HIDDEN_CELL",
    "HIDDEN_CLASSES",
    "NO_HISTORY_HONEST",
    "PAST_STYLE",
    "SPARKLINE_BLOCKS",
    "TimeState",
    "UNCOMMITTED_STYLE",
    "chrome_row_budget",
    "format_age",
    "is_hidden_class",
    "render_sparkline",
    "short_display_for_subject_id",
]
