"""Regression tests for prompt completion panel height reservation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from rich.cells import cell_len
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import (
    COMPLETION_PANEL_CONTENT_ROWS,
    CompletionCandidate,
    completion_scroll_offset,
    completion_visible_rows,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import build_xprompt_assist_entries
from sase.ace.tui.widgets.xprompt_completion import build_xprompt_completion_candidates

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


def _long_skill_candidates() -> list[CompletionCandidate]:
    candidates, _ = build_xprompt_completion_candidates(
        "/sase_monitor",
        entries=build_xprompt_assist_entries(),
    )
    assert candidates, "expected packaged /sase_monitor skill"
    metadata = candidates[0].metadata
    description = getattr(metadata, "description", None) or ""
    assert "\n" not in description
    assert cell_len(description) > 220
    return candidates


def _assert_long_completion_keeps_editor_visible(
    app: App[None],
    bar: PromptInputBar,
) -> None:
    panel = bar.query_one("#prompt-completion", Static)
    editor = bar.active_text_area()
    content = panel.content
    assert isinstance(content, Text)
    logical_lines = [line for line in content.plain.splitlines() if line]
    inner_width = panel.content_size.width
    screen_height = app.size.height

    assert inner_width > 0
    assert any(cell_len(line) > inner_width for line in logical_lines)
    assert panel.styles.text_wrap == "nowrap"
    assert panel.styles.text_overflow == "ellipsis"
    assert panel.visual.get_height(panel.styles, inner_width) == len(logical_lines)

    margin_bottom = panel.styles.margin.bottom
    assert bar._completion_line_count == panel.region.height + margin_bottom
    assert bar._get_visual_line_count() >= 1
    assert _style_height_value(bar.styles.height) == (
        bar._get_visual_line_count() + 2 + bar._completion_line_count
    )
    assert bar.region.height >= panel.region.height + margin_bottom + 3
    assert isinstance(editor, PromptTextArea)
    assert editor.region.height >= 1
    assert editor.region.y < screen_height
    assert editor.region.bottom <= screen_height
    assert bar.region.contains_region(editor.region)
    assert app.screen.region.contains_region(editor.region)


@pytest.mark.parametrize("width", [220, 120])
async def test_long_skill_description_stays_one_visual_row(width: int) -> None:
    app = _StyledPromptBarApp()
    async with app.run_test(size=(width, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        bar.show_file_completions(
            "/sase_monitor",
            _long_skill_candidates(),
            selected_index=0,
            completion_kind="xprompt",
        )
        await pilot.pause()
        _assert_long_completion_keeps_editor_visible(app, bar)


async def test_long_skill_description_stays_one_visual_row_on_resize() -> None:
    app = _StyledPromptBarApp()
    async with app.run_test(size=(220, 24)) as pilot:
        bar = app.query_one(PromptInputBar)
        bar.show_file_completions(
            "/sase_monitor",
            _long_skill_candidates(),
            selected_index=0,
            completion_kind="xprompt",
        )
        await pilot.pause()
        _assert_long_completion_keeps_editor_visible(app, bar)

        await pilot.resize_terminal(120, 24)
        await pilot.pause()
        _assert_long_completion_keeps_editor_visible(app, bar)
