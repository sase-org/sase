"""Transcript-scroll tests for the ``:`` Command Line.

Covers ``ctrl+d`` / ``ctrl+u`` half-page scrolling from INSERT and NORMAL
mode, follow-tail anchoring, and NORMAL-mode block selection scrolling.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch as mock_patch

import pytest

from sase.ace.tui.command_line.context import CommandLineContext
from sase.history import command_line as history_store


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


@asynccontextmanager
async def _panel(grammar: Any, *, size: tuple[int, int] = (120, 40)):
    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
        mock_patch(
            "sase.ace.tui.command_line.screen.resolve_working_context",
            lambda _app, _session: CommandLineContext(
                cwd="/home/test/projects/sase", project="sase"
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


def _seed_overflow(session: Any, *, blocks: int = 6, lines: int = 40) -> None:
    """Seed *blocks* expanded blocks with *lines* of output each."""
    for index in range(blocks):
        block = session.add_block(f"bead show sase-{index}")
        block.tail_text = "\n".join(f"line {index}-{n}" for n in range(lines))
        block.tail_loaded = True
        block.expanded = True


async def _seed_and_anchor(page: Any, screen: Any) -> Any:
    """Seed an overflowing transcript and pin it to the bottom."""
    from sase.ace.tui.command_line.session import command_line_session_for

    session = command_line_session_for(page.app)
    _seed_overflow(session)
    screen.refresh_transcript()
    try:
        screen.transcript.anchor()
    except Exception:  # noqa: BLE001 - anchor is best effort.
        pass
    await page.pause()
    await page.pause()
    assert screen.transcript.max_scroll_y > 0
    return session


async def test_panel_opens_anchored_at_bottom(grammar_handle: Any) -> None:
    """The panel opens with the transcript pinned to the newest output."""
    async with _panel(grammar_handle) as (page, screen):
        await _seed_and_anchor(page, screen)
        assert screen.transcript.scroll_y == screen.transcript.max_scroll_y


async def test_insert_scroll_keys_move_half_page_without_editing(
    grammar_handle: Any,
) -> None:
    """``ctrl+u`` scrolls up half the viewport; ``ctrl+d`` scrolls back down."""
    async with _panel(grammar_handle) as (page, screen):
        from sase.ace.tui.command_line.input import CommandLineInput

        await _seed_and_anchor(page, screen)
        widget = screen.query_one(CommandLineInput)
        widget.set_line("bead list")
        await page.pause()
        transcript = screen.transcript
        step = max(1, transcript.scrollable_content_region.height // 2)
        top = transcript.scroll_y
        assert top == transcript.max_scroll_y

        await page.press("ctrl+u")
        await page.pause()
        assert widget.text == "bead list"
        assert transcript.scroll_y == top - step

        await page.press("ctrl+d")
        await page.pause()
        assert widget.text == "bead list"
        assert transcript.scroll_y == transcript.max_scroll_y


async def test_scrolled_up_transcript_does_not_follow_until_bottom(
    grammar_handle: Any,
) -> None:
    """Appends stay put while scrolled up; reaching the bottom re-follows."""
    async with _panel(grammar_handle) as (page, screen):
        from sase.ace.tui.command_line.input import CommandLineInput
        from sase.ace.tui.command_line.session import command_line_session_for

        await _seed_and_anchor(page, screen)
        screen.query_one(CommandLineInput).set_line("bead list")
        await page.pause()
        transcript = screen.transcript
        session = command_line_session_for(page.app)

        await page.press("ctrl+u")
        await page.pause()
        parked = transcript.scroll_y
        assert parked < transcript.max_scroll_y

        block = session.add_block("bead list --status open")
        block.tail_text = "\n".join(f"new-{n}" for n in range(30))
        block.tail_loaded = True
        block.expanded = True
        screen.refresh_transcript()
        await page.pause()
        await page.pause()
        assert transcript.scroll_y == parked
        assert transcript.scroll_y < transcript.max_scroll_y

        # Extra presses past the bottom are no-ops that keep the follow
        # anchor (see test_ctrl_d_at_bottom_keeps_following), so drive with
        # a fixed press count and settle once instead of a pause loop.
        for _ in range(12):
            await page.press("ctrl+d")
        await page.pause()
        await page.pause()
        assert transcript.scroll_y == transcript.max_scroll_y

        tail = session.add_block("bead show sase-9")
        tail.tail_text = "\n".join(f"tail-{n}" for n in range(30))
        tail.tail_loaded = True
        tail.expanded = True
        screen.refresh_transcript()
        await page.pause()
        await page.pause()
        assert transcript.scroll_y == transcript.max_scroll_y


async def test_ctrl_d_at_bottom_keeps_following(grammar_handle: Any) -> None:
    """``ctrl+d`` at the bottom re-anchors instead of releasing the follow."""
    async with _panel(grammar_handle) as (page, screen):
        from sase.ace.tui.command_line.input import CommandLineInput
        from sase.ace.tui.command_line.session import command_line_session_for

        await _seed_and_anchor(page, screen)
        screen.query_one(CommandLineInput).set_line("bead list")
        await page.pause()
        transcript = screen.transcript
        await page.press("ctrl+d")
        await page.pause()
        assert transcript.scroll_y == transcript.max_scroll_y

        session = command_line_session_for(page.app)
        block = session.add_block("bead list")
        block.tail_text = "\n".join(f"more-{n}" for n in range(20))
        block.tail_loaded = True
        block.expanded = True
        screen.refresh_transcript()
        await page.pause()
        await page.pause()
        assert transcript.scroll_y == transcript.max_scroll_y


async def test_scroll_noop_without_overflow_still_follows_later(
    grammar_handle: Any,
) -> None:
    """``ctrl+u`` with nothing to scroll is a no-op and keeps the anchor."""
    async with _panel(grammar_handle) as (page, screen):
        from sase.ace.tui.command_line.input import CommandLineInput
        from sase.ace.tui.command_line.session import command_line_session_for

        transcript = screen.transcript
        assert transcript.max_scroll_y == 0
        screen.query_one(CommandLineInput).set_line("bead list")
        await page.pause()
        await page.press("ctrl+u")
        await page.pause()
        assert screen.query_one(CommandLineInput).text == "bead list"
        assert transcript.max_scroll_y == 0

        session = command_line_session_for(page.app)
        _seed_overflow(session)
        screen.refresh_transcript()
        await page.pause()
        await page.pause()
        assert transcript.max_scroll_y > 0
        assert transcript.scroll_y == transcript.max_scroll_y


async def test_normal_mode_scroll_matches_insert(grammar_handle: Any) -> None:
    """NORMAL mode scrolls the transcript instead of moving the cursor."""
    async with _panel(grammar_handle) as (page, screen):
        from sase.ace.tui.command_line.input import CommandLineInput

        await _seed_and_anchor(page, screen)
        widget = screen.query_one(CommandLineInput)
        widget.set_line("bead list with text")
        await page.pause()
        widget._enter_normal_mode()
        await page.pause()
        transcript = screen.transcript
        step = max(1, transcript.scrollable_content_region.height // 2)
        top = transcript.scroll_y
        await page.press("ctrl+u")
        await page.pause()
        assert widget.text == "bead list with text"
        assert transcript.scroll_y == top - step
        await page.press("ctrl+d")
        await page.pause()
        assert widget.text == "bead list with text"
        assert transcript.scroll_y == transcript.max_scroll_y


async def test_submit_after_scroll_reanchors_to_bottom(
    grammar_handle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Submitting a line after scrolling up pins the view to the new block."""
    from types import SimpleNamespace as _NS

    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.input import CommandLineInput
    from sase.ace.tui.command_line.session import command_line_session_for

    def _fake_submit(**kwargs: object) -> object:
        return _NS(proc_id="proc-scroll-submit-1")

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])

    def _mark_loaded(block: Any) -> bool:
        block.tail_loaded = True
        return True

    monkeypatch.setattr(screen_module, "load_block_tail_text", _mark_loaded)
    with mock_patch.object(screen_module, "submit_in_worker", side_effect=_fake_submit):
        async with _panel(grammar_handle) as (page, screen):
            await _seed_and_anchor(page, screen)
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead list")
            await page.pause()
            await page.press("ctrl+u")
            await page.pause()
            assert screen.transcript.scroll_y < screen.transcript.max_scroll_y
            screen.submit_current_line()
            await page.pause()
            await page.pause()
            session = command_line_session_for(page.app)
            assert len(session.blocks) == 7
            assert screen.transcript.scroll_y == screen.transcript.max_scroll_y


async def test_unbound_scroll_falls_through_to_editing(
    grammar_handle: Any,
) -> None:
    """With ``scroll_transcript_up=unbound``, ``ctrl+u`` deletes to line start."""
    import dataclasses as _dataclasses

    from sase.ace.tui.command_line.input import CommandLineInput

    async with _panel(grammar_handle) as (page, screen):
        await _seed_and_anchor(page, screen)
        scope = page.app._keymap_registry.command_line
        page.app._keymap_registry.command_line = _dataclasses.replace(
            scope, scroll_transcript_up="unbound"
        )
        widget = screen.query_one(CommandLineInput)
        widget.set_line("bead list")
        await page.pause()
        before = screen.transcript.scroll_y
        await page.press("ctrl+u")
        await page.pause()
        assert widget.text != "bead list"
        assert screen.transcript.scroll_y == before


async def test_block_nav_scrolls_selection_into_view(grammar_handle: Any) -> None:
    """``k`` selects the last block; ``g`` jumps to the first, scrolled in view."""
    async with _panel(grammar_handle) as (page, screen):
        from sase.ace.tui.command_line.input import CommandLineInput
        from sase.ace.tui.command_line.session import command_line_session_for

        await _seed_and_anchor(page, screen)
        widget = screen.query_one(CommandLineInput)
        widget.set_line("bead list")
        await page.pause()
        widget._enter_normal_mode()
        await page.pause()
        assert screen.handle_block_nav_key("k") is True
        session = command_line_session_for(page.app)
        assert session.selected_block() is session.blocks[-1]
        assert screen.handle_block_nav_key("g") is True
        assert session.selected_block() is session.blocks[0]
        await page.pause()
        await page.pause()
        transcript = screen.transcript
        first_id = session.blocks[0].block_id
        target = None
        for child in transcript.query("Static"):
            block = getattr(child, "block", None)
            if block is not None and block.block_id == first_id:
                target = child
                break
        assert target is not None
        assert target.region.overlaps(transcript.scrollable_content_region)
