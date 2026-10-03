"""Timeline lens: the rail becomes the subject's version timeline (``@``).

Owns the phase timeline-lens rail behind :class:`MemoryPane` (epic
design ``plan:202610/memory_history_tui.md`` §12 and §4.4). ``@``
re-skins the Notes rail into the selected subject's timeline: rows
come from :func:`sase.pager.history_kit.build_picker_rows` laid out by
the kit's picker column fitter, so these are the pager picker's exact
cells. The highlight moves at once while the card follows through the
existing 150 ms detail debouncer; ``b`` sets a compare base, ``.``
reveals hidden versions, and ``⏎``/``l``/``H`` hand the cursor's pin,
view, and base to the pager.

The lens framework (snapshot/restore, Esc ladder) lives in
:mod:`sase.ace.tui.modals.memory_pane_lens`; this module never imports
history presentation except through ``sase.pager.history_kit`` (the
import-guard door).

Facade preserving the original ``memory_pane_timeline_lens`` import
path. The implementation lives in the ``memory_pane_timeline_lens_*``
siblings, with shared rows and rail constants in the private
:mod:`sase.ace.tui.modals._memory_pane_timeline_lens_shared` module
under public names so siblings never import ``_``-prefixed names
across modules. Only the original public names are re-exported here.
"""

from __future__ import annotations

from ._memory_pane_timeline_lens_shared import HIDDEN_SUMMARY_ID as HIDDEN_SUMMARY_ID
from .memory_pane_timeline_lens_actions import MemoryPaneTimelineLensActionsMixin
from .memory_pane_timeline_lens_navigation import (
    MemoryPaneTimelineLensNavigationMixin,
)
from .memory_pane_timeline_lens_preview import MemoryPaneTimelineLensPreviewMixin
from .memory_pane_timeline_lens_rail import MemoryPaneTimelineLensRailMixin
from .memory_pane_timeline_lens_state import MemoryPaneTimelineLensStateMixin


class MemoryPaneTimelineLensMixin(
    MemoryPaneTimelineLensStateMixin,
    MemoryPaneTimelineLensRailMixin,
    MemoryPaneTimelineLensPreviewMixin,
    MemoryPaneTimelineLensActionsMixin,
    MemoryPaneTimelineLensNavigationMixin,
):
    """The ``@`` Timeline lens: rail rows, preview, base, and hand-off."""


__all__ = [
    "HIDDEN_SUMMARY_ID",
    "MemoryPaneTimelineLensMixin",
]
