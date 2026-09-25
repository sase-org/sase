"""Chrome-layout tests for the ``:`` Command Line (phase sase-17x.13.8).

Covers the border chrome (title, chip, key hints and running count on the
frame borders, recomposed on resize) and the floating completion popup
(anchored above the input at the replace-span column, never reflowing the
transcript).
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch as mock_patch

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.command_line.chrome import _compose_border_label
from sase.ace.tui.command_line.context import (
    CommandLineContext,
    middle_truncate,
    working_context_chip,
)
from sase.ace.tui.command_line.popup_layout import (
    PEEK_GAP,
    POPUP_MAX_WIDTH,
    POPUP_MIN_WIDTH,
    POPUP_TEXT_INSET,
    popup_content_width,
    popup_geometry,
)
from sase.history import command_line as history_store
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text

_LONG_CONTEXT = CommandLineContext(
    cwd="/home/test/" + "/".join(f"projects{n}" for n in range(8)), project="sase"
)


@pytest.fixture(scope="module")
def grammar_handle() -> Any:
    """Return an in-process ``CommandLineGrammar`` (no spec subprocess)."""
    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        return CommandLineGrammar.from_spec_json(json.dumps(build_spec().to_json()))
    except AttributeError:
        pytest.skip("installed sase_core_rs wheel predates CommandLineGrammar")


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the history store on a temp file so RECENT rows stay deterministic."""
    monkeypatch.setattr(
        history_store, "_history_file_override", tmp_path / "history.json"
    )


# -- pure: label composition ------------------------------------------------------


def _compose(left: str, right: str, width: int, **kwargs: Any) -> Text:
    return _compose_border_label(Text(left), Text(right), width, **kwargs)


def test_label_spans_the_width_with_both_ends_aligned() -> None:
    """Left text, a run of border dashes, then the right text fill the label."""
    label = _compose("❯ Command Line", "⌂ +sase", 60).plain
    assert cell_len(label) == 60
    assert label.startswith("❯ Command Line ─")
    assert label.endswith("─ ⌂ +sase")


def test_label_without_right_text_is_left_unpadded() -> None:
    """Textual pads a short label with border dashes itself."""
    assert _compose("hints", "", 40).plain == "hints"


def test_right_text_is_middle_truncated_to_the_room_left() -> None:
    """The chip keeps both of its ends when the title leaves little room."""
    chip = "⌂ +sase · /home/user/projects/github/sase-org/sase"
    label = _compose("❯ Command Line", chip, 44, middle_right=True)
    assert cell_len(label.plain) == 44
    assert label.plain.startswith("❯ Command Line ─")
    tail = label.plain.split("─ ", 1)[1]
    assert tail.startswith("⌂ +sase") and tail.endswith("sase-org/sase")
    assert "…" in tail


def test_keep_right_ellipsizes_the_left_text_instead() -> None:
    """The bottom border keeps ``N running`` whole and elides the hints."""
    hints = "⏎ run · ⇥ complete · ↑↓ history · ^R search · esc hide"
    label = _compose(hints, "3 running", 40, keep_right=True)
    assert cell_len(label.plain) == 40
    assert label.plain.endswith("─ 3 running")
    assert "…" in label.plain.split(" ─", 1)[0]
    roomy = _compose("hints", "3 running", 40, keep_right=True)
    assert roomy.plain.startswith("hints ─") and roomy.plain.endswith("─ 3 running")
    # No room for the left text at all: the right text stays right-aligned.
    only_right = _compose(hints, "3 running", 12, keep_right=True)
    assert cell_len(only_right.plain) == 12
    assert only_right.plain.startswith("─") and only_right.plain.endswith(" 3 running")


def test_right_text_is_dropped_when_no_room_remains() -> None:
    """A title that leaves fewer than a handful of cells hides the right side."""
    label = _compose("❯ Command Line", "⌂ +sase · /a/b/c", 20)
    assert label.plain == "❯ Command Line"


def test_left_text_is_ellipsized_when_it_alone_overflows() -> None:
    """The left text has priority but never overflows the label."""
    label = _compose("⏎ run · ⇥ complete · ↑↓ history", "0 running", 12)
    assert cell_len(label.plain) <= 12
    assert label.plain.endswith("…")


def test_fill_dashes_carry_the_fill_style() -> None:
    """The dashes take the border color so the edge reads as one line."""
    label = _compose("a", "b", 20, fill_style="#112233")
    dashes = [span for span in label.spans if str(span.style) == "#112233"]
    assert len(dashes) == 1
    assert set(label.plain[dashes[0].start : dashes[0].end]) == {"─"}


def test_middle_truncate_elides_the_middle() -> None:
    """Both ends survive; the ellipsis takes the middle."""
    assert middle_truncate("abcdefghij", 10) == "abcdefghij"
    assert middle_truncate("abcdefghij", 7) == "abc…hij"
    assert middle_truncate("abcdefghij", 1) == "…"
    assert middle_truncate("abcdefghij", 0) == ""


def test_chip_width_none_skips_truncation() -> None:
    """The frame elides the chip itself, so the screen passes it whole."""
    whole = working_context_chip(_LONG_CONTEXT, max_width=None)
    assert whole.startswith("⌂ +sase · /home/test/projects0")
    assert len(whole) > 48
    assert len(working_context_chip(_LONG_CONTEXT)) <= 48


# -- pure: popup geometry -------------------------------------------------------


def test_popup_content_width_measures_the_widest_row() -> None:
    """Row width mirrors glyph, value, ``[badge]``, description and ``sel``."""
    narrow = {"display": "abc"}
    wide = {"display": "abc", "badge": "cmd", "description": "does a thing"}
    assert popup_content_width([]) == 0
    assert popup_content_width([narrow]) < popup_content_width([wide])
    assert popup_content_width([narrow, wide]) == popup_content_width([wide])
    selected = dict(wide, selected=True)
    assert popup_content_width([selected]) == popup_content_width([wide]) + 5


def test_popup_geometry_aligns_the_text_with_the_replace_column() -> None:
    """The candidate text (not the card edge) lands on the replace column."""
    geometry = popup_geometry(anchor=20, content=50, peek=0, available=113)
    assert geometry.x == 20 - POPUP_TEXT_INSET
    assert geometry.card_width == 50
    assert geometry.peek_width == 0


def test_popup_geometry_clamps_inside_the_frame() -> None:
    """A far-right anchor slides the card left; a far-left one stops at zero."""
    right = popup_geometry(anchor=110, content=50, peek=0, available=113)
    assert right.x + right.card_width == 113
    assert popup_geometry(anchor=0, content=50, peek=0, available=113).x == 0
    bounded = popup_geometry(anchor=0, content=500, peek=0, available=200)
    assert bounded.card_width == POPUP_MAX_WIDTH
    floored = popup_geometry(anchor=0, content=3, peek=0, available=113)
    assert floored.card_width == POPUP_MIN_WIDTH


def test_popup_geometry_shrinks_the_card_before_the_peek() -> None:
    """The doc-peek keeps its width while the card gives way, then it drops."""
    fits = popup_geometry(anchor=10, content=100, peek=60, available=134)
    assert fits.peek_width == 60
    assert fits.card_width + PEEK_GAP + fits.peek_width <= 134
    assert fits.x + fits.card_width + PEEK_GAP + fits.peek_width <= 134
    dropped = popup_geometry(anchor=10, content=100, peek=60, available=90)
    assert dropped.peek_width == 0
    assert dropped.card_width == 90


# -- pilot: panel harness -----------------------------------------------------------


@asynccontextmanager
async def _panel(
    grammar: Any,
    *,
    size: tuple[int, int] = (120, 40),
    context: CommandLineContext | None = None,
) -> AsyncGenerator[tuple[Any, Any]]:
    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        mock_patch(
            "sase.ace.tui.command_line.screen.resolve_working_context",
            lambda _app, _session: (
                context
                or CommandLineContext(cwd="/home/test/projects/sase", project="sase")
            ),
        ),
    ):
        async with AcePage(
            query="test_feature", patches=[make_patch()], size=size
        ) as page:
            page.app._command_line_grammar = grammar
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            await page.pause()
            await page.pause()
            yield page, screen


async def _type(page: Any, screen: Any, line: str) -> Any:
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = screen.query_one(CommandLineInput)
    widget.set_line(line)
    await page.pause()
    return widget


def _frame(screen: Any) -> Any:
    from sase.ace.tui.command_line.chrome import CommandLineFrame

    return screen.query_one(CommandLineFrame)


# -- pilot: border chrome -------------------------------------------------------------


async def test_chrome_lives_on_the_borders_not_in_rows(grammar_handle: Any) -> None:
    """The title/chip sit on the top border, hints/count on the bottom one."""
    async with _panel(grammar_handle) as (page, screen):
        assert not screen.query("#command-line-title-row")
        assert not screen.query("#command-line-status-row")
        frame = _frame(screen)
        top, bottom = frame.top_label.plain, frame.bottom_label.plain
        assert top.startswith("❯ Command Line ─")
        assert top.endswith("⌂ +sase · /home/test/projects/sase")
        assert bottom.startswith("⏎ run · ⇥ complete")
        assert bottom.endswith("─ 0 running")
        # The labels reach the drawn borders.
        drawn = page_svg_text(page)
        assert "Command Line" in drawn and "0 running" in drawn


async def test_running_count_and_hints_follow_state_on_the_border(
    grammar_handle: Any,
) -> None:
    """The bottom border tracks the running count and the menu/input hints."""
    from sase.ace.tui.command_line.session import command_line_session_for

    async with _panel(grammar_handle) as (page, screen):
        frame = _frame(screen)
        session = command_line_session_for(page.app)
        block = session.add_block("agent wait x")
        block.status = "running"
        block.proc_id = "proc-1"
        screen.refresh_transcript()
        assert frame.bottom_label.plain.endswith("─ 1 running")
        await _type(page, screen, "bead ")
        await page.press("tab")
        await page.press("tab")
        assert frame.bottom_label.plain.startswith("⏎ accept · ↑↓ move")


@pytest.mark.parametrize(("wide", "narrow"), [((140, 40), (80, 24))])
async def test_chrome_recomposes_and_stays_aligned_on_resize(
    grammar_handle: Any, wide: tuple[int, int], narrow: tuple[int, int]
) -> None:
    """Title and hints survive a resize: both ends stay aligned at each width."""
    async with _panel(grammar_handle, size=wide, context=_LONG_CONTEXT) as (
        page,
        screen,
    ):
        frame = _frame(screen)
        widths: list[int] = []
        chips: list[str] = []
        for size in (wide, narrow, wide):
            await page._pilot.resize_terminal(*size)
            await page.pause()
            await page.pause()
            budget = frame.outer_size.width - 6
            widths.append(frame.outer_size.width)
            for label in (frame.top_label.plain, frame.bottom_label.plain):
                assert cell_len(label) == budget
            assert frame.top_label.plain.startswith("❯ Command Line ─")
            assert frame.bottom_label.plain.endswith("─ 0 running")
            chips.append(frame.top_label.plain.split("─ ", 1)[1])
        assert widths[0] == widths[2] > widths[1]
        # The chip is whole when it fits and middle-truncated when it does not.
        assert "…" not in chips[0] and chips[0].endswith("projects7")
        assert "…" in chips[1] and chips[1].startswith("⌂ +sase")
        assert chips[1].endswith("projects7")
        assert chips[2] == chips[0]


async def test_frame_width_cap_and_full_height_toggle_keep_the_labels(
    grammar_handle: Any,
) -> None:
    """The frame is 96% wide (max 160), 65% tall, and ``ctrl+t`` fills the height."""
    async with _panel(grammar_handle, size=(200, 40)) as (page, screen):
        frame = _frame(screen)
        assert frame.outer_size.width == 160
        assert frame.outer_size.height == 26  # 65% of 40 rows
        await page._pilot.resize_terminal(100, 40)
        await page.pause()
        assert frame.outer_size.width == 96
        await page.press("ctrl+t")
        await page.pause()
        assert frame.outer_size.height == 40
        assert cell_len(frame.top_label.plain) == frame.outer_size.width - 6
        assert cell_len(frame.bottom_label.plain) == frame.outer_size.width - 6
        await page.press("ctrl+t")
        await page.pause()
        assert frame.outer_size.height == 26


# -- pilot: floating popup -----------------------------------------------------------


async def test_popup_floats_over_the_transcript_without_reflowing_it(
    grammar_handle: Any,
) -> None:
    """Opening and closing the popup never moves the frame or the transcript."""
    from sase.ace.tui.command_line.popup import CommandLinePopup

    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "zzzzzz")
        frame, transcript = _frame(screen), screen.transcript
        popup_float = screen.query_one("#command-line-popup-float")
        assert popup_float.display is False
        before = (frame.region, transcript.region)

        await _type(page, screen, "bead ")
        popup = screen.query_one(CommandLinePopup)
        card = screen.query_one("#command-line-popup-card")
        assert popup.display is True and popup_float.display is True
        assert (frame.region, transcript.region) == before
        # The card overlaps the transcript's rows and sits right above the input.
        assert card.region.overlaps(transcript.region)
        assert (
            card.region.bottom == screen.query_one("#command-line-input-row").region.y
        )
        assert frame.content_region.contains_region(card.region)

        await _type(page, screen, "zzzzzz")
        assert popup_float.display is False
        assert (frame.region, transcript.region) == before


async def test_popup_column_tracks_the_replace_span(grammar_handle: Any) -> None:
    """The candidate text lines up with the span that Tab would replace."""
    async with _panel(grammar_handle) as (page, screen):
        card = screen.query_one("#command-line-popup-card")
        for line in ("bead ", "bead list --st"):
            widget = await _type(page, screen, line)
            state = screen._popup_state
            cursor = widget.cursor_location[1]
            replace_column = widget.cursor_screen_offset.x - (
                cursor - state.replace_start
            )
            assert card.region.x + POPUP_TEXT_INSET == replace_column, line
        # The two slots start at different columns, so the card moved with it.
        assert state.replace_start == len("bead list ")


async def test_popup_clamps_inside_a_narrow_frame(grammar_handle: Any) -> None:
    """A slot far to the right slides the card left instead of clipping it."""
    async with _panel(grammar_handle, size=(80, 30)) as (page, screen):
        await _type(page, screen, "bead list --status open --st")
        frame = _frame(screen)
        card = screen.query_one("#command-line-popup-card")
        assert screen.query_one("#command-line-popup-float").display is True
        assert frame.content_region.contains_region(card.region)


async def test_popup_reclamps_when_the_terminal_shrinks(grammar_handle: Any) -> None:
    """A resize with the popup open keeps the card inside the narrower frame."""
    async with _panel(grammar_handle, size=(140, 40)) as (page, screen):
        await _type(page, screen, "bead list --status open --st")
        frame = _frame(screen)
        card = screen.query_one("#command-line-popup-card")
        wide_x = card.region.x
        await page._pilot.resize_terminal(80, 30)
        await page.pause()
        await page.pause()
        assert frame.content_region.contains_region(card.region)
        assert card.region.x < wide_x


async def test_doc_peek_shares_the_float_and_fits_beside_the_card(
    grammar_handle: Any,
) -> None:
    """On a wide terminal the peek sits right of the card, inside the frame."""
    async with _panel(grammar_handle, size=(160, 40)) as (page, screen):
        await _type(page, screen, "bead ")
        await page.press("tab")
        await page.press("tab")
        peek = screen.query_one("#command-line-doc-peek")
        card = screen.query_one("#command-line-popup-card")
        assert peek.display is True
        assert card.region.right + PEEK_GAP <= peek.region.x
        frame = _frame(screen)
        assert frame.content_region.contains_region(peek.region)
        assert frame.content_region.contains_region(card.region)
