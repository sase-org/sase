"""Content-aware geometry for the update failure report modal.

Pure helpers with no Textual imports so sizing stays unit-testable.

Mirrors ``UpdateFailureModal > #update-failure-container`` in ``styles.tcss``.
The TCSS block is the pre-mount fallback (compact 90-column width, automatic
height); the constants below must agree with it.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

# Preferred compact width for ordinary reports, clamped to the terminal.
PREFERRED_MIN_WIDTH = 90
# Explicit tab expansion shared by measurement and rendering.
TAB_SIZE = 8

# Maximum outer rectangle leaves a balanced gutter: two columns each side,
# one row above and below, matching the preview panel convention.
MAX_MARGIN_COLS = 2
MAX_MARGIN_ROWS = 1

# Cramped terminals use the full rectangle and drop optional spacing.
CRAMPED_WIDTH_BELOW = 60
CRAMPED_HEIGHT_BELOW = 16

# Horizontal chrome: container border (2) + container padding (2) + stable
# scrollbar gutter (1). The gutter is always reserved so showing the
# scrollbar never shifts the report.
CONTAINER_BORDER_COLS = 2
CONTAINER_PADDING_COLS = 2
SCROLLBAR_GUTTER_COLS = 1
CHROME_COLS = CONTAINER_BORDER_COLS + CONTAINER_PADDING_COLS + SCROLLBAR_GUTTER_COLS

# Vertical chrome pieces. Inter-section gap and footer margin are optional
# spacing dropped on cramped terminals.
CONTAINER_BORDER_ROWS = 2
SECTION_GAP_ROWS = 1
FOOTER_MARGIN_ROWS = 1

SEPARATOR_TEXT = "── last output ──"
PLACEHOLDER_TEXT = "No output was captured."

FOOTER_FULL_GROUPS = ("u open Update", "d dismiss", "y copy", "q/Esc close")
FOOTER_SHORT_GROUPS = ("u Update", "d dismiss", "y copy", "q close")
FOOTER_SEPARATOR = " · "
SCROLL_HINT_TEXT = "Ctrl+u/d scroll · g/G top/bottom"


@dataclass(frozen=True)
class UpdateFailureGeometry:
    """Outer container size plus footer/scroll decisions."""

    width: int
    height: int
    inner_width: int
    cramped: bool
    needs_scroll: bool
    show_scroll_hint: bool
    footer_lines: tuple[str, ...]
    hint_lines: tuple[str, ...]


def _is_cramped(screen_w: int, screen_h: int) -> bool:
    """Return whether the terminal gets the full rectangle fallback."""
    return screen_w < CRAMPED_WIDTH_BELOW or screen_h < CRAMPED_HEIGHT_BELOW


def _max_outer_size(screen_w: int, screen_h: int) -> tuple[int, int]:
    """Return the largest outer container size for the screen."""
    if screen_w <= 0 or screen_h <= 0:
        return (max(1, screen_w), max(1, screen_h))
    if _is_cramped(screen_w, screen_h):
        return (max(1, screen_w), max(1, screen_h))
    return (
        max(1, screen_w - 2 * MAX_MARGIN_COLS),
        max(1, screen_h - 2 * MAX_MARGIN_ROWS),
    )


def expand_tabs(text: str, *, tab_size: int = TAB_SIZE) -> str:
    """Expand tabs the same way for measurement and rendering."""
    return text.expandtabs(tab_size)


def _logical_lines(text: str, *, tab_size: int = TAB_SIZE) -> list[str]:
    """Split expanded text into logical lines, ignoring a trailing newline."""
    expanded = expand_tabs(text, tab_size=tab_size)
    lines = expanded.split("\n")
    if expanded.endswith("\n"):
        lines = lines[:-1]
    if not lines:
        return [""]
    return lines


def _max_cell_width(lines: list[str]) -> int:
    """Return the widest display-cell width across logical lines."""
    width = 0
    for line in lines:
        w = cell_len(line)
        if w > width:
            width = w
    return width


def _content_cell_width(text: str) -> int:
    """Return the widest displayed logical line in *text*."""
    return _max_cell_width(_logical_lines(text))


def _count_wrapped_rows(text: str, inner_width: int) -> int:
    """Return Rich wrapped rows for literal *text* at *inner_width*.

    Uses Rich measurement (not character-count division) so wide characters,
    combining marks, and long tokens agree with rendering. Markup-like text
    stays literal because it is measured as plain :class:`Text`.
    """
    width = max(1, inner_width)
    console = Console(width=width, force_terminal=True)
    total = 0
    for line in _logical_lines(text):
        wrapped = Text(line).wrap(console, width, overflow="fold", tab_size=TAB_SIZE)
        total += max(1, len(wrapped))
    return max(1, total)


def _footer_groups_for_width(inner_width: int) -> tuple[str, ...]:
    """Return full or shortened action groups that fit *inner_width*."""
    full = FOOTER_SEPARATOR.join(FOOTER_FULL_GROUPS)
    if cell_len(full) <= max(1, inner_width):
        return FOOTER_FULL_GROUPS
    return FOOTER_SHORT_GROUPS


def _pack_footer_lines(groups: tuple[str, ...], inner_width: int) -> tuple[str, ...]:
    """Pack action groups into lines without breaking a group.

    Wraps between complete action groups so a key never separates from its
    label. Falls back to Rich folding only when a single group exceeds the
    available width.
    """
    width = max(1, inner_width)
    lines: list[str] = []
    current = ""
    for group in groups:
        candidate = group if not current else current + FOOTER_SEPARATOR + group
        if cell_len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        if cell_len(group) <= width:
            current = group
        else:
            console = Console(width=width, force_terminal=True)
            wrapped = Text(group).wrap(console, width, overflow="fold")
            for part in wrapped[:-1]:
                lines.append(part.plain)
            current = wrapped[-1].plain if wrapped else group
    if current:
        lines.append(current)
    return tuple(lines) if lines else ("",)


def _action_footer_lines(inner_width: int) -> tuple[str, ...]:
    """Return the responsive action-footer lines for *inner_width*."""
    return _pack_footer_lines(_footer_groups_for_width(inner_width), inner_width)


def _hint_lines(inner_width: int) -> tuple[str, ...]:
    """Return the scroll-hint lines, wrapped only if unavoidable."""
    width = max(1, inner_width)
    if cell_len(SCROLL_HINT_TEXT) <= width:
        return (SCROLL_HINT_TEXT,)
    console = Console(width=width, force_terminal=True)
    wrapped = Text(SCROLL_HINT_TEXT).wrap(console, width, overflow="fold")
    return tuple(part.plain for part in wrapped) if wrapped else (SCROLL_HINT_TEXT,)


def _required_outer_width(
    *,
    meta: str,
    headline: str,
    body: str,
    title: str,
    footer_text: str | None = None,
) -> int:
    """Return the outer width needed to show every line unwrapped."""
    widest = max(
        _content_cell_width(meta),
        _content_cell_width(headline),
        cell_len(expand_tabs(SEPARATOR_TEXT)),
        _content_cell_width(body),
    )
    footer_cells = (
        cell_len(expand_tabs(footer_text))
        if footer_text is not None
        else cell_len(FOOTER_SEPARATOR.join(FOOTER_FULL_GROUPS))
    )
    return max(widest + CHROME_COLS, cell_len(title) + 4, footer_cells + CHROME_COLS)


def compute_geometry(
    *,
    screen_w: int,
    screen_h: int,
    meta: str,
    headline: str,
    body: str,
    title: str,
) -> UpdateFailureGeometry | None:
    """Compute the adaptive outer rectangle and footer decisions.

    Returns ``None`` for transient zero dimensions so callers defer layout
    instead of computing negative sizes. The result is a pure function of its
    inputs: the same report and terminal always resolve the same way, with at
    most two deterministic footer passes and no visibility feedback loop.
    """
    if screen_w <= 0 or screen_h <= 0:
        return None
    cramped = _is_cramped(screen_w, screen_h)
    max_w, max_h = _max_outer_size(screen_w, screen_h)
    max_w = max(1, max_w)
    max_h = max(1, max_h)

    full_footer = FOOTER_SEPARATOR.join(FOOTER_FULL_GROUPS)
    needed = _required_outer_width(
        meta=meta, headline=headline, body=body, title=title, footer_text=full_footer
    )
    width = max(1, min(max(needed, PREFERRED_MIN_WIDTH), max_w, max(1, screen_w)))
    inner_width = max(1, width - CHROME_COLS)

    gap = 0 if cramped else SECTION_GAP_ROWS
    footer_margin = 0 if cramped else FOOTER_MARGIN_ROWS

    meta_rows = _count_wrapped_rows(meta, inner_width)
    headline_rows = _count_wrapped_rows(headline, inner_width)
    label_rows = _count_wrapped_rows(SEPARATOR_TEXT, inner_width)
    body_rows = _count_wrapped_rows(body, inner_width)
    content_rows = meta_rows + headline_rows + label_rows + body_rows + gap

    # First pass: action footer only.
    footer = _action_footer_lines(inner_width)
    chrome = CONTAINER_BORDER_ROWS + footer_margin + len(footer)
    if content_rows + chrome <= max_h:
        return UpdateFailureGeometry(
            width=width,
            height=max(1, content_rows + chrome),
            inner_width=inner_width,
            cramped=cramped,
            needs_scroll=False,
            show_scroll_hint=False,
            footer_lines=footer,
            hint_lines=(),
        )

    # Second pass: content overflows, reserve the scroll hint when it still
    # leaves room for the report viewport and the action footer.
    hint = _hint_lines(inner_width)
    chrome_with_hint = chrome + len(hint)
    viewport_with_hint = max_h - chrome_with_hint
    if viewport_with_hint >= 1:
        return UpdateFailureGeometry(
            width=width,
            height=max_h,
            inner_width=inner_width,
            cramped=cramped,
            needs_scroll=True,
            show_scroll_hint=True,
            footer_lines=footer,
            hint_lines=hint,
        )
    # Short heights omit the optional hint before sacrificing actions.
    return UpdateFailureGeometry(
        width=width,
        height=max_h,
        inner_width=inner_width,
        cramped=cramped,
        needs_scroll=True,
        show_scroll_hint=False,
        footer_lines=footer,
        hint_lines=(),
    )


__all__ = [
    "CHROME_COLS",
    "CRAMPED_HEIGHT_BELOW",
    "CRAMPED_WIDTH_BELOW",
    "FOOTER_FULL_GROUPS",
    "FOOTER_SHORT_GROUPS",
    "MAX_MARGIN_COLS",
    "MAX_MARGIN_ROWS",
    "PLACEHOLDER_TEXT",
    "PREFERRED_MIN_WIDTH",
    "SCROLL_HINT_TEXT",
    "SEPARATOR_TEXT",
    "TAB_SIZE",
    "UpdateFailureGeometry",
    "compute_geometry",
    "expand_tabs",
]
