"""Resolve-stranded-work modal: Continue (fork) or Close bead."""

from __future__ import annotations

from dataclasses import replace

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.models.stranded_resolve import (
    StrandedResolveResult,
    StrandedResolveView,
    blocking_line,
)
from sase.bead.stranded_presentation import (
    STRANDED_GLYPH,
    STRANDED_LEAF_STYLE,
)

_FOOTER_ENABLED = "f/⏎ Continue  ·  c Close bead  ·  esc Cancel"
_FOOTER_DISABLED = "Continue disabled  ·  c Close bead  ·  esc Cancel"


class StrandedResolveModal(ModalScreen[StrandedResolveResult | None]):
    """Offer Continue or Close for one stranded or blocked bead.

    Facts are supplied by :class:`StrandedResolveView`; mounting does no I/O.
    """

    BINDINGS = [
        Binding("enter", "continue_leaf", "Continue", show=False),
        Binding("f", "continue_leaf", "Continue", show=False),
        Binding("c", "close_leaf", "Close bead", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("j", "cursor_down", "Next leaf", show=False),
        Binding("k", "cursor_up", "Previous leaf", show=False),
        Binding("down", "cursor_down", "Next leaf", show=False),
        Binding("up", "cursor_up", "Previous leaf", show=False),
    ]

    def __init__(self, view: StrandedResolveView) -> None:
        super().__init__()
        if not view.leaves:
            raise ValueError("StrandedResolveModal needs at least one leaf")
        self._view = view
        self._dismissed = False

    @property
    def view(self) -> StrandedResolveView:
        """Return the current view, including the selected leaf index."""
        return self._view

    def compose(self) -> ComposeResult:
        with Container(id="stranded-resolve-container"):
            yield Static(self._title_text(), id="stranded-resolve-title")
            yield Static(self._body_text(), id="stranded-resolve-body")
            if len(self._view.leaves) > 1:
                with VerticalScroll(id="stranded-resolve-leaves"):
                    for index in range(len(self._view.leaves)):
                        yield Static(
                            self._leaf_row(index),
                            id=f"stranded-resolve-leaf-{index}",
                            classes=self._leaf_classes(index),
                        )
            yield Static(self._actions_text(), id="stranded-resolve-actions")
            yield Static(self._footer_text(), id="stranded-resolve-footer")

    def on_mount(self) -> None:
        self._refresh()

    def on_key(self, event: events.Key) -> None:
        character = event.character if event.character else ""
        if character.isdigit() and character != "0":
            index = int(character) - 1
            if 0 <= index < len(self._view.leaves):
                event.prevent_default()
                event.stop()
                self._select_index(index)
                return
        if event.key in {"enter", "f"}:
            event.prevent_default()
            event.stop()
            self.action_continue_leaf()
            return
        if event.key == "c":
            event.prevent_default()
            event.stop()
            self.action_close_leaf()
            return
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()
            return
        if event.key in {"j", "down"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_down()
            return
        if event.key in {"k", "up"}:
            event.prevent_default()
            event.stop()
            self.action_cursor_up()
            return

    def action_cancel(self) -> None:
        self._dismiss_once(None)

    def action_continue_leaf(self) -> None:
        leaf = self._view.selected_leaf
        if leaf.continue_disabled_reason:
            self.notify(leaf.continue_disabled_reason, severity="warning")
            return
        self._dismiss_once(
            StrandedResolveResult(
                choice="continue",
                project=self._view.project,
                leaf_id=leaf.bead_id,
            )
        )

    def action_close_leaf(self) -> None:
        leaf = self._view.selected_leaf
        self._dismiss_once(
            StrandedResolveResult(
                choice="close",
                project=self._view.project,
                leaf_id=leaf.bead_id,
            )
        )

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def _move(self, delta: int) -> None:
        if len(self._view.leaves) < 2:
            return
        index = (self._view.selected_index + delta) % len(self._view.leaves)
        self._select_index(index)

    def _select_index(self, index: int) -> None:
        self._view = replace(self._view, selected_index=index)
        self._refresh()

    def _dismiss_once(self, result: StrandedResolveResult | None) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(result)

    def _refresh(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#stranded-resolve-title", Static).update(self._title_text())
        self.query_one("#stranded-resolve-body", Static).update(self._body_text())
        self.query_one("#stranded-resolve-actions", Static).update(self._actions_text())
        self.query_one("#stranded-resolve-footer", Static).update(self._footer_text())
        if len(self._view.leaves) < 2:
            return
        for index in range(len(self._view.leaves)):
            row = self.query_one(f"#stranded-resolve-leaf-{index}", Static)
            row.update(self._leaf_row(index))
            row.set_class(index == self._view.selected_index, "focused")

    def _title_text(self) -> Text:
        state = "Stranded" if self._view.focus_state == "stranded" else "Blocked"
        text = Text()
        text.append(
            f"{STRANDED_GLYPH} {state} {self._view.title_kind}",
            style=STRANDED_LEAF_STYLE,
        )
        return text

    def _body_text(self) -> Text:
        leaf = self._view.selected_leaf
        title = self._view.focus_title or leaf.title
        heading = f"{self._view.focus_id}"
        if title:
            heading = f"{heading} · {title}"
        state_word = "stranded" if self._view.focus_state == "stranded" else "blocked"
        status = f"in_progress · {state_word}"
        if self._view.focus_age:
            status = f"{status} {self._view.focus_age}"
        body = Text()
        body.append(heading + "\n", style="bold")
        body.append(status + "\n\n")
        last_turn = leaf.last_turn or "—"
        ended = f" · ended {leaf.ended_at_label}" if leaf.ended_at_label else ""
        body.append("Last turn  ", style="dim")
        body.append(f"{last_turn}{ended}\n")
        body.append("Why        ", style="dim")
        body.append(f"{leaf.cause}\n")
        blocking = blocking_line(leaf.blocks)
        if blocking:
            body.append("Blocking   ", style="dim")
            body.append(blocking)
        return body

    def _leaf_row(self, index: int) -> Text:
        leaf = self._view.leaves[index]
        focused = index == self._view.selected_index
        row = Text(no_wrap=True, overflow="ellipsis")
        row.append(
            "› " if focused else "  ", style="bold #FFAF00" if focused else "dim"
        )
        row.append(f"{index + 1}  ", style="bold #FFAF00" if focused else "dim")
        row.append(leaf.bead_id, style=STRANDED_LEAF_STYLE)
        if leaf.age:
            row.append(f"  {leaf.age}", style="dim")
        return row

    def _leaf_classes(self, index: int) -> str:
        classes = "stranded-resolve-leaf"
        if index == self._view.selected_index:
            classes += " focused"
        return classes

    def _actions_text(self) -> Text:
        leaf = self._view.selected_leaf
        text = Text()
        if leaf.continue_disabled_reason:
            text.append("  f ⏎  Continue  ", style="dim")
            text.append(f"({leaf.continue_disabled_reason})\n", style="dim")
        else:
            text.append("  f ⏎  ", style="bold #FFAF00")
            text.append("Continue: fork the last turn; the fork takes over\n")
        text.append("  c    ", style="bold")
        text.append("Close bead: the work is done; record a note\n")
        text.append("  esc  ", style="dim")
        text.append("Cancel")
        return text

    def _footer_text(self) -> str:
        if self._view.selected_leaf.continue_disabled_reason:
            return _FOOTER_DISABLED
        return _FOOTER_ENABLED


__all__ = ["StrandedResolveModal"]
