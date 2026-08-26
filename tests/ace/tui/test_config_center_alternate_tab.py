"""In-tab alternate-jump and footer coverage for the SASE Admin Center."""

from __future__ import annotations

import pytest
from textual.widgets import Input

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.modals.config_center_footer import AdminCenterFooter
from sase.ace.tui.modals.config_center_history import AdminCenterTabHistory
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from tests.ace.tui._config_center_tabs_helpers import (
    _InputPane,
    _StubPane,
    _patch_stub_panes,
)


async def test_alternate_opener_ping_pongs_between_exactly_two_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_stub_panes(monkeypatch)
    async with AcePage(initial_tab="agents") as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("1")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        await page.press("2")
        await page.wait_for(lambda _state: modal._active_tab == "logs")

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "logs")
        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "config")

        # Each section is constructed once; ping-ponging between the two
        # already-mounted panes never constructs a third.
        assert calls == ["config", "logs"]
        assert tuple(modal._panes) == ("config", "logs")


async def test_single_section_visited_leaves_opener_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("3")
        await page.wait_for(lambda _state: modal._active_tab == "procs")
        assert modal.check_action("alternate_center_tab", ()) is False

        await page.press("number_sign")
        await page.pause()

        assert modal._active_tab == "procs"
        assert calls == ["procs"]


async def test_seeded_alternate_survives_close_and_reopen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        first = page.app.screen
        assert isinstance(first, ConfigCenterModal)

        await page.press("1")
        await page.wait_for(lambda _state: first._active_tab == "config")
        await page.press("2")
        await page.wait_for(lambda _state: first._active_tab == "logs")
        await page.press("escape")
        await page.expect_no_modal()

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        second = page.app.screen
        assert isinstance(second, ConfigCenterModal)
        assert second._active_tab is None

        await page.press("number_sign")
        await page.wait_for(lambda _state: second._active_tab == "logs")

        await page.press("number_sign")
        await page.wait_for(lambda _state: second._active_tab == "config")


async def test_custom_opener_drives_alternate_jump_and_is_shown_in_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"keymaps": {"app": {"open_config_center": "f2"}}}},
    )
    monkeypatch.setattr(AceApp, "_schedule_axe_async_refresh", lambda self: None)
    _patch_stub_panes(monkeypatch)

    async with AcePage() as page:
        await page.press("f2")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("1")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        await page.press("2")
        await page.wait_for(lambda _state: modal._active_tab == "logs")

        footer = modal.query_one("#config-center-footer", AdminCenterFooter)
        text = footer.render().plain
        assert "f2" in text
        assert "Config" in text
        assert "#" not in text

        await page.press("f2")
        await page.wait_for(lambda _state: modal._active_tab == "config")


async def test_literal_opener_with_alternate_available_still_types_and_stays_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ConfigCenterModal,
        "_create_pane",
        lambda _self, tab: _InputPane(tab),
    )
    async with AcePage() as page:
        modal = ConfigCenterModal(
            initial_tab="procs", resume_tab="logs", alternate_tab="config"
        )
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "procs")
        field = modal.query_one("#stub-filter", Input)
        await page.wait_for(lambda _state: field.has_focus)

        assert modal.check_action("alternate_center_tab", ()) is True

        await page.press("number_sign")
        await page.pause()

        assert field.value == "#"
        assert modal._active_tab == "procs"
        assert page.app.screen is modal
        assert len(page.app.screen_stack) == 2


async def test_failed_alternate_jump_leaves_history_unchanged_and_is_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def create(_self: ConfigCenterModal, tab: CenterTab) -> _StubPane:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("synthetic alternate-jump failure")
        return _StubPane(tab)

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    async with AcePage() as page:
        page.app._admin_center_history = AdminCenterTabHistory(
            current="procs", alternate="logs"
        )
        page.app._last_admin_center_tab = "procs"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "procs")
        assert attempts == 1
        history_before = modal._history
        assert history_before == AdminCenterTabHistory(
            current="procs", alternate="logs"
        )

        await page.press("number_sign")
        await page.wait_for(lambda _state: attempts == 2)
        assert modal._active_tab == "procs"
        assert modal._history == history_before

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "logs")
        assert attempts == 3


async def test_footer_hidden_on_home_and_reflects_alternate_once_a_tab_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        footer = modal.query_one("#config-center-footer", AdminCenterFooter)
        assert footer.display is False

        await page.press("1")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        assert footer.display is True
        assert "no earlier section yet" in footer.render().plain

        await page.press("2")
        await page.wait_for(lambda _state: modal._active_tab == "logs")
        text = footer.render().plain
        assert "Config" in text
        assert "press again to return here" in text

        await page.press("escape")
        await page.expect_no_modal()


async def test_footer_click_navigates_to_the_alternate_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("1")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        await page.press("2")
        await page.wait_for(lambda _state: modal._active_tab == "logs")

        await page.click("#config-center-footer")
        await page.wait_for(lambda _state: modal._active_tab == "config")
