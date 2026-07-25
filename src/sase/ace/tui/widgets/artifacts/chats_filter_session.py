"""Live inline-filter session behavior for the Artifacts Chats pane."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sase.history.chat_catalog_provenance import CHAT_PROVENANCE_VALUES
from sase.history.chat_filter_query import (
    ChatFilterQueryError,
    ChatFilterValues,
    parse_chat_filter_query,
    to_query_string,
)

from .chat_filter_bar import ChatFilterBar
from .entry_navigation import ArtifactEntryTarget

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class ChatsFilterSessionMixin(_MixinBase):
    """Own committed/live filters and provenance cycling."""

    filters: ChatFilterValues
    _filter_session_open: bool
    _filter_restore_values: ChatFilterValues | None
    _filter_restore_selection: ArtifactEntryTarget | None
    _live_filter_values: ChatFilterValues | None
    _filter_query_error: ChatFilterQueryError | None

    if TYPE_CHECKING:

        def _refresh_options(
            self,
            *,
            preferred_target: ArtifactEntryTarget | None = None,
            update_detail: bool = True,
        ) -> None: ...

        def selected_entry_target(self) -> ArtifactEntryTarget | None: ...

        def focus_list(self) -> None: ...

        def _set_filter_completion_sources(self) -> None: ...

    def _init_chats_filter_session(self) -> None:
        self.filters = ChatFilterValues()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def show_filters(self) -> None:
        bar = self.query_one(ChatFilterBar)
        if self._filter_session_open:
            bar.query_one("#chat-filter-input").focus()
            return
        self._filter_session_open = True
        self._filter_restore_values = self.filters
        self._filter_restore_selection = self.selected_entry_target()
        self._live_filter_values = self.filters
        self._filter_query_error = None
        self._set_filter_completion_sources()
        bar.open(to_query_string(self.filters))
        self._refresh_options(preferred_target=self._filter_restore_selection)

    def on_chat_filter_bar_query_changed(
        self,
        event: ChatFilterBar.QueryChanged,
    ) -> None:
        event.stop()
        try:
            values = parse_chat_filter_query(event.text)
        except ChatFilterQueryError as exc:
            self._filter_query_error = exc
            self.query_one(ChatFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            return
        self._filter_query_error = None
        self._live_filter_values = values
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options()

    def on_chat_filter_bar_submitted(
        self,
        event: ChatFilterBar.Submitted,
    ) -> None:
        event.stop()
        try:
            values = parse_chat_filter_query(event.text)
        except ChatFilterQueryError as exc:
            self._filter_query_error = exc
            self.query_one(ChatFilterBar).set_status(
                None,
                exact=False,
                error=exc,
            )
            self.notify(exc.message, severity="error")
            return
        self.filters = values
        self._live_filter_values = values
        preferred = self.selected_entry_target()
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_target=preferred)
        self.focus_list()

    def on_chat_filter_bar_dismissed(
        self,
        event: ChatFilterBar.Dismissed,
    ) -> None:
        event.stop()
        restore = self._filter_restore_values
        preferred = self._filter_restore_selection
        if restore is not None:
            self.filters = restore
        self._close_filter_session()
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options(preferred_target=preferred)
        self.focus_list()

    def cycle_provenance(self) -> None:
        """Cycle All → local → shared → remote → unknown → All."""

        current = (
            self.filters.provenances[0] if len(self.filters.provenances) == 1 else None
        )
        if current is None:
            next_value: str | None = CHAT_PROVENANCE_VALUES[0]
        else:
            try:
                index = CHAT_PROVENANCE_VALUES.index(current)  # type: ignore[arg-type]
            except ValueError:
                next_value = CHAT_PROVENANCE_VALUES[0]
            else:
                next_value = (
                    CHAT_PROVENANCE_VALUES[index + 1]
                    if index + 1 < len(CHAT_PROVENANCE_VALUES)
                    else None
                )
        if self._filter_session_open:
            self._close_filter_session()
        self.filters = replace(
            self.filters,
            provenances=(() if next_value is None else (next_value,)),
        )
        self._cancel_jump_mode_for_filter_change()
        self._refresh_options()
        self.focus_list()

    def _display_filter_values(self) -> ChatFilterValues:
        if self._filter_session_open and self._live_filter_values is not None:
            return self._live_filter_values
        return self.filters

    def _close_filter_session(self) -> None:
        self.query_one(ChatFilterBar).close()
        self._filter_session_open = False
        self._filter_restore_values = None
        self._filter_restore_selection = None
        self._live_filter_values = None
        self._filter_query_error = None

    def _cancel_jump_mode_for_filter_change(self) -> None:
        cancel = getattr(
            self.app,
            "_cancel_artifacts_jump_mode_for_model_change",
            None,
        )
        if callable(cancel):
            cancel("chats")


__all__ = ["ChatsFilterSessionMixin"]
