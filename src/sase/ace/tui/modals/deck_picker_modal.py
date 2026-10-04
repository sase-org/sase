"""Centered deck picker for the Agents tab (opens on ``p``)."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.picker import (
    BackOrigin,
    DeckPick,
    DeckPickerBackRow,
    DeckPickerRow,
    pick_deck_capital,
    usable_back_keys,
)
from sase.ace.tui.widgets.decks.spec import DECK_SPECS

_DECK_CLASS: dict[DeckId, str] = {s.deck_id: s.picker_class for s in DECK_SPECS}
_BACK_ROW_INNER = 48
_BACK_ARROW = "\u21a9"


def _build_deck_picker_legend(
    letters: tuple[str, ...],
    *,
    back: str = "",
    width: int = 64,
) -> str:
    """Build the border-subtitle legend, trimming tail words to fit."""
    joined = "/".join(letters)
    back_prefix = f"{back} back \u00b7 " if back else ""
    tiers = (
        f"{back_prefix}{joined} pick \u00b7 j/k move \u00b7 enter select \u00b7 esc close",
        f"{back_prefix}{joined} pick \u00b7 j/k move \u00b7 enter \u00b7 esc close",
        f"{back_prefix}{joined} pick \u00b7 j/k \u00b7 enter \u00b7 esc",
        f"{back_prefix}{joined} pick \u00b7 esc",
        f"{joined} pick \u00b7 esc",
    )
    if width <= 0:
        return tiers[0]
    for tier in tiers:
        if len(tier) <= width:
            return tier
    return tiers[-1]


class DeckPickerModal(ModalScreen[DeckPick | None]):
    """Pick which deck a deck panel shows.

    A lowercase deck letter (or Enter, or a click) targets the focused panel.
    When ``other_hint`` is set, the capital letter targets the other panel.
    Pressing the opener again selects the return row for this panel; the
    opener's capital selects that same deck for the other panel.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "select_current", "Select"),
        ("j", "cursor_down", "Next"),
        ("k", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("up", "cursor_up", "Previous"),
    ]

    def __init__(
        self,
        rows: tuple[DeckPickerRow, ...],
        heading: str,
        back: DeckPickerBackRow,
        back_keys: tuple[str, ...] = (),
        other_hint: str | None = None,
    ) -> None:
        super().__init__()
        self._rows = tuple(rows)
        self._back = back
        self._heading = heading
        self._other_hint = other_hint
        self._key_to_index = {row.key.lower(): i for i, row in enumerate(self._rows)}
        self._capital_to_index = {
            row.key.upper(): i
            for i, row in enumerate(self._rows)
            if row.key.upper() != row.key.lower()
        }
        self._item_count = 1 + len(self._rows)
        self._selected = next(
            (i + 1 for i, row in enumerate(self._rows) if row.is_current),
            1 if self._rows else 0,
        )
        self._back_keys = usable_back_keys(back_keys)
        self._back_capital: str | None = None
        if other_hint is not None:
            for key in back_keys:
                capital = pick_deck_capital(key)
                if capital is not None and capital not in self._capital_to_index:
                    self._back_capital = capital
                    break
        self._dismissed = False
        letters = tuple(row.key for row in self._rows)
        back_token = self._back.key if self._back_keys else ""
        self._legend = _build_deck_picker_legend(letters, back=back_token)

    @property
    def rows(self) -> tuple[DeckPickerRow, ...]:
        """Return the picker rows."""
        return self._rows

    def compose(self) -> ComposeResult:
        with Container(id="deck-picker-container"):
            yield Static(self._heading, id="deck-picker-heading")
            yield Static(
                self._back_text(focused=self._selected == 0),
                id="deck-picker-back",
                classes=self._back_classes(focused=self._selected == 0),
            )
            for index, row in enumerate(self._rows):
                yield Static(
                    self._row_text(row, focused=index + 1 == self._selected),
                    id=f"deck-picker-row-{index}",
                    classes=self._row_classes(row, index + 1),
                )
            if self._other_hint is not None:
                yield Static(self._other_hint_text(), id="deck-picker-other-hint")

    def on_mount(self) -> None:
        try:
            container = self.query_one("#deck-picker-container", Container)
            container.border_title = "Switch deck"
            container.border_subtitle = self._legend
        except Exception:
            pass
        self._refresh()

    def on_key(self, event: events.Key) -> None:
        """Handle picker keys and swallow every other printable key."""
        key = event.key
        if key == "enter":
            event.prevent_default()
            event.stop()
            self.action_select_current()
            return
        if key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        if key in {"j", "down"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_down()
            return
        if key in {"k", "up"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
            return
        if key == "q":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        character = event.character or ""
        if key in self._back_keys or character in self._back_keys:
            event.prevent_default()
            event.stop()
            self._select_item(0)
            return
        if (
            self._other_hint is not None
            and self._back_capital is not None
            and character == self._back_capital
        ):
            event.prevent_default()
            event.stop()
            self._select_item(0, other_panel=True)
            return
        # Case-sensitive on purpose: lowercase targets this panel, the
        # capital targets the other one, whatever key name the terminal
        # reports for the shifted letter.
        if character in self._key_to_index:
            event.prevent_default()
            event.stop()
            self._select_item(self._key_to_index[character] + 1)
            return
        capital_index = (
            self._capital_to_index.get(character)
            if self._other_hint is not None
            else None
        )
        if capital_index is not None:
            event.prevent_default()
            event.stop()
            self._select_item(capital_index + 1, other_panel=True)
            return
        if event.character and event.character.isprintable():
            event.prevent_default()
            event.stop()
            return
        # Non-printable keys that are not part of the picker are also
        # swallowed so nothing leaks through to the Agents tab.
        event.prevent_default()
        event.stop()

    def on_click(self, event: events.Click) -> None:
        """Pick the clicked row."""
        widget = event.widget
        while widget is not None:
            widget_id = getattr(widget, "id", None)
            if widget_id == "deck-picker-back":
                event.prevent_default()
                event.stop()
                self._select_item(0)
                return
            prefix = "deck-picker-row-"
            if isinstance(widget_id, str) and widget_id.startswith(prefix):
                try:
                    index = int(widget_id.removeprefix(prefix))
                except ValueError:
                    return
                if 0 <= index < len(self._rows):
                    event.prevent_default()
                    event.stop()
                    self._select_item(index + 1)
                return
            widget = getattr(widget, "parent", None)

    def action_cancel(self) -> None:
        """Cancel the picker."""
        self._dismiss_once(None)

    def action_select_current(self) -> None:
        """Pick the highlighted row."""
        self._select_item(self._selected)

    def action_cursor_down(self) -> None:
        """Move the highlight down, wrapping."""
        if self._item_count:
            self._selected = (self._selected + 1) % self._item_count
            self._refresh()

    def action_cursor_up(self) -> None:
        """Move the highlight up, wrapping."""
        if self._item_count:
            self._selected = (self._selected - 1) % self._item_count
            self._refresh()

    def _select_item(self, index: int, *, other_panel: bool = False) -> None:
        if index == 0:
            self._dismiss_once(DeckPick(self._back.deck, other_panel))
            return
        self._dismiss_once(DeckPick(self._rows[index - 1].deck, other_panel))

    def _dismiss_once(self, result: DeckPick | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        back_focused = self._selected == 0
        try:
            back_widget = self.query_one("#deck-picker-back", Static)
        except Exception:
            back_widget = None
        if back_widget is not None:
            back_widget.update(self._back_text(focused=back_focused))
            back_widget.set_class(back_focused, "focused")
            back_widget.set_class(self._back.has_content is False, "empty")
            if back_focused:
                try:
                    back_widget.scroll_visible(animate=False)
                except Exception:
                    pass
        for index, row in enumerate(self._rows):
            focused = index + 1 == self._selected
            try:
                widget = self.query_one(f"#deck-picker-row-{index}", Static)
            except Exception:
                continue
            widget.update(self._row_text(row, focused=focused))
            widget.set_class(focused, "focused")
            widget.set_class(row.is_current, "current")
            widget.set_class(row.has_content is False, "empty")
            if focused:
                try:
                    widget.scroll_visible(animate=False)
                except Exception:
                    pass

    def _row_text(self, row: DeckPickerRow, *, focused: bool) -> Text:
        pointer_style = f"bold {row.accent}" if focused else "dim"
        if row.has_content is False:
            key_style = f"bold {row.accent}"
            name_style = "dim"
            blurb_style = "dim"
        elif focused:
            key_style = f"bold black on {row.accent}"
            name_style = f"bold {row.accent}"
            blurb_style = "dim"
        else:
            key_style = f"bold black on {row.accent}"
            name_style = f"bold {row.accent}"
            blurb_style = "dim"
        count_style = "dim"
        if row.is_current:
            badge_style = f"bold {row.accent}"
        else:
            badge_style = "dim"

        text = Text()
        text.append("\u203a " if focused else "  ", style=pointer_style)
        text.append(f" {row.key} ", style=key_style)
        text.append(" ", style="")
        text.append(f"{row.glyph} ", style=f"bold {row.accent}")
        text.append(f"{row.name:<5}", style=name_style)
        text.append("  ", style="")
        if row.count_label:
            text.append(f"{row.count_label:<10}", style=count_style)
        else:
            text.append(" " * 10, style="")
        if row.is_current:
            text.append("\u25cf showing", style=badge_style)
        elif row.other_panel_label is not None:
            text.append(f"\u25cb in {row.other_panel_label} panel", style=badge_style)
        text.append("\n    ", style="")
        text.append(row.blurb, style=blurb_style)
        return text

    def _back_text(self, *, focused: bool) -> Text:
        """Build the single-line return row."""
        row = self._back
        pointer_style = f"bold {row.accent}" if focused else "dim"
        empty = row.has_content is False
        if empty:
            key_style = f"bold {row.accent}"
            name_style = "dim"
        else:
            key_style = f"bold black on {row.accent}"
            name_style = f"bold {row.accent}"
        accent_style = f"bold {row.accent}"
        if row.origin is BackOrigin.LAST:
            badge = "last deck"
            badge_style = accent_style
        else:
            badge = "previous"
            badge_style = "dim"

        left = Text()
        left.append("\u203a " if focused else "  ", style=pointer_style)
        if row.key:
            left.append(f" {row.key} ", style=key_style)
        else:
            left.append("   ", style="")
        left.append(" ", style="")
        left.append(f"{_BACK_ARROW} ", style=accent_style)
        left.append(f"{row.glyph} ", style=accent_style)
        left.append(f"{row.name:<5}", style=name_style)

        count = row.count_label
        used = cell_len(left.plain)
        badge_width = cell_len(badge)
        gap_for_count = 2
        count_width = cell_len(count) if count else 0
        remaining = _BACK_ROW_INNER - used - badge_width
        include_count = bool(count) and remaining >= gap_for_count + count_width + 1
        text = left
        if include_count:
            text.append("  ", style="")
            text.append(count, style="dim")
            used = cell_len(text.plain)
            pad = max(1, _BACK_ROW_INNER - used - badge_width)
            text.append(" " * pad, style="")
        else:
            pad = max(1, _BACK_ROW_INNER - used - badge_width)
            text.append(" " * pad, style="")
        text.append(badge, style=badge_style)
        return text

    def _other_hint_text(self) -> Text:
        """Build the muted hint line telling where a capital letter goes."""
        text = Text()
        # Three columns of indent put each capital under its row's keycap letter.
        text.append("   ")
        if self._back_capital is not None:
            text.append(self._back_capital, style=f"bold {self._back.accent}")
            text.append("/", style="dim")
        for index, row in enumerate(self._rows):
            if index:
                text.append("/", style="dim")
            text.append(row.key.upper(), style=f"bold {row.accent}")
        text.append(f"  {self._other_hint}", style="dim")
        return text

    def _row_classes(self, row: DeckPickerRow, item_index: int) -> str:
        classes = ["deck-picker-row", _DECK_CLASS[row.deck]]
        if item_index == self._selected:
            classes.append("focused")
        if row.is_current:
            classes.append("current")
        if row.has_content is False:
            classes.append("empty")
        return " ".join(classes)

    def _back_classes(self, *, focused: bool) -> str:
        classes = ["deck-picker-row", "deck-picker-back", _DECK_CLASS[self._back.deck]]
        if focused:
            classes.append("focused")
        if self._back.has_content is False:
            classes.append("empty")
        return " ".join(classes)


__all__ = ["DeckPickerModal"]
