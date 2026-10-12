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

import dataclasses

from rich.style import Style
from textual.message import Message
from textual.widgets._text_area import TextAreaTheme

from sase.ace.query.highlighting import tokenize_query_for_display

from .filter_bar import FilterBar, FilterBarInput

__all__ = ["AgentsFilterBar"]

_SCOPE_THEME_NAME = "sase-agents-scope"
_SCOPE_AMBER = Style(bold=True, color="#d7af5f")


class _AgentsFilterBarInput(FilterBarInput):
    """Agents editor that paints the host ``in:`` token as an amber chip."""

    def on_mount(self) -> None:
        super().on_mount()
        self._register_scope_theme()
        self.theme = _SCOPE_THEME_NAME

    def _register_scope_theme(self) -> None:
        base_name = str(getattr(self, "theme", "css") or "css")
        base = TextAreaTheme.get_builtin_theme(base_name)
        if base is None:
            base = TextAreaTheme.get_builtin_theme("css")
        if base is None:
            return
        syntax_styles = dict(base.syntax_styles)
        syntax_styles["scope_key"] = _SCOPE_AMBER
        syntax_styles["scope_value"] = _SCOPE_AMBER
        self.register_theme(
            dataclasses.replace(
                base, name=_SCOPE_THEME_NAME, syntax_styles=syntax_styles
            )
        )

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        offset = 0
        for token, kind in tokenize_query_for_display(text, host_scope=True):
            start = offset
            end = offset + len(token)
            offset = end
            if kind not in {"scope_key", "scope_value"}:
                continue
            start_byte = len(text[:start].encode("utf-8"))
            end_byte = len(text[:end].encode("utf-8"))
            # Textual's map is a defaultdict that parent `_build_highlight_map`
            # clears; an empty map is falsy, so seed line 0 here.
            self._highlights[0].append((start_byte, end_byte, kind))


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
    INPUT_CLASS = _AgentsFilterBarInput

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
