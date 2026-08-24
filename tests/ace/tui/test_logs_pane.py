"""Layout, navigation, and scrolling tests for the Admin Center Logs tab."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from rich.cells import cell_len
from rich.console import Console
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import ContentSwitcher, OptionList

from sase.ace.testing import wait_for
from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.logs_pane import LogsPane
from sase.logs import (
    RegisteredError,
    clear_registered_errors,
    error_anchor,
    register_error,
)
from tests.ace.tui._logs_pane_helpers import (
    LAUNCH_LOG_BODY,
    ModalTestApp,
    open_logs_pane,
    wait_for_logs_loaded,
    write_log,
)


@pytest.fixture(autouse=True)
def _clear_registered_errors() -> Iterator[None]:
    clear_registered_errors()
    yield
    clear_registered_errors()


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


async def test_logs_tab_selects_registered_error_source(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    write_log(log_dir / "tui.log", "2026-06-17 10:00:00,1 WARNING sase: heads up\n")
    error_id = "err_260617_143000_7f3a9c"
    target = RegisteredError(
        error_id=error_id,
        source_id="tui",
        anchor=error_anchor(error_id),
        summary="Launch failed",
        registered_at="2026-06-17 14:30:00",
    )

    async with ModalTestApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="logs", log_error_target=target)
        pilot.app.push_screen(modal)
        await pilot.pause()
        pane = modal.query_one("#logs", LogsPane)
        await wait_for_logs_loaded(pilot, pane)

        option_list = pane.query_one("#log-source-list", OptionList)
        assert option_list.highlighted == 1
        assert "tui.log" in pane._last_detail_text.plain


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
        assert modal._active_tab == "procs"
        assert switcher.current == "procs"

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
        # Load finishing does not mean the detail scroller has laid out yet.
        # G clamps to the current max, so wait until the pane is scrollable.
        await wait_for(pilot, lambda: scroll.max_scroll_y > 0)

        # G jumps to the bottom of the detail pane.
        await pilot.press("G")
        await wait_for(
            pilot,
            lambda: scroll.max_scroll_y > 0 and scroll.scroll_y == scroll.max_scroll_y,
        )

        # g returns to the top.
        await pilot.press("g")
        await wait_for(pilot, lambda: scroll.scroll_y == 0)

        # The highlighted log source is untouched by g / G.
        assert option_list.highlighted == highlighted_before


_FOCUS_ERROR_ID = "err_260617_143000_7f3a9c"


def _focus_target(*, source_id: str = "launch_failures") -> RegisteredError:
    return RegisteredError(
        error_id=_FOCUS_ERROR_ID,
        source_id=source_id,
        anchor=error_anchor(_FOCUS_ERROR_ID),
        summary="Launch failed",
        registered_at="2026-06-17 14:30:00",
    )


def _long_focused_launch_log() -> str:
    return (
        "".join(f"line {i}\n" for i in range(200))
        + "=" * 72
        + "\n"
        + "[2026-06-17 14:30:00 UTC] single launch failure: alpha  "
        + f"{error_anchor(_FOCUS_ERROR_ID)}\n"
    )


class _JumpApp(BaseActionsMixin, ModalTestApp):
    def _on_admin_center_tab_activated(self, tab: object) -> None:
        return

    def _schedule_updates_indicator_revalidation(self) -> None:
        return


async def test_logs_pane_error_target_scrolls_to_focused_line_and_refresh_unfocuses(
    log_dir: Path,
) -> None:
    write_log(log_dir / "launch_failures.log", _long_focused_launch_log())
    target = _focus_target()

    async with ModalTestApp().run_test() as pilot:
        _, pane = await open_logs_pane(pilot, error_target=target)
        scroll = pane.query_one("#log-detail-scroll", VerticalScroll)
        await wait_for(pilot, lambda: scroll.scroll_y > 0)

        assert pane._error_target is None
        assert f"focused on {_FOCUS_ERROR_ID}" in pane._last_detail_text.plain
        assert any(
            "#1F1B00" in str(span.style) for span in pane._last_detail_text.spans
        )

        await pilot.press("r")
        await wait_for_logs_loaded(pilot, pane)
        assert f"focused on {_FOCUS_ERROR_ID}" not in pane._last_detail_text.plain
        assert not any(
            "#1F1B00" in str(span.style) for span in pane._last_detail_text.spans
        )


async def test_jump_to_last_error_focuses_registered_log_entry(log_dir: Path) -> None:
    write_log(log_dir / "launch_failures.log", LAUNCH_LOG_BODY)
    registered = register_error(
        error_id=_FOCUS_ERROR_ID,
        source_id="launch_failures",
        summary="Launch failed",
    )

    async with _JumpApp().run_test() as pilot:
        pilot.app.action_jump_to_last_error()
        await pilot.pause()
        modal = pilot.app.screen
        assert isinstance(modal, ConfigCenterModal)
        assert modal._log_error_target is registered
        pane = modal.query_one("#logs", LogsPane)
        await wait_for_logs_loaded(pilot, pane)
        assert f"focused on {_FOCUS_ERROR_ID}" in pane._last_detail_text.plain
        assert error_anchor(_FOCUS_ERROR_ID) in pane._last_detail_text.plain
