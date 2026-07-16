"""Cached saved-PR-query chooser."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.saved_queries import KEY_ORDER

from ..widgets.changespec_detail import build_query_text
from .base import OptionListNavigationMixin

SAVED_QUERY_SLOT_ORDER: tuple[str, ...] = tuple(KEY_ORDER[1:] + KEY_ORDER[:1])
_QUERY_DISPLAY_WIDTH = 58


def _canonical_query_or_raw(query: str) -> str:
    """Return a canonical query for comparison, tolerating malformed slots."""
    try:
        from sase.ace.query import parse_query, to_canonical_string

        return to_canonical_string(parse_query(query))
    except Exception:
        return query


class SavedQueryPickerModal(
    OptionListNavigationMixin,
    ModalScreen[str | None],
):
    """Choose a populated saved-query slot from an immutable cache snapshot."""

    _option_list_id = "saved-query-picker-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("enter", "select_highlighted", "Load", show=False),
        *[
            Binding(slot, f"select_slot('{slot}')", f"Load Q{slot}", show=False)
            for slot in SAVED_QUERY_SLOT_ORDER
        ],
    ]

    def __init__(
        self,
        queries: Mapping[str, str],
        active_query: str,
    ) -> None:
        super().__init__()
        snapshot = {
            slot: query
            for slot, query in dict(queries).items()
            if slot in SAVED_QUERY_SLOT_ORDER and isinstance(query, str)
        }
        self._queries: Mapping[str, str] = MappingProxyType(snapshot)
        self._slots = tuple(
            slot for slot in SAVED_QUERY_SLOT_ORDER if slot in self._queries
        )
        self._active_query = active_query
        self._active_slots = frozenset(
            slot
            for slot in self._slots
            if _canonical_query_or_raw(self._queries[slot]) == active_query
        )

    @property
    def queries(self) -> Mapping[str, str]:
        """Expose the immutable snapshot for diagnostics and tests."""
        return self._queries

    @property
    def slots(self) -> tuple[str, ...]:
        """Return populated slots in deterministic display order."""
        return self._slots

    def compose(self) -> ComposeResult:
        with Container(id="saved-query-picker-container"):
            yield Static(self._build_title(), id="saved-query-picker-title")
            yield OptionList(
                *[Option(self._build_option(slot), id=slot) for slot in self._slots],
                id=self._option_list_id,
                classes="-empty" if not self._slots else "",
            )
            if not self._slots:
                yield Static(
                    self._build_empty_state(),
                    id="saved-query-picker-empty",
                )
            yield Static(
                self._build_footer(),
                id="saved-query-picker-footer",
            )

    def on_mount(self) -> None:
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        if self._slots:
            option_list.highlighted = next(
                (
                    index
                    for index, slot in enumerate(self._slots)
                    if slot in self._active_slots
                ),
                0,
            )
            option_list.focus()

    def _build_title(self) -> Text:
        text = Text()
        text.append("✦ ", style="bold #FFD700")
        text.append("Saved PR Queries", style="bold #F5F5F5")
        text.append("  ", style="")
        count = len(self._slots)
        text.append(
            f"{count} {'slot' if count == 1 else 'slots'}",
            style="dim #87D7FF",
        )
        return text

    def _build_option(self, slot: str) -> Text:
        query_text = build_query_text(self._queries[slot])
        query_text.truncate(_QUERY_DISPLAY_WIDTH, overflow="ellipsis")

        text = Text()
        is_active = slot in self._active_slots
        text.append(
            f" {slot} ",
            style="bold black on #FFD700" if is_active else "bold #FFD700",
        )
        text.append("  ")
        text.append_text(query_text)
        if is_active:
            text.append("  ● active", style="bold #00D7AF")
        return text

    @staticmethod
    def _build_empty_state() -> Text:
        text = Text(justify="center")
        text.append("No saved PR queries yet\n", style="bold #FFD700")
        text.append("Press /, then save with ", style="dim")
        text.append("#<slot> <query>", style="bold #00D7AF")
        text.append("\nExample: ", style="dim")
        text.append('#1 "my-feature"', style="#87D7FF")
        return text

    def _build_footer(self) -> Text:
        text = Text(justify="center")
        if self._slots:
            text.append("1–9 / 0 load", style="#FFD700")
            text.append("  ·  j/k or ↑/↓ move  ·  Enter select", style="dim")
        else:
            text.append("No populated slots to select", style="dim")
        text.append("  ·  q/Esc close", style="dim")
        return text

    def action_select_slot(self, slot: str) -> None:
        """Load *slot* when populated; otherwise keep the chooser open."""
        if slot not in self._queries:
            self.notify(f"No query saved in slot {slot}", severity="warning")
            return
        self.dismiss(slot)

    def action_select_highlighted(self) -> None:
        """Load the currently highlighted populated slot."""
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None or not (0 <= highlighted < len(self._slots)):
            return
        self.dismiss(self._slots[highlighted])

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        """Load the clicked or Enter-selected option."""
        slot = event.option.id
        if isinstance(slot, str):
            self.action_select_slot(slot)


__all__ = ["SAVED_QUERY_SLOT_ORDER", "SavedQueryPickerModal"]
