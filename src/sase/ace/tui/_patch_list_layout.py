"""Shared width contract for the Patches side list."""

# Width bounds for dynamic Patch list panel sizing, in terminal cells.
CL_LIST_MIN_PANEL_WIDTH = 43
CL_LIST_MAX_PANEL_WIDTH = 80

# Matches the renderer-side padding used when broadcasting WidthChanged:
# border, scrollbar, and visual breathing room around option prompts.
CL_LIST_CONTENT_WIDTH_PADDING = 8
CL_LIST_MAX_CONTENT_WIDTH = CL_LIST_MAX_PANEL_WIDTH - CL_LIST_CONTENT_WIDTH_PADDING
