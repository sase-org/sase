"""Go-to-line strip rendering for the pager.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.pager._chrome_sections import section_icon

_GOTO_SIGIL_STYLE = "bold #FFD75F"
_GOTO_DIGIT_STYLE = "white"
_GOTO_INVALID_STYLE = "bold #FF5F5F"
_GOTO_RANGE_STYLE = "dim"
_GOTO_INVALID_RANGE_STYLE = "dim #FF5F5F"
_ELLIPSIS = "…"


def goto_command_line(
    *,
    digits: str,
    line_count: int,
    section_title: str | None,
    section_kind: str | None,
    width: int,
) -> Text:
    """Render the one-line ``:`` go-to-line strip.

    The section glyph+title (multi-section documents only) truncates before
    the valid-range readout disappears.
    """
    invalid = _goto_digits_are_invalid(digits, line_count)
    left = Text(no_wrap=True, overflow="crop")
    left.append(":", style=_GOTO_SIGIL_STYLE)
    left.append(digits, style=_GOTO_INVALID_STYLE if invalid else _GOTO_DIGIT_STYLE)
    left.append(" ", style="reverse")

    range_text = f"out of range · 1-{line_count}" if invalid else f"line 1-{line_count}"
    range_style = _GOTO_INVALID_RANGE_STYLE if invalid else _GOTO_RANGE_STYLE
    context = None if invalid else _goto_section_context(section_title, section_kind)
    return _assemble_goto_line(
        left,
        range_text=range_text,
        range_style=range_style,
        context=context,
        width=max(width, 0),
    )


def _goto_digits_are_invalid(digits: str, line_count: int) -> bool:
    if not digits:
        return False
    value = int(digits)
    return value == 0 or value > line_count


def _goto_section_context(
    section_title: str | None,
    section_kind: str | None,
) -> tuple[str, str] | None:
    if section_title is None:
        return None
    return (section_icon(section_kind or ""), section_title)


def _assemble_goto_line(
    left: Text,
    *,
    range_text: str,
    range_style: str,
    context: tuple[str, str] | None,
    width: int,
) -> Text:
    right = _goto_right_side(
        range_text,
        range_style=range_style,
        context=context,
        available=max(0, width - cell_len(left.plain)),
    )
    content = Text(no_wrap=True, overflow="crop")
    content.append_text(left)
    if not right.plain:
        return content
    padding = width - cell_len(left.plain) - cell_len(right.plain)
    content.append(" " * max(2, padding))
    content.append_text(right)
    return content


def _goto_right_side(
    range_text: str,
    *,
    range_style: str,
    context: tuple[str, str] | None,
    available: int,
) -> Text:
    range_part = Text(range_text, style=range_style)
    range_width = cell_len(range_text)
    if context is None:
        return range_part
    glyph, title = context
    prefix_budget = available - range_width - 4  # two 2-cell gaps around the prefix
    prefix = _fit_section_prefix(glyph, title, prefix_budget)
    if prefix is None:
        return range_part
    right = Text(no_wrap=True, overflow="crop")
    right.append(prefix, style=_GOTO_RANGE_STYLE)
    right.append("  ")
    right.append_text(range_part)
    return right


def _fit_section_prefix(glyph: str, title: str, budget: int) -> str | None:
    """Return ``glyph title`` fitted to *budget*, or ``None`` to drop it."""
    if budget <= 0:
        return None
    full = f"{glyph} {title}"
    if cell_len(full) <= budget:
        return full
    glyph_prefix = f"{glyph} "
    title_budget = budget - cell_len(glyph_prefix)
    if title_budget < 2:
        return None
    return glyph_prefix + _truncate_to_cells(title, title_budget)


def _truncate_to_cells(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    if cell_len(text) <= budget:
        return text
    if budget == 1:
        return _ELLIPSIS
    target = budget - cell_len(_ELLIPSIS)
    if target <= 0:
        return _ELLIPSIS
    kept: list[str] = []
    used = 0
    for character in text:
        width = cell_len(character)
        if used + width > target:
            break
        kept.append(character)
        used += width
    return "".join(kept) + _ELLIPSIS


__all__ = [
    "goto_command_line",
]
