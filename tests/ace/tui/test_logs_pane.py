"""Layout, navigation, and scrolling tests for the Admin Center Logs tab."""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, OptionList

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


async def test_logs_tab_source_rows_fit_the_pane_width(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane._option_list()
        assert option_list is not None

        width = option_list.scrollable_content_region.width
        for index in range(option_list.option_count):
            label = option_list.get_option_at_index(index).prompt
            assert isinstance(label, Text)
            for line in label.plain.splitlines():
                assert cell_len(line) <= width


async def test_logs_tab_source_rows_render_on_exactly_two_lines(
    log_dir: Path,
) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)
        option_list = pane._option_list()
        assert option_list is not None
        width = option_list.scrollable_content_region.width
        console = Console(width=width)

        for index in range(option_list.option_count):
            label = option_list.get_option_at_index(index).prompt
            assert isinstance(label, Text)
            assert len(label.wrap(console, width)) == 2

        # A hinted row is wider still (``[a] `` prefix) -- must still ellipsize
        # to two lines rather than wrap to three.
        await pilot.press("apostrophe")
        await pilot.pause()
        assert pane.jump_mode_active is True

        for index in range(option_list.option_count):
            label = option_list.get_option_at_index(index).prompt
            assert isinstance(label, Text)
            assert len(label.wrap(console, width)) == 2


async def test_logs_tab_opens_with_launch_failures_selected(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)

    async with ModalTestApp().run_test() as pilot:
        modal, pane = await open_logs_pane(pilot)

        assert isinstance(pilot.app.screen, ConfigCenterModal)
        assert modal._active_tab == "logs"
        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 0  # launch_failures is the default

        assert "launch_failures.log" in pane._last_detail_text.plain


async def test_logs_tab_navigation_updates_detail(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)

        await pilot.press("j")
        await wait_for_logs_loaded(pilot, pane)
        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 1
        assert "tui.log" in pane._last_detail_text.plain

        # k navigates back up to launch failures.
        await pilot.press("k")
        await wait_for_logs_loaded(pilot, pane)
        assert option_list.highlighted == 0


async def test_tab_switches_admin_center_tabs_and_brackets_do_not(
    log_dir: Path,
) -> None:
    async with ModalTestApp().run_test() as pilot:
        modal, pane = await open_logs_pane(pilot)
        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("left_square_bracket")
        await pilot.pause()
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"
        assert option_list.highlighted == 0

        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"
        assert option_list.highlighted == 0

        await pilot.press("tab")
        await pilot.pause()
        assert modal._active_tab == "projects"
        assert switcher.current == "projects"

        await pilot.press("shift+tab")
        await pilot.pause()
        assert modal._active_tab == "logs"
        assert switcher.current == "logs"


async def test_logs_tab_refresh_and_scroll_and_dismiss(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)

        # Log grows after the pane opened; r re-reads the tail.
        write_log(
            log_dir / "launch_failures.log",
            LAUNCH_LOG_BODY + "  error: SecondError: again\n",
        )
        await pilot.press("r")
        await wait_for_logs_loaded(pilot, pane)
        assert "SecondError" in pane._last_detail_text.plain

        # Scrolling and dismissal don't error.
        await pilot.press("ctrl+d")
        await pilot.press("ctrl+u")
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, ConfigCenterModal)


def _binding_action(key: str) -> str | None:
    """Action bound to *key* in ``LogsPane.BINDINGS`` (tuple or Binding)."""
    for binding in LogsPane.BINDINGS:
        if isinstance(binding, tuple):
            bind_key, action = binding[0], binding[1]
        else:
            bind_key, action = binding.key, binding.action
        if bind_key == key:
            return action
    return None


def test_logs_pane_binds_g_and_shift_g_to_scroll_extremes() -> None:
    assert _binding_action("g") == "scroll_to_top"
    assert _binding_action("G") == "scroll_to_bottom"


async def test_logs_tab_g_and_shift_g_scroll_detail_extremes(log_dir: Path) -> None:
    # Enough lines that the right detail pane is genuinely scrollable.
    write_log(
        log_dir / "launch_failures.log", "".join(f"line {i}\n" for i in range(200))
    )

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot)

        option_list = pane.query_one("#log-source-list", OptionList)
        highlighted_before = option_list.highlighted
        scroll = pane.query_one("#log-detail-scroll", VerticalScroll)

        # G jumps to the bottom of the detail pane.
        await pilot.press("G")
        await pilot.pause()
        assert scroll.max_scroll_y > 0  # pane really is scrollable
        assert scroll.scroll_y == scroll.max_scroll_y

        # g returns to the top.
        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0

        # The highlighted log source is untouched by g / G.
        assert option_list.highlighted == highlighted_before
