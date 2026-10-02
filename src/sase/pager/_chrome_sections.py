"""Section chrome for the pager: kind glyphs, accents, and transition rules.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.
"""

from __future__ import annotations

from collections.abc import Mapping

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, ARTIFACTS_ICONS
from sase.pager._trail_chrome_model import MUTED_STYLE
from sase.pager._trail_chrome_text import append_path_label
from sase.pager.document import PagerSection

#: Pager sections carry the *singular* kind vocabulary their adapters chose
#: (``"bead"``, ``"file"``) rather than the Artifacts tab's plural pane keys.
#: Translate through this table instead of inventing a second glyph/accent
#: registry, per the epic plan's "one glyph, one accent table" seam with the
#: ``sase-ug`` link rail.
_SECTION_KIND_TAB: Mapping[str, str] = {
    "bead": "beads",
    "file": "files",
    "agent": "agents",
}
_DEFAULT_SECTION_ICON = "◆"
_DEFAULT_SECTION_ACCENT = "#AFAFAF"

_DIVIDER_CHAR = "━"


def section_icon(kind: str) -> str:
    """Return the glyph for a pager section's ``kind``."""
    tab = _SECTION_KIND_TAB.get(kind)
    if tab is None:
        return _DEFAULT_SECTION_ICON
    return ARTIFACTS_ICONS.get(tab, _DEFAULT_SECTION_ICON)


def section_accent(kind: str) -> str:
    """Return the public accent color for a pager section ``kind``."""
    tab = _SECTION_KIND_TAB.get(kind)
    if tab is None:
        return _DEFAULT_SECTION_ACCENT
    return ARTIFACTS_ACCENTS.get(tab, _DEFAULT_SECTION_ACCENT)


def section_rule(
    section: PagerSection,
    *,
    index: int,
    total: int,
    width: int,
) -> Text:
    """Build one section-transition rule, `_show_divider`'s shape plus a
    kind glyph and accent (design doc section D5)."""
    glyph = section_icon(section.kind)
    accent = section_accent(section.kind)
    marker = f"{index}/{total}"

    line = Text()
    line.append(f"{_DIVIDER_CHAR}{_DIVIDER_CHAR} ", style="dim")
    line.append(marker, style=f"bold {accent}")
    line.append(f" {_DIVIDER_CHAR} ", style="dim")
    line.append(f"{glyph} ", style=accent)
    append_path_label(line, section.title, style=accent, root_style=MUTED_STYLE)
    prefix_width = cell_len(line.plain) + 1
    fill = _DIVIDER_CHAR * max(width - prefix_width, 0)
    line.append(f" {fill}", style="dim")
    return line


__all__ = [
    "section_accent",
    "section_icon",
    "section_rule",
]
