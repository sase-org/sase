"""Pure render helpers for the Memory panel shell.

Facade preserving the original module's public import path. The
implementation now lives in sibling modules (each at most 500 lines):

- :mod:`sase.ace.tui.modals.memory_panel_rendering_rail` — note-rail
  rows and rail width.
- :mod:`sase.ace.tui.modals.memory_panel_rendering_card` — note card,
  badges, and property grid.
- :mod:`sase.ace.tui.modals.memory_panel_rendering_chrome` — header,
  footer, empty/error states, and accent.

Shared helpers live in the private
:mod:`sase.ace.tui.modals._memory_panel_rendering_shared` module under
public names so siblings never import ``_``-prefixed names across
modules.

Note-rail rows, the header/footer strips, the note card, and empty/error
states are built here. Nothing in this module touches the filesystem or a
mounted widget -- callers apply these renderables to widgets from
:mod:`sase.ace.tui.modals.memory_panel_view`.
"""

from __future__ import annotations

from .memory_panel_rendering_card import (
    append_badge as append_badge,
    build_note_badge_row as build_note_badge_row,
    build_note_card_meta as build_note_card_meta,
    build_property_grid as build_property_grid,
    build_rail_node_card_title as build_rail_node_card_title,
    build_rail_node_description as build_rail_node_description,
    iso_from_mtime_ns as iso_from_mtime_ns,
    memory_note_source_path as memory_note_source_path,
)
from .memory_panel_rendering_chrome import (
    build_diagnostics_message as build_diagnostics_message,
    build_empty_scope_message as build_empty_scope_message,
    build_empty_scope_no_root_message as build_empty_scope_no_root_message,
    build_no_match_message as build_no_match_message,
    build_panel_footer as build_panel_footer,
    build_panel_header as build_panel_header,
    memory_card_accent as memory_card_accent,
)
from .memory_panel_rendering_rail import (
    build_note_row_text as build_note_row_text,
    note_rail_content_width as note_rail_content_width,
    note_rail_width as note_rail_width,
)

__all__ = [
    "append_badge",
    "build_diagnostics_message",
    "build_empty_scope_message",
    "build_empty_scope_no_root_message",
    "build_no_match_message",
    "build_note_badge_row",
    "build_note_card_meta",
    "build_property_grid",
    "build_rail_node_card_title",
    "build_rail_node_description",
    "build_note_row_text",
    "build_panel_footer",
    "build_panel_header",
    "iso_from_mtime_ns",
    "memory_card_accent",
    "memory_note_source_path",
    "note_rail_content_width",
    "note_rail_width",
]
