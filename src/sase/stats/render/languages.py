"""Language identity and renderers for the Projects language breakdown."""

from __future__ import annotations

from sase.stats.render.languages_card import (
    breakdown_widths,
    make_breakdown_grid,
    render_language_card_block,
)
from sase.stats.render.languages_identity import (
    language_cell_text,
    language_label,
    language_share_label,
    top_language,
)
from sase.stats.render.languages_table import (
    language_markdown_rows,
    render_language_table,
)

__all__ = [
    "breakdown_widths",
    "language_cell_text",
    "language_label",
    "language_markdown_rows",
    "language_share_label",
    "make_breakdown_grid",
    "render_language_card_block",
    "render_language_table",
    "top_language",
]
