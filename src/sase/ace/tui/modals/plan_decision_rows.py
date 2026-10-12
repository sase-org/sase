"""Decision cards widget for Plan Decisions (sase-1ka.1).

Each decision is a focusable :class:`DecisionCard` (a ``Static`` rendering
one pure-Rich card from
:mod:`sase.ace.tui.modals.plan_decision_cards`) mounted inside its own
per-decision slot ``VerticalScroll``. ``PlanDecisionRows`` owns the focused
row index and re-renders only the cards a keypress or focus move touches.
"""

from __future__ import annotations

from typing import Any

from textual.containers import Vertical, VerticalScroll
from textual.events import Click
from textual.message import Message
from textual.widgets import Static

from .plan_decision_cards import (
    BuiltCard,
    collapsed_card,
    expanded_card,
    render_lines,
)

#: Fallback card width before the first layout pass measures the real one.
_FALLBACK_CARD_WIDTH = 44


class DecisionCard(Static, can_focus=True):
    """One focusable decision card.

    Clicking the card focuses it (the modal syncs the decision index through
    the normal focus path). Clicking an option line inside the *current*
    choice card posts :class:`PlanDecisionRows.OptionSelected` instead.
    """

    def __init__(
        self,
        index: int,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__("", id=id, classes=classes)
        self._card_index = index
        self._row: dict[str, Any] = {}
        self._definition: dict[str, Any] | None = None
        self._current = False
        self._card_focused = False
        self._read_only = False
        self._preview_lines = 2
        self._card_width = _FALLBACK_CARD_WIDTH
        self._built: BuiltCard | None = None

    @property
    def card_index(self) -> int:
        return self._card_index

    def render_card(
        self,
        row: dict[str, Any],
        definition: dict[str, Any] | None,
        width: int,
        *,
        current: bool,
        focused: bool,
        read_only: bool,
        preview_lines: int = 2,
    ) -> None:
        """Rebuild this card's renderable from a sheet row."""
        self._row = dict(row)
        self._definition = dict(definition) if isinstance(definition, dict) else None
        self._current = current
        self._card_focused = focused
        self._read_only = read_only
        self._preview_lines = preview_lines
        self._card_width = max(int(width), 8)
        if current:
            self._built = expanded_card(
                self._row,
                self._definition,
                self._card_width,
                focused=focused,
                read_only=read_only,
            )
        else:
            self._built = collapsed_card(
                self._row,
                self._definition,
                self._card_width,
                current=False,
                read_only=read_only,
                preview_lines=preview_lines,
            )
        self.update(self._built.renderable)
        self.set_class(current, "-current")
        self.set_class(read_only, "-readonly")

    def refresh_for_width(self, width: int) -> bool:
        """Re-render when the measured content width changed."""
        width = max(int(width), 8)
        if width == self._card_width and self._built is not None:
            return False
        self.render_card(
            self._row,
            self._definition,
            width,
            current=self._current,
            focused=self._card_focused,
            read_only=self._read_only,
            preview_lines=self._preview_lines,
        )
        return True

    def rendered_lines(self) -> list[str]:
        """Return the current card as plain lines (tests + measuring)."""
        if self._built is None:
            return []
        return render_lines(self._built.renderable, self._card_width)

    def option_at_line(self, line: int) -> str | None:
        """Map a card-local line number to an option key, if any."""
        if self._built is None or not self._current or self._read_only:
            return None
        if str(self._row.get("kind", "")) != "choice":
            return None
        for option in self._built.option_map:
            if option.first_line <= line <= option.last_line:
                return option.key
        return None

    def on_click(self, event: Click) -> None:
        if self._read_only:
            return
        if not self._current:
            # First click makes the card current through the focus path.
            self.focus()
            return
        if str(self._row.get("kind", "")) != "choice":
            return
        try:
            line = int(event.y) - int(self.content_offset.y)
        except Exception:
            return
        key = self.option_at_line(line)
        if key is None:
            return
        event.stop()
        self.post_message(
            PlanDecisionRows.OptionSelected(
                str(self._row.get("id", "")), key, self._card_index
            )
        )


class DecisionSlot(VerticalScroll):
    """One scrollable card slot; composes its own :class:`DecisionCard`."""

    def __init__(self, index: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._slot_index = index

    def compose(self):  # type: ignore[no-untyped-def]
        yield DecisionCard(
            self._slot_index,
            id=f"plan-decision-{self._slot_index}",
            classes="plan-decision-card",
        )


class PlanDecisionRows(Vertical):
    """Pinned decision cards; the modal owns the draft."""

    class OptionSelected(Message):
        """A mouse click picked an option in the current choice card."""

        def __init__(self, decision_id: str, value: str, index: int) -> None:
            super().__init__()
            self.decision_id = decision_id
            self.value = value
            self.index = index

    def __init__(
        self,
        sheet_rows: list[dict[str, Any]],
        definitions: list[dict[str, Any]] | None = None,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._rows = list(sheet_rows)
        self._definitions = list(definitions or [])
        self._by_id = {
            str(d.get("id", "")): d for d in self._definitions if str(d.get("id", ""))
        }
        self._focused_index = 0 if self._rows else -1
        self._cards_focused = True
        self._read_only = False

    @property
    def focused_index(self) -> int:
        return self._focused_index

    @property
    def focused_id(self) -> str | None:
        if 0 <= self._focused_index < len(self._rows):
            return str(self._rows[self._focused_index].get("id", ""))
        return None

    def set_read_only(self, read_only: bool) -> None:
        """Mark every card read-only (settled elsewhere) or editable."""
        if self._read_only == read_only:
            return
        self._read_only = read_only
        if self.is_mounted:
            self._render_cards(range(len(self._rows)))

    def update_rows(self, sheet_rows: list[dict[str, Any]]) -> None:
        self._rows = list(sheet_rows)
        if self._focused_index >= len(self._rows):
            self._focused_index = len(self._rows) - 1
        if self._rows and self._focused_index < 0:
            self._focused_index = 0
        if self.is_mounted:
            self._render_cards(range(len(self._rows)))

    def rebuild(
        self, sheet_rows: list[dict[str, Any]], definitions: list[dict[str, Any]]
    ) -> None:
        """Rebuild rows when the id list changed: new definitions + children."""
        old_len = len(self._rows)
        self._rows = list(sheet_rows)
        self._definitions = list(definitions or [])
        self._by_id = {
            str(d.get("id", "")): d for d in self._definitions if str(d.get("id", ""))
        }
        if not self._rows:
            self._focused_index = -1
        elif self._focused_index < 0 or self._focused_index >= len(self._rows):
            self._focused_index = 0
        if not self.is_mounted:
            return
        new_len = len(self._rows)
        # Remove surplus slots when the new id list is shorter.
        for index in range(new_len, old_len):
            for slot in self.query(f"#decision-slot-{index}"):
                slot.remove()
        # Mount missing slots when the new id list is longer.
        if new_len > old_len:
            self.mount(*[self._make_slot(index) for index in range(old_len, new_len)])
        self._render_cards(range(len(self._rows)))

    def set_focused_index(self, index: int) -> None:
        if not self._rows:
            self._focused_index = -1
            return
        old = self._focused_index
        self._focused_index = max(0, min(index, len(self._rows) - 1))
        self._cards_focused = True
        if self.is_mounted:
            touched = {old, self._focused_index}
            self._render_cards(sorted(i for i in touched if 0 <= i < len(self._rows)))

    def set_cards_focused(self, focused: bool) -> None:
        """Re-render the current card for card-focus gained/lost."""
        if self._cards_focused == focused:
            return
        self._cards_focused = focused
        if self.is_mounted and 0 <= self._focused_index < len(self._rows):
            self._render_cards([self._focused_index])

    def refresh_cards(self, indexes: list[int]) -> None:
        """Re-render only the given cards (one keypress worth of work)."""
        if self.is_mounted:
            self._render_cards([i for i in indexes if 0 <= i < len(self._rows)])

    def refresh_with_sheet(
        self, sheet_rows: list[dict[str, Any]], indexes: list[int]
    ) -> None:
        """Swap in fresh sheet rows, then re-render only *indexes*."""
        self._rows = list(sheet_rows)
        if self._focused_index >= len(self._rows):
            self._focused_index = len(self._rows) - 1
        if self._rows and self._focused_index < 0:
            self._focused_index = 0
        self.refresh_cards(indexes)

    def _make_slot(self, index: int) -> DecisionSlot:
        return DecisionSlot(
            index, id=f"decision-slot-{index}", classes="plan-decision-slot"
        )

    def compose(self):  # type: ignore[no-untyped-def]
        for index in range(len(self._rows)):
            yield self._make_slot(index)

    def on_mount(self) -> None:
        # First paint uses the fallback width; the post-layout pass re-wraps
        # every card at its measured content width.
        try:
            self._render_cards(range(len(self._rows)))
        except Exception:
            pass
        try:
            self.call_after_refresh(self._refresh_all_widths)
        except Exception:
            pass

    def on_resize(self) -> None:
        self._refresh_all_widths()

    def _refresh_all_widths(self) -> None:
        if not self.is_mounted:
            return
        for index in range(len(self._rows)):
            try:
                card = self.query_one(f"#plan-decision-{index}", DecisionCard)
            except Exception:
                continue
            try:
                width = card.content_region.width or _FALLBACK_CARD_WIDTH
            except Exception:
                width = _FALLBACK_CARD_WIDTH
            try:
                row = self._rows[index]
                if card._row != row or width != card._card_width or card._built is None:
                    card.render_card(
                        row,
                        self._by_id.get(str(row.get("id", ""))),
                        width,
                        current=(index == self._focused_index),
                        focused=self._cards_focused and (index == self._focused_index),
                        read_only=self._read_only,
                    )
            except Exception:
                continue

    def _render_cards(self, indexes) -> None:  # type: ignore[no-untyped-def]
        for index in indexes:
            card = self.query_one(f"#plan-decision-{index}", DecisionCard)
            row = self._rows[index]
            try:
                width = card.content_region.width or _FALLBACK_CARD_WIDTH
            except Exception:
                width = _FALLBACK_CARD_WIDTH
            if not card.is_mounted:
                width = _FALLBACK_CARD_WIDTH
            card.render_card(
                row,
                self._by_id.get(str(row.get("id", ""))),
                width,
                current=(index == self._focused_index),
                focused=self._cards_focused and (index == self._focused_index),
                read_only=self._read_only,
            )

    def visible_control_ids(self) -> list[str]:
        return [f"plan-decision-{index}" for index in range(len(self._rows))]


__all__ = [
    "DecisionCard",
    "DecisionSlot",
    "PlanDecisionRows",
]
