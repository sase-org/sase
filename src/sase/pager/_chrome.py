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
) -> Text:
    """Build the sticky subject line: title left, position right.

    ``section_index``/``section_total`` are only shown once a document has
    more than one section — a single-section document's own index is not
    information, per the beauty rule that absence costs nothing.
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
    right = Text(" · ".join(right_parts), style="dim")

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
) -> Text:
    """Build the availability-driven footer legend.

    Only verbs that would sometimes do nothing are worth a row (the ACE
    footer convention, matched here): plain scrolling (``j``/``k``/``g``/``G``
    /``ctrl+d``/``ctrl+u``) is always available so it lives in ``?`` only.
    """
    verbs: list[tuple[str, str]] = []
    action_key = {"copy": "y", "edit": "E"}.get(pending_action)
    if action_key is not None:
        verbs.append((f"{action_key}{pending_prefix}…", pending_action))
    elif pending_prefix:
        verbs.append((f"{pending_prefix}…", "link"))
    elif label_count:
        verbs.append(("0-9a-z", "follow"))
        verbs.append(("y", "copy"))
        verbs.append(("E", "edit"))
    if section_total > 1:
        verbs.append(("^N/^P", "entity"))
    verbs.append(("/", "search"))
    verbs.append(("?", "keys"))
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
    "section_rule",
    "subject_line",
]
