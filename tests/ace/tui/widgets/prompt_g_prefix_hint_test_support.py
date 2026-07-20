"""Shared test support for prompt ``g`` prefix hint tests."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class GPrefixHintApp(App[None]):
    """Host a prompt bar and expose prompt-stash availability."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        initial_value: str = "",
        *,
        mode: str = "prompt",
        stash_exists: bool = False,
        pinned_exists: bool = False,
    ) -> None:
        super().__init__()
        self._initial_value = initial_value
        self._mode = mode
        self._stash_exists = stash_exists
        self._pinned_exists = pinned_exists
        self.cancelled: list[PromptInputBar.Cancelled] = []
        self.stashed: list[PromptInputBar.Stashed] = []
        self.restore_requests: list[PromptInputBar.RestoreRequested] = []
        self.update_requests: list[PromptInputBar.UpdatePinnedRequested] = []
        self.save_xprompt_requests: list[PromptInputBar.SaveAsXpromptRequested] = []

    def compose(self) -> ComposeResult:
        yield PromptInputBar(
            initial_value=self._initial_value,
            mode=self._mode,
            id="prompt-input-bar",
        )

    def _has_stashed_prompts(self) -> bool:
        return self._stash_exists

    def _has_pinned_stashed_prompts(self) -> bool:
        return self._pinned_exists

    def on_prompt_input_bar_stashed(self, event: PromptInputBar.Stashed) -> None:
        self.stashed.append(event)

    def on_prompt_input_bar_restore_requested(
        self, event: PromptInputBar.RestoreRequested
    ) -> None:
        self.restore_requests.append(event)

    def on_prompt_input_bar_update_pinned_requested(
        self, event: PromptInputBar.UpdatePinnedRequested
    ) -> None:
        self.update_requests.append(event)

    def on_prompt_input_bar_save_as_xprompt_requested(
        self, event: PromptInputBar.SaveAsXpromptRequested
    ) -> None:
        self.save_xprompt_requests.append(event)

    def on_prompt_input_bar_cancelled(self, event: PromptInputBar.Cancelled) -> None:
        self.cancelled.append(event)


def entry_pairs(
    bar: PromptInputBar, *, via_ctrl_g: bool = False
) -> list[tuple[str, str]]:
    return [
        (entry.key, entry.label)
        for entry in bar.g_prefix_hint_entries(via_ctrl_g=via_ctrl_g)
    ]


def hint_panel(bar: PromptInputBar) -> Static:
    return bar.query_one("#prompt-g-prefix-hints", Static)
