"""Shared glyph and style vocabulary for clan-wave list chrome."""

from ._agent_list_styling import TREE_DEPTH_COLORS

WAVE_NUMBER_COLOR = TREE_DEPTH_COLORS[0]
WAVE_NUMBER_OPEN_STYLE = f"bold {WAVE_NUMBER_COLOR}"
WAVE_NUMBER_DONE_STYLE = f"dim {WAVE_NUMBER_COLOR}"
WAVE_UNRESOLVED_STYLE = "bold #FFAF00"
WAVE_BRACE_GLYPHS = ("╭", "├", "╰", "─")
WAVE_LANE_GLYPH = "│"
WAVE_GUTTER_WIDTH = 5


def wave_connector_style(*, is_selected: bool) -> str:
    """Return the depth-one connector style used by a selected row."""
    return f"bold {WAVE_NUMBER_COLOR}" if is_selected else WAVE_NUMBER_COLOR


__all__ = [
    "WAVE_BRACE_GLYPHS",
    "WAVE_GUTTER_WIDTH",
    "WAVE_LANE_GLYPH",
    "WAVE_NUMBER_COLOR",
    "WAVE_NUMBER_DONE_STYLE",
    "WAVE_NUMBER_OPEN_STYLE",
    "WAVE_UNRESOLVED_STYLE",
    "wave_connector_style",
]
