"""Regression tests for prompt completion panel height reservation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

_ROOT = Path(__file__).resolve().parents[4]


class _StyledPromptBarApp(App[None]):
    """Minimal prompt-bar app with production prompt CSS loaded."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_value="hello", id="prompt-input-bar")


def _candidate(index: int) -> CompletionCandidate:
    name = f"candidate-{index}"
    return CompletionCandidate(
        display=name,
        insertion=name,
        is_dir=False,
        name=name,
    )


def _style_height_value(value: Any) -> int:
    scalar_value = getattr(value, "value", value)
    return int(scalar_value)


async def test_long_completion_panel_reservation_matches_css_cap() -> None:
    app = _StyledPromptBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "",
            [_candidate(index) for index in range(15)],
            selected_index=0,
        )
        await pilot.pause()

        margin_bottom = panel.styles.margin.bottom
        assert panel.styles.max_height.value == 10
        assert panel.region.height == 10
        assert bar._completion_line_count == panel.region.height + margin_bottom
        assert _style_height_value(bar.styles.height) == (
            bar._get_visual_line_count() + 2 + bar._completion_line_count
        )


async def test_short_completion_panel_reservation_is_unchanged() -> None:
    app = _StyledPromptBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        bar.show_file_completions(
            "",
            [_candidate(index) for index in range(3)],
            selected_index=0,
        )
        await pilot.pause()

        margin_bottom = panel.styles.margin.bottom
        assert bar._completion_line_count == 6
        assert bar._completion_line_count == panel.region.height + margin_bottom
        assert _style_height_value(bar.styles.height) == (
            bar._get_visual_line_count() + 2 + bar._completion_line_count
        )
