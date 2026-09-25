"""Completion-fixes tests for the ``:`` Command Line (sase-17x.13.5).

Covers the popup window (every candidate reachable), the highlight echo
guard, the scoped provider footer, per-kind cache TTLs and invalidation on
finish, cursor rechecks on async provider results, and the hint and heading
text fixes.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch as mock_patch

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.tui.command_line.extras import (
    EMPTY_STATE_RECENT_HEADING,
    empty_state_rows,
    provider_empty_note,
    provider_unavailable_note,
    top_level_command_count,
)
from sase.ace.tui.command_line.popup import (
    POPUP_MAX_VISIBLE_ROWS,
    CommandLinePopup,
    popup_footer,
)
from sase.ace.tui.command_line.sources import ProviderCache
from sase.history import command_line as history_store


@pytest.fixture
def history_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the history store to a temp file."""
    path = tmp_path / "command_line_history.json"
    monkeypatch.setattr(history_store, "_history_file_override", path)
    return path


@pytest.fixture(scope="module")
def grammar_handle() -> Any:
    """Return an in-process ``CommandLineGrammar`` (no spec subprocess)."""
    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        return CommandLineGrammar.from_spec_json(json.dumps(build_spec().to_json()))
    except AttributeError:
        pytest.skip("installed sase_core_rs wheel predates CommandLineGrammar")


def _item(index: int) -> dict[str, Any]:
    name = f"item-{index:02d}"
    return {
        "insert_text": f"{name} ",
        "display": name,
        "description": "",
        "badge": "cmd",
        "source": "spec",
        "match_runs": [],
        "selected": False,
    }


def _items(count: int) -> list[dict[str, Any]]:
    return [_item(index) for index in range(count)]


def _row_text(popup: CommandLinePopup, row: int) -> str:
    return str(popup.get_option_at_index(row).prompt.plain)  # type: ignore[union-attr]


def _highlighted_text(popup: CommandLinePopup) -> str:
    assert popup.highlighted is not None
    return _row_text(popup, popup.highlighted)


# -- the popup window ---------------------------------------------------------


class _PopupHost(App[None]):
    def compose(self) -> ComposeResult:
        yield CommandLinePopup()


async def test_popup_window_scrolls_to_keep_every_item_reachable() -> None:
    """The popup renders 8 rows at a time but reaches all 30 candidates."""
    async with _PopupHost().run_test() as pilot:
        popup = pilot.app.query_one(CommandLinePopup)
        popup.show_items(_items(30))
        assert popup.option_count == POPUP_MAX_VISIBLE_ROWS
        assert popup.highlighted is None

        popup.highlight_index(0)
        assert "item-00" in _highlighted_text(popup)
        popup.highlight_index(7)
        assert "item-07" in _highlighted_text(popup)
        # One past the window scrolls it by exactly one row.
        popup.highlight_index(8)
        assert "item-08" in _highlighted_text(popup)
        assert popup.highlighted == POPUP_MAX_VISIBLE_ROWS - 1
        assert "item-01" in _row_text(popup, 0)
        popup.highlight_index(29)
        assert "item-29" in _highlighted_text(popup)
        assert popup.option_count == POPUP_MAX_VISIBLE_ROWS
        # Wrapping back to the top scrolls the window back.
        popup.highlight_index(30)
        assert "item-00" in _highlighted_text(popup)
        assert "item-00" in _row_text(popup, 0)
        popup.highlight_index(20)
        popup.clear_highlight()
        assert popup.highlighted is None
        assert "item-00" in _row_text(popup, 0)


async def test_popup_section_headings_are_disabled_and_never_highlighted() -> None:
    """Section headings render as disabled rows the highlight skips."""
    items = _items(6)
    for item in items[:2]:
        item["section"] = "RECENT"
    for item in items[2:]:
        item["section"] = "FOR athena.1 · selected agent"
    async with _PopupHost().run_test() as pilot:
        popup = pilot.app.query_one(CommandLinePopup)
        popup.show_items(items)
        assert popup.option_count == 8  # six rows plus two headings
        assert popup.get_option_at_index(0).disabled is True
        assert "RECENT" in _row_text(popup, 0)
        assert popup.get_option_at_index(3).disabled is True
        assert "FOR athena.1 · selected agent" in _row_text(popup, 3)
        popup.highlight_index(0)
        assert popup.highlighted == 1
        popup.highlight_index(2)
        assert popup.highlighted == 4
        assert "item-02" in _highlighted_text(popup)
        popup.highlight_index(5)
        assert "item-05" in _highlighted_text(popup)
        popup.highlight_index(2)
        assert "item-02" in _highlighted_text(popup)
        # Headings are extra rows: a full 8-item window still shows them.
        sectioned = [dict(_item(i), section="A") for i in range(4)] + [
            dict(_item(i), section="B") for i in range(4, 12)
        ]
        popup.show_items(sectioned)
        assert popup.option_count == POPUP_MAX_VISIBLE_ROWS + 2  # items + A, B
        popup.highlight_index(11)  # the window now opens on section B's heading
        assert popup.option_count == POPUP_MAX_VISIBLE_ROWS + 1
        assert popup.get_option_at_index(0).disabled is True
        assert "B" in _row_text(popup, 0)
        assert "item-11" in _highlighted_text(popup)
        popup.highlight_index(2)  # scrolled back up: B's heading sits mid-window
        assert "item-02" in _highlighted_text(popup)
        assert popup.get_option_at_index(0).disabled is False
        assert popup.get_option_at_index(2).disabled is True
        assert "B" in _row_text(popup, 2)


def test_popup_footer_tracks_index_and_menu_state() -> None:
    """The footer shows one key hint that fits the menu state."""
    assert popup_footer("bead", 8, 410) == "bead · 8 of 410 · fuzzy    ⇥ complete"
    assert (
        popup_footer("bead", 12, 30, menu_active=True)
        == "bead · 12 of 30 · fuzzy    ⏎ accept"
    )
    assert popup_footer("bead", 0, 0, note="no bead").endswith("⇥ complete  no bead")
    assert "⇥ accept" not in popup_footer("bead", 1, 3, menu_active=True)


# -- panel harness ------------------------------------------------------------


@asynccontextmanager
async def _panel(grammar: Any) -> AsyncGenerator[tuple[Any, Any]]:
    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.screen import CommandLineScreen

    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app._command_line_grammar = grammar
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            await page.pause()
            yield page, screen


async def _type(page: Any, screen: Any, line: str) -> Any:
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = screen.query_one(CommandLineInput)
    widget.set_line(line)
    await page.pause()
    return widget


async def test_tab_through_every_subcommand_reaches_the_last_with_a_highlight(
    grammar_handle: Any,
) -> None:
    """``bead `` offers 30 subcommands; Tab walks all of them, highlight visible."""
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "bead ")
        state = screen._popup_state
        count = len(state.items)
        assert count > POPUP_MAX_VISIBLE_ROWS
        popup = screen.query_one(CommandLinePopup)
        for _ in range(count):
            await page.press("tab")
        assert state.menu_active is True
        assert state.index == count - 1
        expected = str(state.items[count - 1]["display"])
        assert expected in _highlighted_text(popup)
        assert popup.option_count == POPUP_MAX_VISIBLE_ROWS
        footer = screen.query_one("#command-line-popup-footer", Static)
        assert f"{count} of" in str(footer.render())
        assert "⏎ accept" in str(footer.render())
        await page.press("tab")  # wraps to the first item
        assert state.index == 0
        assert str(state.items[0]["display"]) in _highlighted_text(popup)
        await page.press("shift+tab")  # and back to the last
        assert state.index == count - 1


async def test_enter_with_an_active_menu_accepts_without_submitting(
    grammar_handle: Any, history_file: Path
) -> None:
    """Enter in the menu inserts the highlight; the line is not also run."""
    from sase.ace.tui.command_line.session import command_line_session_for

    async with _panel(grammar_handle) as (page, screen):
        widget = await _type(page, screen, "bead ")
        await page.press("tab")
        assert screen._popup_state.menu_active is True
        insert = str(screen._popup_state.items[0]["insert_text"])
        await page.press("enter")
        assert widget.text == "bead " + insert
        assert screen._popup_state.menu_active is False
        assert command_line_session_for(page.app).blocks == []


async def test_escape_with_an_active_menu_leaves_the_menu_not_the_panel(
    grammar_handle: Any,
) -> None:
    """Esc in the menu restores the typed text and keeps the panel open."""
    from sase.ace.tui.command_line.screen import CommandLineScreen

    async with _panel(grammar_handle) as (page, screen):
        widget = await _type(page, screen, "bead ")
        await page.press("tab")
        assert screen._popup_state.menu_active is True
        await page.press("escape")
        assert screen._popup_state.menu_active is False
        assert widget.text == "bead "
        assert isinstance(page.app.screen, CommandLineScreen)


async def test_programmatic_highlights_do_not_reset_the_index(
    grammar_handle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queued echoes of the popup's own highlights never touch the state."""
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "item-")
        items = _items(30)
        state = screen._popup_state
        state.reset(items, typed_text="item-", replace_start=0, replace_end=5)
        screen._render_popup({"items": items, "total": 30, "kind": "subcommand"})
        await page.pause()
        popup = screen.query_one(CommandLinePopup)
        repaints: list[int] = []
        monkeypatch.setattr(screen, "_render_signature", lambda: repaints.append(1))

        state.menu_active = True
        for index in range(1, 12):
            popup.highlight_index(index)  # a burst: every echo lands later
        state.index = 11
        await page.pause()
        assert state.index == 11
        assert repaints == []

        # A genuine user highlight (a mouse click posts one) still lands.
        row = 2
        option = popup.get_option_at_index(row)
        popup.post_message(OptionList.OptionHighlighted(popup, option, row))
        await page.pause()
        assert str(items[state.index]["display"]) in _row_text(popup, row)
        assert repaints == [1]


async def test_stale_highlight_from_a_replaced_list_is_ignored(
    grammar_handle: Any,
) -> None:
    """A highlight message from before ``show_items`` cannot move the index."""
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "item-")
        items = _items(12)
        state = screen._popup_state
        state.reset(items, typed_text="item-", replace_start=0, replace_end=5)
        screen._render_popup({"items": items, "total": 12, "kind": "subcommand"})
        popup = screen.query_one(CommandLinePopup)
        stale_option = popup.get_option_at_index(3)
        screen._render_popup({"items": items, "total": 12, "kind": "subcommand"})
        popup.post_message(OptionList.OptionHighlighted(popup, stale_option, 3))
        await page.pause()
        assert state.index == 0


# -- provider footer, TTLs, invalidation -------------------------------------


async def _await_provider_task(screen: Any) -> None:
    task = screen._provider_task
    assert task is not None
    await asyncio.wait_for(task, timeout=5)


def _footer_text(screen: Any) -> tuple[bool, str]:
    footer = screen.query_one("#command-line-popup-footer", Static)
    return bool(footer.display), str(footer.render())


async def test_provider_footer_is_scoped_to_the_slot_and_clears_on_change(
    grammar_handle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed fetch warns only on its own slot; another slot's footer is clean."""
    import sase.completion.candidates.providers as providers

    def _boom(*args: object, **kwargs: object) -> list[Any]:
        raise RuntimeError("provider down")

    monkeypatch.setattr(providers, "candidates_for", _boom)
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "bead show ")
        await _await_provider_task(screen)
        await page.pause()
        shown, text = _footer_text(screen)
        assert shown is True
        assert text == provider_unavailable_note("bead")

        await _type(page, screen, "bead ")
        shown, text = _footer_text(screen)
        assert shown is True
        assert "unavailable" not in text
        assert "subcommand" in text


async def test_empty_provider_result_reads_neutral_not_unavailable(
    grammar_handle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful but empty fetch says ``no <kind>``; a failure warns."""
    import sase.completion.candidates.providers as providers

    monkeypatch.setattr(providers, "candidates_for", lambda *a, **k: [])
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "plan approve ")
        await _await_provider_task(screen)
        await page.pause()
        shown, text = _footer_text(screen)
        assert shown is True
        assert text == provider_empty_note("pending_plan")
        assert "unavailable" not in text


def test_provider_cache_health_distinguishes_empty_from_failed() -> None:
    """The cache remembers whether a fetch was empty or failed."""
    cache = ProviderCache(ttl_seconds=60.0)
    assert cache.health("bead", None) is None
    assert cache.commit(cache.next_generation(), "bead", None, []) is True
    assert cache.health("bead", None) == "empty"
    cache.note_unavailable("agent", None)
    assert cache.health("agent", None) == "failed"
    assert cache.commit(cache.next_generation(), "bead", None, [{"value": "x"}])
    assert cache.health("bead", None) == "ok"


def test_provider_cache_honors_per_kind_ttl() -> None:
    """Volatile kinds expire on their own short window, others on the default."""
    now = 100.0
    cache = ProviderCache(ttl_seconds=15.0, clock=lambda: now)
    generation = cache.next_generation()
    assert cache.commit(generation, "pending_plan", None, [{"value": "p"}])
    assert cache.commit(generation, "bead", None, [{"value": "b"}])
    now += 4.0
    assert cache.cached("pending_plan", None) == [{"value": "p"}]
    now += 2.0  # 6 s: past pending_plan's 5 s window, inside the 15 s default
    assert cache.cached("pending_plan", None) is None
    assert cache.cached("bead", None) == [{"value": "b"}]
    now += 10.0
    assert cache.cached("bead", None) is None


def test_provider_cache_invalidate_forgets_everything() -> None:
    """``invalidate`` drops fresh entries of every kind."""
    cache = ProviderCache(ttl_seconds=60.0)
    generation = cache.next_generation()
    cache.commit(generation, "pending_plan", None, [{"value": "p"}])
    cache.note_unavailable("bead", "sase")
    cache.invalidate()
    assert cache.cached("pending_plan", None) is None
    assert cache.health("bead", "sase") is None


async def test_finishing_a_command_invalidates_the_provider_cache(
    grammar_handle: Any, history_file: Path
) -> None:
    """``plan approve X`` finishing drops the cached pending-plan rows."""
    from sase.ace.tui.command_line.exits import deliver_command_line_exit
    from sase.ace.tui.command_line.session import (
        CommandLineBlock,
        command_line_session_for,
    )

    async with _panel(grammar_handle) as (page, screen):
        cache = screen._provider_cache
        cache.commit(cache.next_generation(), "pending_plan", None, [{"value": "X"}])
        assert cache.cached("pending_plan", None) == [{"value": "X"}]
        session = command_line_session_for(page.app)
        session.blocks.append(
            CommandLineBlock(
                block_id="b-approve",
                line="plan approve X",
                status="running",
                proc_id="proc-approve",
            )
        )
        completion = SimpleNamespace(proc_id="proc-approve", exit_code=0, status="done")
        assert deliver_command_line_exit(page.app, completion) is True
        assert cache.cached("pending_plan", None) is None


async def test_cursor_move_during_a_fetch_drops_the_result(
    grammar_handle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result that lands after the cursor moved is dropped, not cached."""
    import sase.completion.candidates.providers as providers
    from sase.completion.candidates.protocol import Candidate

    release = threading.Event()
    started = threading.Event()

    def _slow(*args: object, **kwargs: object) -> list[Candidate]:
        started.set()
        release.wait(timeout=5)
        return [Candidate("sase-1", "a bead")]

    monkeypatch.setattr(providers, "candidates_for", _slow)
    async with _panel(grammar_handle) as (page, screen):
        widget = await _type(page, screen, "bead show ")
        project = screen._working_context.project if screen._working_context else None
        task = screen._provider_task
        assert task is not None
        await page.wait_for(lambda _state: started.is_set())  # debounce, then thread
        widget.move_cursor((0, 3))  # same text, different cursor
        release.set()
        await asyncio.wait_for(task, timeout=5)
        assert screen._provider_cache.cached("bead", project) is None


async def test_line_change_during_a_fetch_drops_the_result(
    grammar_handle: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A result for a line the user already edited is dropped, not cached."""
    import sase.completion.candidates.providers as providers
    from sase.completion.candidates.protocol import Candidate

    release = threading.Event()
    started = threading.Event()

    def _slow(*args: object, **kwargs: object) -> list[Candidate]:
        started.set()
        release.wait(timeout=5)
        return [Candidate("sase-1", "a bead")]

    monkeypatch.setattr(providers, "candidates_for", _slow)
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "bead show ")
        project = screen._working_context.project if screen._working_context else None
        task = screen._provider_task
        assert task is not None
        await page.wait_for(lambda _state: started.is_set())
        await _type(page, screen, "bead ")
        release.set()
        await asyncio.wait_for(task, timeout=5)
        assert screen._provider_cache.cached("bead", project) is None


# -- hint and heading text ----------------------------------------------------


def test_top_level_command_count_counts_only_top_level_children() -> None:
    """The idle hint counts the commands one can type first, not every node."""
    root = {"children": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
    assert top_level_command_count(lambda path: root if path == [] else None) == 3
    assert top_level_command_count(lambda path: None) is None

    def _boom(path: list[str]) -> dict[str, Any]:
        raise RuntimeError("no help")

    assert top_level_command_count(_boom) is None


async def test_empty_state_hint_counts_top_level_commands(grammar_handle: Any) -> None:
    """The empty-state hint shows the top-level count, not the node count."""
    async with _panel(grammar_handle) as (page, screen):
        await _type(page, screen, "")
        hint = str(screen.query_one("#command-line-hint-row", Static).render())
        top_level = len(grammar_handle.command_help([])["children"])
        assert hint.startswith(f"{top_level} commands")
        assert f"{len(grammar_handle)} commands" not in hint


def test_empty_state_rows_carry_section_headings() -> None:
    """RECENT and FOR rows carry the headings the popup renders."""
    entries = [
        SimpleNamespace(line="bead list", last_used="260101_000001", last_exit=0)
    ]

    def _lookup(path: list[str]) -> dict[str, Any] | None:
        if path == []:
            return {"children": [{"name": "agent"}]}
        if path == ["agent"]:
            return {"children": [{"name": "show"}]}
        if path == ["agent", "show"]:
            return {
                "children": [],
                "positionals": [{"required": True, "value_kind": "agent"}],
            }
        return None

    rows = empty_state_rows(
        _lookup, entries, selected_kind="agent", selected_value="athena.1"
    )
    sections = [row.section for row in rows]
    assert sections == [EMPTY_STATE_RECENT_HEADING, "FOR athena.1 · selected agent"]
    assert [row.to_item()["section"] for row in rows] == sections


async def test_empty_state_popup_renders_headings_and_enter_inserts(
    grammar_handle: Any, history_file: Path
) -> None:
    """The empty state shows a RECENT heading; Enter inserts without running."""
    from sase.ace.tui.command_line.input import CommandLineInput

    async with _panel(grammar_handle) as (page, screen):
        screen._history.entries = [
            history_store.CommandLineHistoryEntry(
                line="bead list --status open", last_used="260101_000001"
            )
        ]
        await _type(page, screen, "")
        popup = screen.query_one(CommandLinePopup)
        assert popup.get_option_at_index(0).disabled is True
        assert EMPTY_STATE_RECENT_HEADING in _row_text(popup, 0)
        assert "bead list --status open" in _row_text(popup, 1)
        await page.press("tab")  # activate the menu on the first command row
        assert popup.highlighted == 1
        await page.press("enter")
        widget = screen.query_one(CommandLineInput)
        assert widget.text == "bead list --status open"
        from sase.ace.tui.command_line.session import command_line_session_for

        assert command_line_session_for(page.app).blocks == []
