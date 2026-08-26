"""Rich rendering helpers for notification section headers."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from .notification_sections import NotificationSection

_RULE_CELLS = 32


def render_notification_section_spacer() -> Text:
    """Render the disabled blank row between adjacent sections."""
    return Text("", no_wrap=True)


def render_notification_section_header(
    section: NotificationSection,
    count: int,
) -> Text:
    """Render one disabled notification section header."""
    text = Text(no_wrap=True, overflow="ellipsis")
    accent = f"bold {section.color}"
    text.append("▎", style=accent)
    text.append(section.glyph, style=accent)
    text.append(" ")
    label = section.label.upper()
    text.append(label, style=accent)
    used_cells = cell_len(f"▎{section.glyph} {label} ")
    rule_cells = _RULE_CELLS - used_cells
    if rule_cells > 0:
        text.append("─" * rule_cells, style=accent)
    else:
        text.append(" ", style=accent)
    text.append(f"  {count}", style="dim")
    return text


__all__ = [
    "render_notification_section_header",
    "render_notification_section_spacer",
]
