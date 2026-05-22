"""Regression tests for PromptInputBar detach race in `_update_height`."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class PromptDetachTestApp(App[None]):
    """Minimal app that hosts a single PromptInputBar."""

    def compose(self) -> ComposeResult:
        yield PromptInputBar("hello", id="prompt-input-bar")


async def test_update_height_after_synchronous_detach_does_not_crash() -> None:
    """Mirrors `_detach_prompt_bar`: synchronously remove the bar from its
    parent's `_nodes`, then invoke `_update_height` (as a deferred
    `call_after_refresh` would). The bar should bail out instead of raising
    `NoScreen`."""
    app = PromptDetachTestApp()
    async with app.run_test():
        bar = app.query_one("#prompt-input-bar", PromptInputBar)
        parent = bar._parent
        assert parent is not None
        parent._nodes._remove(bar)  # type: ignore[attr-defined]
        await bar.remove()

        bar._update_height()
