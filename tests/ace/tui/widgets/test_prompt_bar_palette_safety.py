"""Guard prompt-bar colors against terminal-palette remapping.

In Flexoki, ``$primary 12%`` over ``$surface`` flattened to ``#1C232A``, which
downgrades to xterm-256 index 16.  Base16-style terminal palettes commonly
remap slots 16-21, turning that near-black snippet fill into a salmon slab.
"""

from __future__ import annotations

from pathlib import Path

from rich.color import Color as RichColor
from rich.color import ColorSystem
from textual.color import Color

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import XPromptBinding
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.widgets.test_prompt_stack_snippet_pane_frame import (
    _StyledCaptureApp,
)
from tests.ace.tui.widgets.test_prompt_stack_snippet_pane_lifecycle import (
    _name_result,
    _open_snippet,
)


def _pane(bar: PromptInputBar, index: int) -> PromptTextArea:
    item = bar._stack.items[index]
    return bar.query_one(f"#{bar._pane_id(item)}", PromptTextArea)


def _assert_opaque(label: str, color: Color) -> None:
    assert color.a == 1.0, f"{label} resolves to translucent {color}"


def _assert_palette_safe(label: str, color: Color) -> None:
    index = RichColor.parse(color.hex).downgrade(ColorSystem.EIGHT_BIT).number
    assert index is None or not (16 <= index <= 21), (
        f"{label} resolves to {color.hex}, which downgrades to xterm-256 index "
        f"{index}; slots 16-21 are remapped by base16-style terminal palettes."
    )


async def test_prompt_bar_resolved_colors_are_palette_safe(tmp_path: Path) -> None:
    source = tmp_path / "review.md"
    source.write_text("first\n---\nsecond\n", encoding="utf-8")
    binding = XPromptBinding.for_file(source, reference="#review")
    app = _StyledCaptureApp("first\n---\nsecond")
    fill_styles: list[tuple[str, Color]] = []
    flattened_fills: list[tuple[str, Color]] = []
    borders: list[tuple[str, Color]] = []

    def record_pane(label: str, pane: PromptTextArea) -> None:
        fill_styles.append((f"{label} background style", pane.styles.background))
        flattened_fills.append((f"{label} flattened fill", pane.background_colors[1]))
        borders.append((f"{label} left border", pane.styles.border_left[1]))

    def record_frame(label: str, bar: PromptInputBar) -> None:
        borders.append((f"{label} top border", bar.styles.border_top[1]))

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        record_pane("agent active", _pane(bar, 1))
        record_pane("agent inactive", _pane(bar, 0))
        record_frame("plain frame", bar)

        bar.load_stack_from_xprompt_markdown(
            "first\n---\nsecond",
            binding=binding,
        )
        await pilot.pause()
        await pilot.pause()
        record_frame("xprompt-target frame", bar)

        await _open_snippet(pilot, bar, _name_result(tmp_path))
        record_pane("snippet active", bar.active_text_area())
        record_frame("snippet safe frame", bar)

        bar.focus_item(0)
        await pilot.pause()
        snippet_index = bar._stack.snippet_index
        assert snippet_index is not None
        record_pane("snippet parked", _pane(bar, snippet_index))

        assert bar.close_snippet_target("discarded")
        await pilot.pause()
        await pilot.pause()
        await _open_snippet(
            pilot,
            bar,
            _name_result(tmp_path, existing_body="loaded"),
            destination_exists=True,
        )
        bar.active_text_area().text = "edited"
        await pilot.pause()
        record_frame("snippet dirty frame", bar)

    for label, color in fill_styles:
        _assert_opaque(label, color)
    for label, color in flattened_fills:
        _assert_opaque(label, color)
        _assert_palette_safe(label, color)
    for label, color in borders:
        _assert_opaque(label, color)
        _assert_palette_safe(label, color)
