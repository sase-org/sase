"""Reusable stash list/preview pane for the tabbed Prompts overlay."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget

from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.project_display_names import ProjectDisplaySnapshot

from .base import OptionListNavigationMixin
from .stash_controller import StashControllerMixin
from .stash_messages import (
    DeleteRequested,
    PinToggled,
    STASH_BINDINGS,
    StashRestoreResult,
    TrashRequested,
)


def _stash_empty_text(*, trash_count: int) -> str:
    """Return the empty-Stash explanation, pointing at Trash when it has rows."""
    base = "No stashed drafts yet. Stash the current prompt to save it here."
    if trash_count:
        noun = "draft" if trash_count == 1 else "drafts"
        base += f" Trash holds {trash_count} discarded {noun} — switch with ]."
    return base


class StashPane(StashControllerMixin, OptionListNavigationMixin, Widget):
    """Reusable stash list/preview pane for the tabbed Prompts overlay.

    The overlay shell owns the heading and footer; this pane renders only the
    list/preview panels and reports outcomes as :class:`StashPane.Selected`
    instead of dismissing a screen.
    """

    class Selected(Message):
        """Posted when the stash pane resolves to a restore outcome or cancel."""

        def __init__(self, result: StashRestoreResult | None) -> None:
            super().__init__()
            self.result = result

    # Re-export the shared stash messages so hosts can reference one home.
    PinToggled = PinToggled
    DeleteRequested = DeleteRequested
    TrashRequested = TrashRequested

    # In the overlay, delete marks commit to Trash rather than permanent
    # deletion; the pane holds pending state until the host repaints from
    # the authoritative store outcome.
    _delete_marks_mean_trash = True

    BINDINGS = STASH_BINDINGS

    def __init__(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
        trash_limit: int = 20,
        trash_count: int = 0,
    ) -> None:
        super().__init__()
        self._init_stash_controller(
            entries,
            project_display_snapshot=project_display_snapshot,
            trash_limit=trash_limit,
            trash_count=trash_count,
        )

    def _placeholder_text(self) -> str | None:
        if self._entries:
            return None
        return _stash_empty_text(trash_count=self._trash_count)

    def dismiss(self, result: StashRestoreResult | None = None) -> None:
        """Translate screen-style cancel/confirm into a bubbled selection."""
        self.post_message(StashPane.Selected(result))

    def _emit_result(self, result: StashRestoreResult | None = None) -> None:
        self.dismiss(result)

    def compose(self) -> ComposeResult:
        with Vertical(id="stash-pane-body"):
            yield from self._compose_stash_panels(with_chrome=False)

    def on_mount(self) -> None:
        self._on_stash_mount()

    def on_unmount(self) -> None:
        self._on_stash_unmount()

    def on_resize(self, event: events.Resize) -> None:
        self._on_stash_resize(event)
