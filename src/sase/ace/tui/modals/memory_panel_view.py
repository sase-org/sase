"""Widget updates for the Memory panel's header, footer, trail, and card.

Facade preserving the original module's public import path. The
implementation now lives in sibling modules (each at most 500 lines):

- :mod:`sase.ace.tui.modals.memory_panel_view_chrome` — header, footer,
  trail strip, and note-rail width.
- :mod:`sase.ace.tui.modals.memory_panel_view_diff` — diff widgets and
  the diff/read paint step.
- :mod:`sase.ace.tui.modals.memory_panel_view_card` — note-card rendering
  and body previews.
- :mod:`sase.ace.tui.modals.memory_panel_view_time` — past frame, pinned
  head, and time strip.

Only the original public names are re-exported here.
"""

from __future__ import annotations

from .memory_panel_view_card import MemoryPanelViewCardMixin
from .memory_panel_view_chrome import MemoryPanelViewChromeMixin
from .memory_panel_view_diff import MemoryPanelViewDiffMixin
from .memory_panel_view_time import MemoryPanelViewTimeMixin


class MemoryPanelViewMixin(
    MemoryPanelViewCardMixin,
    MemoryPanelViewChromeMixin,
    MemoryPanelViewDiffMixin,
    MemoryPanelViewTimeMixin,
):
    """Header, footer, trail, and note-card rendering."""


__all__ = ["MemoryPanelViewMixin"]
