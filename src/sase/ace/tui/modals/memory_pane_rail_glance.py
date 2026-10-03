"""Rail recency glance and deleted subjects (phase rail-glance).

Facade preserving the original module's public import path. The
implementation now lives in sibling modules (each at most 500 lines):

- :mod:`sase.ace.tui.modals.memory_pane_rail_glance_feed` — feed
  parsing, the recency map, and deleted-subject collection.
- :mod:`sase.ace.tui.modals.memory_pane_rail_glance_rendering` —
  glance suffixes, DELETED row text, tombstone nodes, and the
  read-only refusal toast.
- :mod:`sase.ace.tui.modals.memory_pane_rail_glance_mixin` — the
  ``MemoryPaneRailGlanceMixin`` Notes-rail behavior.
- :mod:`sase.ace.tui.modals._memory_pane_rail_glance_shared` —
  the shared ``DeletedSubject`` type (public name, private module).

Only the original public names are re-exported here.
"""

from __future__ import annotations

from .memory_pane_rail_glance_mixin import MemoryPaneRailGlanceMixin
from .memory_pane_rail_glance_rendering import history_only_refusal

__all__ = [
    "MemoryPaneRailGlanceMixin",
    "history_only_refusal",
]
