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

from typing import Any, Literal

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


def _scrub_roles(styles: Any | None) -> dict[str, str]:
    """Return the concrete colour roles for the playhead scrubber."""
    roles = {
        "past": PAST_STYLE,
        "dim": DIM_STYLE,
        "uncommitted": UNCOMMITTED_STYLE,
        "delete": DELETED_STYLE,
        "insert": "green",
        "foreground": "",
        "now_bg": "",
        "now_fg": "",
    }
    if styles is None:
        return roles
    for key, attr in (
        ("past", "past"),
        ("uncommitted", "uncommitted"),
        ("delete", "delete"),
        ("insert", "insert"),
        ("foreground", "foreground"),
    ):
        try:
            value = getattr(styles, attr, None)
        except Exception:
            value = None
        if isinstance(value, str) and value:
            roles[key] = value
    try:
        now_bg = getattr(styles, "now_pill_bg", None)
        now_fg = getattr(styles, "now_pill_fg", None)
    except Exception:
        now_bg, now_fg = None, None
    if isinstance(now_bg, str) and now_bg:
        roles["now_bg"] = now_bg
    if isinstance(now_fg, str) and now_fg:
        roles["now_fg"] = now_fg
    return roles


def _bar_char(volume: int, peak: int) -> str:
    """Return the log-scaled bar cell for *volume* against *peak*."""
    if peak <= 0:
        return SPARKLINE_BLOCKS[0]
    import math

    ratio = math.log1p(max(0, int(volume))) / math.log1p(peak)
    return SPARKLINE_BLOCKS[min(int(round(ratio * 7)), 7)]


def render_scrubber(
    *,
    ordinals: list[int],
    volumes: list[int],
    hidden: list[bool],
    deleted: list[bool],
    shown_ordinal: int | None,
    view: str = "read",
    diff_base: int | None = None,
    diff_target: int | None = None,
    dirty: bool = False,
    tombstone: bool = False,
    now_matches_newest: bool = False,
    track_width: int = 60,
    endpoints: str = "full",
    styles: Any | None = None,
) -> Text:
    """Render the playhead scrubber: labelled ends around a version track.

    There is one slot per committed version, oldest to newest. Slots are
    two cells (bar plus gap) when twelve versions or fewer fit, otherwise
    one cell; longer histories bucket down into *track_width* cells (at
    most 60). Bar height is the log-scaled word volume. A hidden version
    is a dim ``·`` and a deleted version a ``✖`` in the deleted tone.

    The track reads like a video scrubber's watched portion: in the past
    the slots before the shown version use the past accent, the shown
    version is the reverse-video playhead, and later slots are dim. At a
    clean now every slot uses the normal foreground and the ``● now``
    endpoint is the playhead; a dirty now plays amber on ``◌ now``. In
    the diff view slots outside the compared range are dim, the base is
    bold in the delete tone, the slots between use the past accent, and
    the target is the playhead. ``0`` as a diff target means now (the
    endpoint is the playhead); ``0`` or ``None`` as the base means the
    range starts before the first slot.
    """
    from rich.cells import cell_len

    text = Text(no_wrap=True, overflow="crop")
    roles = _scrub_roles(styles)
    count = len(ordinals)
    if count == 0 or track_width <= 0:
        return text
    if len(volumes) < count:
        volumes = list(volumes) + [0] * (count - len(volumes))
    if len(hidden) < count:
        hidden = list(hidden) + [False] * (count - len(hidden))
    if len(deleted) < count:
        deleted = list(deleted) + [False] * (count - len(deleted))
    peak = max((max(0, int(volume)) for volume in volumes[:count]), default=0)

    two_cell = count <= 12 and count * 2 - 1 <= max(int(track_width), 0)
    if two_cell:
        bounds: list[tuple[int, int]] = [(index, index + 1) for index in range(count)]
    else:
        cells = max(min(count, max(int(track_width), 0)), 1)
        bounds = []
        for cell in range(cells):
            start = (cell * count) // cells
            end = max(((cell + 1) * count) // cells, start + 1)
            bounds.append((start, end))
    oldest = ordinals[0]

    def cell_has(cell: int, ordinal: int | None) -> bool:
        if ordinal is None or ordinal <= 0:
            return False
        start, end = bounds[cell]
        return any(ordinals[index] == ordinal for index in range(start, end))

    shown_cell: int | None = None
    if shown_ordinal is not None:
        for cell in range(len(bounds)):
            if cell_has(cell, shown_ordinal):
                shown_cell = cell
                break
    base_cell: int | None = None
    target_cell: int | None = None
    is_diff = str(view or "read") == "diff" and (
        diff_base is not None or diff_target is not None
    )
    if is_diff:
        for cell in range(len(bounds)):
            if base_cell is None and cell_has(cell, diff_base):
                base_cell = cell
            if cell_has(cell, diff_target):
                target_cell = cell
    past = roles["past"]
    dim = roles["dim"]
    uncommitted = roles["uncommitted"]
    delete = roles["delete"]
    if roles["now_bg"] and roles["now_fg"]:
        now_playhead = f"bold {roles['now_fg']} on {roles['now_bg']}"
    else:
        now_playhead = "reverse"
    past_playhead = f"bold {past} reverse"

    def slot_glyph(cell: int) -> str:
        start, end = bounds[cell]
        if all(hidden[index] for index in range(start, end)):
            return HIDDEN_CELL
        bucket_volumes = [max(0, int(volumes[index])) for index in range(start, end)]
        bucket = max(range(len(bucket_volumes)), key=lambda i: bucket_volumes[i])
        if deleted[start + bucket]:
            return "✖"
        return _bar_char(bucket_volumes[bucket], peak)

    def slot_style(cell: int, glyph: str) -> str:
        if glyph == HIDDEN_CELL:
            return dim
        if is_diff:
            if target_cell is not None and cell == target_cell:
                return past_playhead
            if base_cell is not None and cell == base_cell:
                return f"bold {delete}"
            if target_cell is None and diff_target != 0:
                return dim
            low = base_cell if base_cell is not None else -1
            high = len(bounds) if diff_target == 0 else (target_cell or -1)
            if low < cell < high:
                return past
            return dim
        if tombstone:
            if shown_cell is not None and cell == shown_cell:
                return f"bold {delete} reverse"
            if shown_cell is not None and cell < shown_cell:
                return past
            return dim
        if shown_ordinal is not None:
            if cell == shown_cell:
                return past_playhead
            if shown_cell is not None and cell < shown_cell:
                return past
            return dim
        # At now every slot uses the normal foreground, except the
        # newest slot on a now ≡ vN subject, which joins the ``● now``
        # endpoint as the playhead. Deleted versions keep their mark.
        if glyph == "✖":
            return delete
        if now_matches_newest and cell == len(bounds) - 1:
            return now_playhead
        return ""

    track = Text(no_wrap=True, overflow="crop")
    for cell in range(len(bounds)):
        glyph = slot_glyph(cell)
        style = slot_style(cell, glyph)
        if style:
            track.append(glyph, style=style)
        else:
            track.append(glyph)
        if two_cell and cell < len(bounds) - 1:
            track.append(" ")
    if dirty:
        end_label = "◌ now"
        end_style = f"bold {uncommitted} reverse"
    elif tombstone:
        end_label = "✖ deleted"
        end_style = delete
    elif (shown_ordinal is None and not is_diff) or (is_diff and diff_target == 0):
        end_label = "● now"
        end_style = now_playhead
    else:
        end_label = "● now"
        end_style = dim
    mode = str(endpoints or "full")
    if mode == "none":
        text.append_text(track)
        return text
    if mode == "short":
        text.append_text(track)
        text.append(" ")
        text.append(end_label.split(" ")[0], style=end_style)
        return text
    text.append(f"v{oldest}", style=dim)
    text.append(" ")
    text.append_text(track)
    text.append(" ")
    text.append(end_label, style=end_style)
    return text


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
    "render_scrubber",
    "render_sparkline",
    "short_display_for_subject_id",
]
