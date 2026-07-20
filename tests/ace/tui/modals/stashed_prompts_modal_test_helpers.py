"""Shared helpers for stashed-prompts modal tests."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.stashed_prompts_modal import StashedPromptsModal
from sase.core.prompt_stash_wire import PromptStashEntryWire


def make_entry(
    entry_id: str,
    text: str = "draft",
    *,
    created_at: str = "2026-06-16T10:00:00",
    project: str | None = "proj",
    pane_index: int = 0,
    pinned: bool = False,
) -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=entry_id,
        created_at=created_at,
        text=text,
        project=project,
        pane_index=pane_index,
        pinned=pinned,
    )


class ModalHost(App[None]):
    """Push the stash panel and capture its dismiss result."""

    def __init__(self, entries: list[PromptStashEntryWire]) -> None:
        super().__init__()
        self._entries = entries
        self.result: object = "UNSET"
        self.pin_events: list[StashedPromptsModal.PinToggled] = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            StashedPromptsModal(self._entries),
            lambda result: setattr(self, "result", result),
        )

    def on_stashed_prompts_modal_pin_toggled(
        self, event: StashedPromptsModal.PinToggled
    ) -> None:
        self.pin_events.append(event)
