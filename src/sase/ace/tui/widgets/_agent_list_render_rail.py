"""Public facade for the Agents-tab node-rail vocabulary.

Implementation lives in sibling ``_agent_list_render_rail_*`` modules;
this file re-exports the names that callers and tests historically import
from ``_agent_list_render_rail``. Only public names cross module
boundaries here.
"""

from __future__ import annotations

from ._agent_list_render_rail_cells import (
    rail_agent_cells,
    rail_banner_cells,
    row_kind_glyph,
)
from ._agent_list_render_rail_chrome import (
    rail_overflow_subtitle,
    rail_panel_title,
    rail_tooltip_text,
)
from ._agent_list_render_rail_vocab import (
    NODE_RAIL_WIDTH,
    RAIL_BUCKET_GLYPHS,
    RAIL_COLLAPSED_MARK_DIM_STYLE,
    RAIL_COLLAPSED_MARK_STYLE,
    RAIL_CONTENT_CELLS,
    RAIL_COUNT_CAP,
    RAIL_DONE_READ_STYLE,
    RAIL_FAILED_STYLE,
    RAIL_FOLD_GLYPH,
    RAIL_GATE_GLYPH,
    RAIL_HINT_STYLE,
    RAIL_LEGEND,
    RAIL_MARKED_PIP,
    RAIL_MARKED_PIP_STYLE,
    RAIL_MAX_DEPTH,
    RAIL_MONITOR_GLYPH,
    RAIL_NEEDS_YOU_STYLE,
    RAIL_PATCH_GLYPH,
    RAIL_STEP_GLYPH,
    RAIL_TITLE_CELLS,
    RAIL_UNREAD_PIP,
    RAIL_UNREAD_STYLE,
    RAIL_WORKFLOW_GLYPH,
    gate_glyph_style,
    monitor_glyph_style,
)

__all__ = [
    "NODE_RAIL_WIDTH",
    "RAIL_BUCKET_GLYPHS",
    "RAIL_COLLAPSED_MARK_DIM_STYLE",
    "RAIL_COLLAPSED_MARK_STYLE",
    "RAIL_CONTENT_CELLS",
    "RAIL_COUNT_CAP",
    "RAIL_DONE_READ_STYLE",
    "RAIL_FAILED_STYLE",
    "RAIL_FOLD_GLYPH",
    "RAIL_GATE_GLYPH",
    "RAIL_HINT_STYLE",
    "RAIL_LEGEND",
    "RAIL_MARKED_PIP",
    "RAIL_MARKED_PIP_STYLE",
    "RAIL_MAX_DEPTH",
    "RAIL_MONITOR_GLYPH",
    "RAIL_NEEDS_YOU_STYLE",
    "RAIL_PATCH_GLYPH",
    "RAIL_STEP_GLYPH",
    "RAIL_TITLE_CELLS",
    "RAIL_UNREAD_PIP",
    "RAIL_UNREAD_STYLE",
    "RAIL_WORKFLOW_GLYPH",
    "gate_glyph_style",
    "monitor_glyph_style",
    "rail_agent_cells",
    "rail_banner_cells",
    "rail_overflow_subtitle",
    "rail_panel_title",
    "rail_tooltip_text",
    "row_kind_glyph",
]
