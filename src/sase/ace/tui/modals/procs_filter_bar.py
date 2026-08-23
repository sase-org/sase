"""Inline query editor for the Admin Center Procs tab.

Configured entirely from the compiled ``procs`` profile (see
:func:`sase.ace.query_profile.profiles.procs_query_schema`); no key table is
duplicated here.
"""

from __future__ import annotations

from textual.message import Message

from sase.ace.tui.proc_gear_chips import PROC_GEAR_HUE
from sase.ace.tui.widgets.filter_bar import FilterBar

__all__ = ["ProcsFilterBar"]


class ProcsFilterBar(FilterBar):
    """Show-while-active Procs filter editor, accented in the procs teal."""

    ACCENT = PROC_GEAR_HUE
    ROW_ID = "procs-filter-row"
    SIGIL_ID = "procs-filter-sigil"
    INPUT_ID = "procs-filter-input"
    STATUS_ID = "procs-filter-status"
    COMPLETION_ID = "procs-filter-completion"
    CANDIDATE_ID_PREFIX = "procs-filter-candidate"
    DISPLAY_ID = "procs-filter-display"
    PERSISTENT = False
    SHOW_WHEN_ACTIVE = True
    FORWARD_ARTIFACTS_PAGING = False

    class QueryChanged(Message):
        """The user changed the query text."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Submitted(Message):
        """The user requested that the current query be committed."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Dismissed(Message):
        """The user dismissed the bar after closing any completion menu."""
