"""Widget tests for the prompt input bar's cursor line/column readout."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.widgets._prompt_input_bar_stack_separator import (
    PromptStackSeparator,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar

from ._prompt_input_bar_stack_helpers import _PromptBarApp


def _soft_completion(display: str = "suggested continuation") -> PromptSoftCompletion:
    return PromptSoftCompletion(
        candidate=CompletionCandidate(
            display=display, insertion=display, is_dir=False, name=display
        ),
        completion_kind="file",
        replacement_start=0,
        replacement_end=0,
        replacement_token="",
        display=display,
    )


def _subtitle_text(bar: PromptInputBar) -> Text:
    """Return the composed subtitle for *bar*'s current base + readout state.

    ``border_subtitle`` round-trips through Textual's markup serialization
    once a ``Text`` is assigned to it, so tests recompute the same ``Text``
    the bar just assigned instead of parsing that serialization back out.
    """
    return bar._render_subtitle(bar._subtitle_base)


# --- solo pane ---------------------------------------------------------------


async def test_solo_pane_subtitle_shows_readout() -> None:
    """On mount the cursor parks at the end of the seeded text (``_cursor_to_end``)."""
    app = _PromptBarApp("hello")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert _subtitle_text(bar).plain.endswith("Ln 1, Col 6")


async def test_solo_pane_readout_tracks_cursor_motion() -> None:
    app = _PromptBarApp("one\ntwo\nthree")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()
        text_area.cursor_location = (1, 2)
        await pilot.pause()
        assert _subtitle_text(bar).plain.endswith("Ln 2, Col 3")


async def test_solo_pane_readout_tracks_typing() -> None:
    app = _PromptBarApp("")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert _subtitle_text(bar).plain.endswith("Ln 1, Col 1")

        await pilot.press("h", "i")
        await pilot.pause()
        assert _subtitle_text(bar).plain.endswith("Ln 1, Col 3")


async def test_solo_pane_feedback_mode_shows_readout() -> None:
    """The readout is not prompt-mode-only: feedback mode carries it too."""
    app = _PromptBarApp("note", mode="feedback")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        assert _subtitle_text(bar).plain.endswith("Ln 1, Col 5")


# --- multi-pane ----------------------------------------------------------------


async def test_multi_pane_parked_separators_carry_readout_active_does_not() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        separators = list(app.query(PromptStackSeparator))
        assert len(separators) == len(bar._stack.items) == 3

        with_readout = [sep for sep in separators if sep.position is not None]
        without_readout = [sep for sep in separators if sep.position is None]
        assert len(with_readout) == len(bar._stack.items) - 1
        assert len(without_readout) == 1
        assert without_readout[0].active


async def test_focus_item_moves_the_readout() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        items = bar._stack.items
        sep_0 = app.query_one(f"#{bar._sep_id(items[0])}", PromptStackSeparator)
        sep_2 = app.query_one(f"#{bar._sep_id(items[2])}", PromptStackSeparator)
        assert sep_2.position is None
        assert sep_0.position is not None

        bar.focus_item(0)
        await pilot.pause()

        assert sep_0.position is None
        assert sep_2.position is not None
        assert _subtitle_text(bar).plain.endswith("Ln 1, Col 1")


async def test_parked_position_is_truthful_across_focus_round_trip() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        items = bar._stack.items

        bar.focus_item(1)
        await pilot.pause()
        pane_1 = app.query_one(
            f"#{bar._pane_id(items[1])}", type(bar.active_text_area())
        )
        pane_1.cursor_location = (0, 3)
        await pilot.pause()

        bar.focus_item(0)
        await pilot.pause()

        sep_1 = app.query_one(f"#{bar._sep_id(items[1])}", PromptStackSeparator)
        assert sep_1.position == (1, 4)


# --- soft completion -----------------------------------------------------------


async def test_soft_completion_visible_still_shows_readout() -> None:
    """Asserts right after each call: a background completion timer would
    otherwise race the harness and clear the soft suggestion during a pause.
    """
    app = _PromptBarApp("hello")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.show_soft_completion(_soft_completion())
        plain = _subtitle_text(bar).plain
        assert "accept" in plain
        assert plain.endswith("Ln 1, Col 6")

        bar.hide_soft_completion()
        plain = _subtitle_text(bar).plain
        assert "accept" not in plain
        assert plain.endswith("Ln 1, Col 6")


# --- vim mode coloring -----------------------------------------------------------


async def test_vim_mode_switch_recolors_subtitle_digits() -> None:
    app = _PromptBarApp("hello")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        text_area = bar.active_text_area()

        assert text_area._vim_mode == "insert"
        insert_subtitle = _subtitle_text(bar)
        insert_styles = [
            str(span.style)
            for span in insert_subtitle.spans
            if insert_subtitle.plain[span.start : span.end] == "1"
        ]
        assert insert_styles and all("#3AA99F" in style for style in insert_styles)

        await pilot.press("escape")
        await pilot.pause()
        assert text_area._vim_mode == "normal"
        normal_subtitle = _subtitle_text(bar)
        normal_styles = [
            str(span.style)
            for span in normal_subtitle.spans
            if normal_subtitle.plain[span.start : span.end] == "1"
        ]
        assert normal_styles and all("#D0A215" in style for style in normal_styles)


# --- narrow terminal -------------------------------------------------------------


async def test_narrow_terminal_subtitle_keeps_readout_and_truncates_hints() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(44, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        plain = _subtitle_text(bar).plain
        full_hints = bar.insert_mode_subtitle()

        # The readout survives narrowing in full ("second" is 6 chars, and the
        # cursor parks at its end on mount).
        assert plain.endswith("Ln 1, Col 7")
        # The hints were truncated to make room for it.
        assert not plain.startswith(full_hints)


async def test_narrow_terminal_separator_drops_readout_keeps_agent_label() -> None:
    app = _PromptBarApp("first\n---\nsecond\n---\nthird")

    async with app.run_test(size=(30, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        items = bar._stack.items
        sep_0 = app.query_one(f"#{bar._sep_id(items[0])}", PromptStackSeparator)
        assert sep_0.position is not None  # the model still has a position

        rendered = sep_0.render()
        assert "agent 1" in rendered.plain
        assert "Ln" not in rendered.plain
        assert "Col" not in rendered.plain


# --- no-op guard -------------------------------------------------------------


async def test_set_position_is_a_noop_when_unchanged() -> None:
    app = _PromptBarApp("first\n---\nsecond")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        items = bar._stack.items
        separator = app.query_one(f"#{bar._sep_id(items[0])}", PromptStackSeparator)

        calls = []
        original_refresh = separator.refresh

        def _spy_refresh(*args: object, **kwargs: object) -> object:
            calls.append((args, kwargs))
            return original_refresh(*args, **kwargs)

        separator.refresh = _spy_refresh  # type: ignore[method-assign]
        separator.set_position(separator.position, separator.vim_mode)

        assert calls == []
