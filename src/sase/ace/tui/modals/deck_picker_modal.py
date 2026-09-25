"""Centered deck picker for the Agents tab (opens on ``p``)."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.widgets.decks.model import DeckId
from sase.ace.tui.widgets.decks.picker import DeckPickerRow

_DECK_CLASS = {
    DeckId.MAIN: "-deck-main",
    DeckId.FILES: "-deck-files",
    DeckId.TOOLS: "-deck-tools",
}


def _build_deck_picker_legend(letters: tuple[str, ...], *, width: int = 48) -> str:
    """Build the border-subtitle legend, trimming tail words to fit."""
    joined = "/".join(letters)
    tiers = (
        f"{joined} pick \u00b7 j/k move \u00b7 enter select \u00b7 esc close",
        f"{joined} pick \u00b7 j/k move \u00b7 enter \u00b7 esc close",
        f"{joined} pick \u00b7 j/k \u00b7 enter \u00b7 esc",
        f"{joined} pick \u00b7 esc",
    )
    if width <= 0:
        return tiers[0]
    for tier in tiers:
        if len(tier) <= width:
            return tier
    return tiers[-1]


class DeckPickerModal(ModalScreen[DeckId | None]):
    """Pick which deck the focused deck panel shows."""

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
        close_keys: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self._rows = tuple(rows)
        self._heading = heading
        self._key_to_index = {row.key.lower(): i for i, row in enumerate(self._rows)}
        self._selected = next(
            (i for i, row in enumerate(self._rows) if row.is_current), 0
        )
        reserved = {"j", "k"}
        reserved |= set(self._key_to_index)
        self._close_keys = tuple(
            k.lower() for k in close_keys if k.lower() not in reserved
        )
        self._dismissed = False
        letters = tuple(row.key for row in self._rows)
        self._legend = _build_deck_picker_legend(letters)

    @property
    def rows(self) -> tuple[DeckPickerRow, ...]:
        """Return the picker rows."""
        return self._rows

    def compose(self) -> ComposeResult:
        with Container(id="deck-picker-container"):
            yield Static(self._heading, id="deck-picker-heading")
            for index, row in enumerate(self._rows):
                yield Static(
                    self._row_text(row, focused=index == self._selected),
                    id=f"deck-picker-row-{index}",
                    classes=self._row_classes(row, index),
                )

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
        lowered = key.lower() if isinstance(key, str) else ""
        if lowered and lowered in self._close_keys:
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        character = event.character.lower() if event.character else ""
        if character and character in self._key_to_index:
            event.prevent_default()
            event.stop()
            self._select_index(self._key_to_index[character])
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
            prefix = "deck-picker-row-"
            if isinstance(widget_id, str) and widget_id.startswith(prefix):
                try:
                    index = int(widget_id.removeprefix(prefix))
                except ValueError:
                    return
                if 0 <= index < len(self._rows):
                    event.prevent_default()
                    event.stop()
                    self._select_index(index)
                return
            widget = getattr(widget, "parent", None)

    def action_cancel(self) -> None:
        """Cancel the picker."""
        self._dismiss_once(None)

    def action_select_current(self) -> None:
        """Pick the highlighted row."""
        self._select_index(self._selected)

    def action_cursor_down(self) -> None:
        """Move the highlight down, wrapping."""
        if self._rows:
            self._selected = (self._selected + 1) % len(self._rows)
            self._refresh()

    def action_cursor_up(self) -> None:
        """Move the highlight up, wrapping."""
        if self._rows:
            self._selected = (self._selected - 1) % len(self._rows)
            self._refresh()

    def _select_index(self, index: int) -> None:
        self._dismiss_once(self._rows[index].deck)

    def _dismiss_once(self, result: DeckId | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        for index, row in enumerate(self._rows):
            focused = index == self._selected
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

    def _row_classes(self, row: DeckPickerRow, index: int) -> str:
        classes = ["deck-picker-row", _DECK_CLASS[row.deck]]
        if index == self._selected:
            classes.append("focused")
        if row.is_current:
            classes.append("current")
        if row.has_content is False:
            classes.append("empty")
        return " ".join(classes)


__all__ = ["DeckPickerModal"]
