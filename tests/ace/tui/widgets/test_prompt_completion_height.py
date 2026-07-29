"""Regression tests for prompt completion panel height reservation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import (
    COMPLETION_PANEL_CONTENT_ROWS,
    CompletionCandidate,
    completion_scroll_offset,
    completion_visible_rows,
)
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


async def test_last_candidate_highlight_stays_inside_rendered_window() -> None:
    app = _StyledPromptBarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)

        candidates = [_candidate(index) for index in range(15)]
        selected_index = len(candidates) - 1
        bar.show_file_completions(
            "",
            candidates,
            selected_index=selected_index,
            scroll_offset=completion_scroll_offset(len(candidates), selected_index),
        )
        await pilot.pause()

        lines = panel.render().plain.splitlines()
        assert any(
            line.startswith("▸") and candidates[selected_index].display in line
            for line in lines
        )
        assert len(lines) <= COMPLETION_PANEL_CONTENT_ROWS
        assert panel.styles.max_height.value == 10
        assert panel.region.height <= 10


def test_row_budget_reserves_overflow_and_group_rule_lines() -> None:
    assert completion_visible_rows(3) == COMPLETION_PANEL_CONTENT_ROWS
    assert completion_visible_rows(COMPLETION_PANEL_CONTENT_ROWS) == (
        COMPLETION_PANEL_CONTENT_ROWS
    )
    # Overflowing candidates give up one row to the "N more" indicator.
    assert completion_visible_rows(COMPLETION_PANEL_CONTENT_ROWS + 1) == (
        COMPLETION_PANEL_CONTENT_ROWS - 1
    )
    # A group rule claims another content line.
    assert completion_visible_rows(3, group_rule=True) == (
        COMPLETION_PANEL_CONTENT_ROWS - 1
    )
    assert completion_visible_rows(15, group_rule=True) == (
        COMPLETION_PANEL_CONTENT_ROWS - 2
    )


def test_scroll_offset_keeps_selection_within_budget() -> None:
    for group_rule in (False, True):
        budget = completion_visible_rows(15, group_rule=group_rule)
        for selected_index in range(15):
            offset = completion_scroll_offset(15, selected_index, group_rule=group_rule)
            assert offset <= selected_index < offset + budget


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
