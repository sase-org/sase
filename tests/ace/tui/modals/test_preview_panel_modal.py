"""Tests for the prompt preview modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload


class _PreviewModalTestApp(App[None]):
    def __init__(self, payload: PreviewPayload) -> None:
        super().__init__()
        self.payload = payload

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(PreviewPanelModal(self.payload))


def _payload() -> PreviewPayload:
    return PreviewPayload(
        kind_label="file",
        icon="@",
        title="src/example.py",
        source_path="/tmp/src/example.py",
        content="\n".join(f"print({idx})" for idx in range(120)),
        lexer="python",
    )


async def test_preview_modal_scrolls_and_closes() -> None:
    app = _PreviewModalTestApp(_payload())

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        scroll = modal.query_one("#preview-scroll")

        await pilot.press("ctrl+d")
        await pilot.pause()
        assert scroll.scroll_y > 0

        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0

        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_y > 0

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen_stack[-1], PreviewPanelModal)
