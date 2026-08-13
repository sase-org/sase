"""Widget coverage for the pinned snippet pane's pane and bar frames."""

from __future__ import annotations

from pathlib import Path

from textual.color import Color

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import XPromptBinding
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.highlight_theme import ACE_THEME_NAME
from tests.ace.tui.widgets.prompt_stack_submit_cancel_test_support import CaptureApp
from tests.ace.tui.widgets.test_prompt_stack_snippet_pane_lifecycle import (
    _name_result,
    _open_snippet,
)

_ROOT = Path(__file__).resolve().parents[4]


class _StyledCaptureApp(CaptureApp):
    """Capture prompt events while loading the production prompt-bar styles."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def __init__(self, initial_value: str = "") -> None:
        super().__init__(initial_value)
        self.theme = ACE_THEME_NAME


def _pane(bar: PromptInputBar, index: int) -> PromptTextArea:
    item = bar._stack.items[index]
    return bar.query_one(f"#{bar._pane_id(item)}", PromptTextArea)


def _border_color(bar: PromptInputBar) -> Color:
    return bar.styles.border_top[1]


async def test_focused_snippet_fill_matches_focused_agent_fill(
    tmp_path: Path,
) -> None:
    app = _StyledCaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        focused_agent_fill = bar.active_text_area().background_colors[1]

        await _open_snippet(pilot, bar, _name_result(tmp_path))

        assert bar.active_text_area().background_colors[1] == focused_agent_fill


async def test_parked_snippet_fill_matches_inactive_agent_fill(
    tmp_path: Path,
) -> None:
    app = _StyledCaptureApp("first\n---\nsecond")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(pilot, bar, _name_result(tmp_path))

        bar.focus_item(0)
        await pilot.pause()

        assert _pane(bar, 2).background_colors[1] == _pane(bar, 1).background_colors[1]


async def test_snippet_frame_follows_focus_and_close(tmp_path: Path) -> None:
    app = _StyledCaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(pilot, bar, _name_result(tmp_path))

        assert bar.has_class("snippet-mode")
        assert bar.has_class("snippet-safe")
        assert not bar.has_class("snippet-dirty")

        bar.focus_item(0)
        await pilot.pause()

        assert not bar.has_class("snippet-mode")
        assert not bar.has_class("snippet-safe")
        assert not bar.has_class("snippet-dirty")

        snippet_index = bar._stack.snippet_index
        assert snippet_index is not None
        bar.focus_item(snippet_index)
        await pilot.pause()

        assert bar.has_class("snippet-mode")
        assert bar.has_class("snippet-safe")
        assert not bar.has_class("snippet-dirty")

        assert bar.close_snippet_target("discarded")
        await pilot.pause()
        await pilot.pause()

        assert not bar.has_class("snippet-mode")
        assert not bar.has_class("snippet-safe")
        assert not bar.has_class("snippet-dirty")


async def test_snippet_frame_escalates_only_existing_dirty_target(
    tmp_path: Path,
) -> None:
    app = _StyledCaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )

        bar.active_text_area().text = "edited"
        await pilot.pause()

        assert bar.has_class("snippet-mode")
        assert bar.has_class("snippet-dirty")
        assert not bar.has_class("snippet-safe")

        assert bar.close_snippet_target("discarded")
        await pilot.pause()
        await pilot.pause()
        await _open_snippet(pilot, bar, _name_result(tmp_path, trigger="brand-new"))

        bar.active_text_area().text = "new draft"
        await pilot.pause()

        assert bar.has_class("snippet-mode")
        assert bar.has_class("snippet-safe")
        assert not bar.has_class("snippet-dirty")


async def test_snippet_frame_takes_precedence_over_xprompt_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "review.md"
    source.write_text("agent prompt\n", encoding="utf-8")
    binding = XPromptBinding.for_file(source, reference="#review")
    app = _StyledCaptureApp("agent prompt")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar.load_stack_from_xprompt_markdown("agent prompt\n", binding=binding)
        await pilot.pause()
        await pilot.pause()
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )

        assert bar.has_class("xprompt-target")
        assert bar.styles.border_top[0] == "double"
        assert _border_color(bar) == Color.parse(app.get_css_variables()["primary"])

        bar.active_text_area().text = "edited"
        await pilot.pause()

        assert not bar.has_class("dirty")
        assert bar.has_class("snippet-dirty")
        assert bar.styles.border_top[0] == "double"
        assert _border_color(bar) == Color.parse(app.get_css_variables()["warning"])
