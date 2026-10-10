"""Auto-hiding inline query editor for the top-level Agents tab (sase-zf.4).

Configured entirely from the compiled ``agents-live`` profile (see
:func:`sase.ace.query_profile.profiles.agents_live_query_schema`). Unlike
every other :class:`~sase.ace.tui.widgets.filter_bar.FilterBar` subclass,
this bar has no closed/resting display of its own: the canonical query and
match count are rendered by :class:`~sase.ace.tui.widgets.agent_info_panel.AgentInfoPanel`
instead, so the bar takes zero screen space whenever it is not actively
being edited (neither ``PERSISTENT`` nor ``SHOW_WHEN_ACTIVE``).
"""

from __future__ import annotations

from textual.message import Message

from .filter_bar import FilterBar

__all__ = ["AgentsFilterBar"]


class AgentsFilterBar(FilterBar):
    """Editing-only Agents-tab query editor, accented in the agents gold."""

    ACCENT = "#FFD700"
    ROW_ID = "agents-filter-row"
    SIGIL_ID = "agents-filter-sigil"
    INPUT_ID = "agents-filter-input"
    STATUS_ID = "agents-filter-status"
    COMPLETION_ID = "agents-filter-completion"
    CANDIDATE_ID_PREFIX = "agents-filter-candidate"
    # A DISPLAY_ID is required even though it is never actually shown (the
    # info panel owns the resting readout, see module docstring): with
    # neither PERSISTENT nor SHOW_WHEN_ACTIVE, the bar is never
    # resting-visible, so ``FilterBar``'s closed-display bookkeeping is what
    # keeps the inline editor non-focusable and hidden at rest -- without
    # one, the editor would default to focusable and steal the app's
    # initial focus target (sase-zf.4 regression: `next_tab`/`prev_tab`
    # disable themselves whenever a VimTextArea is focused).
    DISPLAY_ID = "agents-filter-display"
    PERSISTENT = False
    SHOW_WHEN_ACTIVE = False
    FORWARD_ARTIFACTS_PAGING = False
    FORWARD_QUERY_HISTORY_KEYS = True

    class QueryChanged(Message):
        """The user changed the live query text."""

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

    def _inject_host_limit_completions(self) -> None:
        super()._inject_host_limit_completions()
        self._inject_host_scope_completions()

    def _inject_host_scope_completions(self) -> None:
        """Expose the host-owned ``in:`` token on the Agents-tab filter bar."""

        from sase.ace.query.scope_token import (
            HOST_SCOPE_HINT,
            HOST_SCOPE_KEY,
            HOST_SCOPE_VALUE_HINT,
            HOST_SCOPE_VALUES,
        )

        if not any(key == HOST_SCOPE_KEY for key, _hint in self.KEY_COMPLETIONS):
            items = [*(self.KEY_COMPLETIONS), (HOST_SCOPE_KEY, HOST_SCOPE_HINT)]
            items.sort(key=lambda item: item[0])
            self.KEY_COMPLETIONS = tuple(items)
        static = dict(self.STATIC_VALUE_COMPLETIONS)
        if not static.get(HOST_SCOPE_KEY):
            static[HOST_SCOPE_KEY] = HOST_SCOPE_VALUES
            self.STATIC_VALUE_COMPLETIONS = static
        hints = dict(self.VALUE_HINTS)
        if HOST_SCOPE_KEY not in hints:
            hints[HOST_SCOPE_KEY] = HOST_SCOPE_VALUE_HINT
            self.VALUE_HINTS = hints
