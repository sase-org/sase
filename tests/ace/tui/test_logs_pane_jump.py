"""Jump-mode tests for the Admin Center Logs tab."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, OptionList

from sase.ace.tui.modals import logs_pane as lp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.logs_pane import LogsPane
from tests.ace.tui._logs_pane_helpers import log_dir as log_dir
from tests.ace.tui._logs_pane_helpers import (
    LAUNCH_LOG_BODY,
    ModalTestApp,
    open_logs_pane,
    wait_for_logs_loaded,
    write_log,
)


def _option_plain(option_list: OptionList, index: int) -> str:
    option = option_list.get_option_at_index(index)
    assert isinstance(option.prompt, Text)
    return option.prompt.plain


def _logs_hint_text(pane: LogsPane) -> str:
    return pane._hints()


async def test_logs_tab_apostrophe_enters_jump_mode_with_hints(
    log_dir: Path,
) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()

        assert pane.jump_mode_active is True
        assert _option_plain(option_list, 0).startswith("[0] ● Launch")
        assert _option_plain(option_list, 1).startswith("[1] ● TUI Diagnostics")
        assert "JUMP ' first" in _logs_hint_text(pane)


async def test_logs_tab_jump_hint_selects_source_and_loads_detail(
    log_dir: Path,
) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("1")
        await wait_for_logs_loaded(pilot, pane)

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == [0]
        assert option_list.highlighted == 1
        assert "tui.log" in pane._last_detail_text.plain
        assert not _option_plain(option_list, 1).startswith("[1]")


async def test_logs_tab_digit_hint_does_not_switch_admin_center_tabs(
    log_dir: Path,
) -> None:
    async with ModalTestApp().run_test() as pilot:
        modal, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert len(pane._source_options) >= 3

        await pilot.press("apostrophe")
        await pilot.press("2")
        await wait_for_logs_loaded(pilot, pane)

        assert pane.jump_mode_active is False
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"
        assert option_list.highlighted == 2


async def test_logs_tab_apostrophe_in_jump_mode_returns_to_previous_source(
    log_dir: Path,
) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.press("1")
        await wait_for_logs_loaded(pilot, pane)
        assert option_list.highlighted == 1

        await pilot.press("apostrophe")
        await pilot.pause()
        assert "JUMP ' back" in _logs_hint_text(pane)

        await pilot.press("apostrophe")
        await wait_for_logs_loaded(pilot, pane)

        assert option_list.highlighted == 0
        assert pane.jump_back_stack == []
        assert "launch_failures.log" in pane._last_detail_text.plain


async def test_logs_tab_apostrophe_without_history_jumps_to_first_source(
    log_dir: Path,
) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("j")
        await wait_for_logs_loaded(pilot, pane)
        assert option_list.highlighted == 1
        assert pane.jump_back_stack == []

        await pilot.press("apostrophe")
        await pilot.press("apostrophe")
        await wait_for_logs_loaded(pilot, pane)

        assert option_list.highlighted == 0
        assert pane.jump_back_stack == [1]
        assert "launch_failures.log" in pane._last_detail_text.plain


async def test_logs_tab_escape_cancels_jump_mode_without_closing_modal(
    log_dir: Path,
) -> None:
    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)

        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfigCenterModal)
        assert pane.jump_mode_active is False
        assert option_list.highlighted == 0
        assert not _option_plain(option_list, 0).startswith("[0]")
        assert "': jump" in _logs_hint_text(pane)


async def test_logs_tab_jump_mode_reuses_cached_source_labels(
    log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)
        cached_plain = _option_plain(option_list, 0)

        def fail_source_label(*_a: object, **_kw: object) -> Text:
            raise AssertionError("_source_label should not run during jump rendering")

        monkeypatch.setattr(lp, "_source_label", fail_source_label)

        await pilot.press("apostrophe")
        await pilot.pause()

        assert _option_plain(option_list, 0) == f"[0] {cached_plain}"


async def test_logs_tab_jump_mode_takes_g_and_shift_g_from_the_detail_scroller(
    log_dir: Path,
) -> None:
    # Enough lines that the right detail pane is genuinely scrollable, so a
    # swallowed g / G would move it.
    write_log(
        log_dir / "launch_failures.log", "".join(f"line {i}\n" for i in range(200))
    )

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        scroll = pane.query_one("#log-detail-scroll", VerticalScroll)

        for hint_key in ("G", "g"):
            await pilot.press("apostrophe")
            await pilot.pause()
            assert pane.jump_mode_active is True

            await pilot.press(hint_key)
            await wait_for_logs_loaded(pilot, pane)

            # These sources allocate single-digit hints, so g / G are invalid
            # hints that exit jump mode -- but they must reach the pane's jump
            # handler instead of being swallowed by the detail scroller.
            assert scroll.max_scroll_y > 0  # pane really is scrollable
            assert pane.jump_mode_active is False
            assert scroll.scroll_y == 0
