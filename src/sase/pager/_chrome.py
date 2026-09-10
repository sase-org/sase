"""Pure rendering helpers for the pager's sticky chrome and footer.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.
"""

from __future__ import annotations

from collections.abc import Mapping

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, ARTIFACTS_ICONS
from sase.pager.document import PagerDocument, PagerSection

#: Pager sections carry the *singular* kind vocabulary their adapters chose
#: (``"bead"``, ``"file"``) rather than the Artifacts tab's plural pane keys.
#: Translate through this table instead of inventing a second glyph/accent
#: registry, per the epic plan's "one glyph, one accent table" seam with the
#: ``sase-ug`` link rail.
_SECTION_KIND_TAB: Mapping[str, str] = {
    "bead": "beads",
    "file": "files",
}
_DEFAULT_SECTION_ICON = "◆"
_DEFAULT_SECTION_ACCENT = "#AFAFAF"

_DIVIDER_CHAR = "━"


def _section_icon(kind: str) -> str:
    """Return the glyph for a pager section's ``kind``."""
    tab = _SECTION_KIND_TAB.get(kind)
    if tab is None:
        return _DEFAULT_SECTION_ICON
    return ARTIFACTS_ICONS.get(tab, _DEFAULT_SECTION_ICON)


def _section_accent(kind: str) -> str:
    """Return the accent color for a pager section's ``kind``."""
    tab = _SECTION_KIND_TAB.get(kind)
    if tab is None:
        return _DEFAULT_SECTION_ACCENT
    return ARTIFACTS_ACCENTS.get(tab, _DEFAULT_SECTION_ACCENT)


def section_accent(kind: str) -> str:
    """Return the public accent color for a pager section ``kind``."""
    return _section_accent(kind)


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
    return (_section_icon(section_kind or ""), section_title)


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


def _format_char_count(count: int) -> str:
    """Format a character count for the subject line's ``⌘`` readout."""
    if count < 1_000:
        return f"{count}c"
    if count < 1_000_000:
        return f"{count / 1_000:.1f}Kc"
    return f"{count / 1_000_000:.1f}Mc"


def subject_line(
    document: PagerDocument,
    current_section: PagerSection,
    *,
    section_index: int,
    section_total: int,
    scroll_percent: int,
    char_count: int,
    width: int,
    syntax_hint: str | None = None,
) -> Text:
    """Build the sticky subject line: title left, position right.

    ``section_index``/``section_total`` are only shown once a document has
    more than one section — a single-section document's own index is not
    information, per the beauty rule that absence costs nothing.

    ``syntax_hint`` is a short language alias (``"py"``, ``"md"``, ``"diff"``)
    shown only when syntax is actually enabled/prepared for the current
    section; it is the first thing dropped at a narrow width, before either
    the subject or the position information it sits beside.
    """
    glyph = _section_icon(current_section.kind)
    accent = _section_accent(current_section.kind)

    left = Text()
    left.append(f"{glyph} ", style=f"bold {accent}")
    left.append(document.title, style="bold")
    if section_total > 1 and current_section.title != document.title:
        left.append(" · ", style="dim")
        left.append(current_section.title)

    right_parts = []
    if section_total > 1:
        right_parts.append(f"{section_index}/{section_total}")
    right_parts.append(f"{scroll_percent}%")
    right_parts.append(f"⌘ {_format_char_count(char_count)}")
    right_str = " · ".join(right_parts)
    if syntax_hint:
        with_hint = " · ".join((*right_parts, syntax_hint))
        if cell_len(left.plain) + cell_len(with_hint) + 1 <= width:
            right_str = with_hint
    right = Text(right_str, style="dim")

    gap = max(width - cell_len(left.plain) - cell_len(right.plain), 1)
    line = Text()
    line.append_text(left)
    line.append(" " * gap)
    line.append_text(right)
    return line


def section_rule(
    section: PagerSection,
    *,
    index: int,
    total: int,
    width: int,
) -> Text:
    """Build one section-transition rule, `_show_divider`'s shape plus a
    kind glyph and accent (design doc section D5)."""
    glyph = _section_icon(section.kind)
    accent = _section_accent(section.kind)
    marker = f"{index}/{total}"
    label = f"{glyph} {section.title}"

    line = Text()
    line.append(f"{_DIVIDER_CHAR}{_DIVIDER_CHAR} ", style="dim")
    line.append(marker, style=f"bold {accent}")
    line.append(f" {_DIVIDER_CHAR} ", style="dim")
    line.append(label, style=accent)
    prefix_width = cell_len(line.plain) + 1
    fill = _DIVIDER_CHAR * max(width - prefix_width, 0)
    line.append(f" {fill}", style="dim")
    return line


def footer_legend(
    *,
    section_total: int,
    label_count: int = 0,
    pending_prefix: str = "",
    pending_action: str = "follow",
    trail_back_count: int = 0,
    trail_forward_count: int = 0,
    status: str | None = None,
) -> Text:
    """Build the availability-driven footer legend.

    Only verbs that would sometimes do nothing are worth a row (the ACE
    footer convention, matched here): plain scrolling (``j``/``k``/``g``/``G``
    /``ctrl+d``/``ctrl+u``) is always available so it lives in ``?`` only.
    """
    verbs: list[tuple[str, str]] = []
    if status is not None:
        verbs.append(("…", status))
    action_key = {"copy": "y", "edit": "E"}.get(pending_action)
    if action_key is not None:
        verbs.append((f"{action_key}{pending_prefix}…", pending_action))
    elif pending_prefix:
        verbs.append((f"{pending_prefix}…", "link"))
    elif label_count:
        verbs.append(("0-9a-z", "follow"))
        verbs.append(("y", "copy"))
        verbs.append(("E", "edit"))
    if trail_back_count:
        verbs.append(("⌫/^O", "back"))
    if trail_forward_count:
        verbs.append(("<tab>", "forward"))
    if section_total > 1:
        verbs.append(("^N/^P", "entity"))
    verbs.append(("/", "search"))
    help_label = "trail/keys" if trail_back_count or trail_forward_count else "keys"
    verbs.append(("?", help_label))
    verbs.append(("q", "close"))

    line = Text()
    for index, (key, label) in enumerate(verbs):
        if index > 0:
            line.append(" · ", style="dim")
        line.append(key, style="bold")
        line.append(f" {label}")
    return line


__all__ = [
    "footer_legend",
    "goto_command_line",
    "section_rule",
    "section_accent",
    "subject_line",
]
