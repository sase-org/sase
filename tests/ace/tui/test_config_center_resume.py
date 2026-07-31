"""Resume persistence and opener coverage for the SASE Admin Center."""

from __future__ import annotations

import asyncio
import threading

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.modals import config_center_state
from sase.ace.tui.modals.config_center_history import AdminCenterTabHistory
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from sase.ace.tui.modals.config_center_state import (
    load_admin_center_tab_history,
    save_admin_center_tab_history,
)
from tests.ace.tui._config_center_tabs_helpers import (
    _HostApp,
    _InputPane,
    _StubPane,
    _patch_stub_panes,
    _wait_until,
)


async def test_repeated_opener_without_history_keeps_one_zero_pane_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_create(_self: ConfigCenterModal, _tab: CenterTab) -> _StubPane:
        raise AssertionError("an absent resume target must not construct a pane")

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", fail_create)
    async with AcePage(initial_tab="agents") as page:
        assert page.app._last_admin_center_tab is None
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("number_sign", "number_sign")
        await page.pause()

        assert page.app.screen is modal
        assert len(page.app.screen_stack) == 2
        assert modal._active_tab is None
        assert modal._panes == {}


async def test_direct_initial_tab_mounts_only_that_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="updates", auto_update=True)
        assert modal.check_action("resume_last_tab", ()) is False
        pilot.app.push_screen(modal)
        await _wait_until(pilot, lambda: modal._active_tab == "updates")

        assert calls == ["updates"]
        assert tuple(modal._panes) == ("updates",)
        assert modal._auto_update is True


async def test_generic_reopen_is_home_first_then_repeated_opener_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_stub_panes(monkeypatch)
    async with AcePage(initial_tab="agents") as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        first = page.app.screen
        assert isinstance(first, ConfigCenterModal)
        assert first._active_tab is None

        await page.press("5")
        await page.wait_for(lambda _state: first._active_tab == "tasks")
        await page.press("escape")
        await page.expect_no_modal()
        assert page.app._last_admin_center_tab == "tasks"
        generation = page.app._admin_center_tab_save_generation
        assert generation == 1

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        second = page.app.screen
        assert isinstance(second, ConfigCenterModal)
        assert second is not first
        assert second._active_tab is None
        assert second._panes == {}

        await page.press("number_sign", "number_sign", "number_sign")
        await page.wait_for(lambda _state: second._active_tab == "tasks")

        assert calls == ["tasks", "tasks"]
        assert tuple(second._panes) == ("tasks",)
        assert page.app.screen is second
        assert len(page.app.screen_stack) == 2
        assert page.app.current_tab == "agents"
        assert page.app._admin_center_tab_save_generation == generation


async def test_switching_changes_resume_target_and_home_only_close_retains_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        page.app._last_admin_center_tab = "tasks"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")
        await page.press("2")
        await page.wait_for(lambda _state: modal._active_tab == "logs")
        await page.press("escape")
        await page.expect_no_modal()
        assert page.app._last_admin_center_tab == "logs"

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        home = page.app.screen
        assert isinstance(home, ConfigCenterModal)
        assert home._active_tab is None
        await page.press("escape")
        await page.expect_no_modal()
        assert page.app._last_admin_center_tab == "logs"


async def test_direct_entry_establishes_resume_target_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    async with AcePage() as page:
        page.app.action_open_tasks_panel()
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        await page.wait_for(lambda _state: modal._active_tab == "tasks")
        await page.wait_for(
            lambda _state: page.app._admin_center_tab_completed_generation == 1
        )

        assert load_admin_center_tab_history() == AdminCenterTabHistory(current="tasks")
        await page.press("escape")
        await page.expect_no_modal()

        assert page.app._last_admin_center_tab == "tasks"


async def test_persisted_tab_seeds_home_and_repeated_opener_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_admin_center_tab_history(AdminCenterTabHistory(current="tasks"))
    _created, calls = _patch_stub_panes(monkeypatch)

    async with AcePage(initial_tab="agents") as page:
        assert page.app._last_admin_center_tab == "tasks"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        assert modal._active_tab is None
        assert modal._panes == {}
        hint = modal.query_one("#admin-center-home-hint", Static).render().plain
        assert "resume Tasks" in hint

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")

        assert calls == ["tasks"]
        assert tuple(modal._panes) == ("tasks",)
        assert page.app._admin_center_tab_save_generation == 0


async def test_invalid_persisted_tab_keeps_no_history_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = config_center_state._admin_center_last_tab_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("missing\n")

    def _fail_create(_self: ConfigCenterModal, _tab: CenterTab) -> _StubPane:
        raise AssertionError("invalid persisted state must not construct a pane")

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", _fail_create)
    async with AcePage() as page:
        assert page.app._last_admin_center_tab is None
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        hint = modal.query_one("#admin-center-home-hint", Static).render().plain
        assert "resumes after your first section visit" in hint

        await page.press("number_sign")
        await page.pause()
        assert modal._active_tab is None
        assert modal._panes == {}


async def test_blocked_write_keeps_navigation_responsive_and_persists_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    started = threading.Event()
    release = threading.Event()
    writes: list[AdminCenterTabHistory] = []

    async with AcePage() as page:

        def _save(history: AdminCenterTabHistory) -> None:
            started.set()
            assert release.wait(5.0)
            writes.append(history)

        page.app._save_admin_center_tab_now = _save  # type: ignore[method-assign]
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("2")
        await page.wait_for(lambda _state: modal._active_tab == "logs")
        assert await asyncio.wait_for(
            asyncio.to_thread(started.wait, 1.0),
            timeout=1.5,
        )
        try:
            await page.press("5")
            await page.wait_for(lambda _state: modal._active_tab == "tasks")
            await page.press("6")
            await page.wait_for(lambda _state: modal._active_tab == "updates")
            assert page.app._last_admin_center_tab == "updates"
            assert writes == []
        finally:
            release.set()

        await page.wait_for(
            lambda _state: (
                page.app._admin_center_tab_completed_generation
                == page.app._admin_center_tab_save_generation
            )
        )

    assert writes == [
        AdminCenterTabHistory(current="logs"),
        AdminCenterTabHistory(current="updates", alternate="tasks"),
    ]


async def test_write_failure_is_nonfatal_and_same_tab_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    attempts: list[AdminCenterTabHistory] = []

    async with AcePage() as page:

        def _save(history: AdminCenterTabHistory) -> None:
            attempts.append(history)
            if len(attempts) == 1:
                raise OSError("synthetic write failure")
            save_admin_center_tab_history(history)

        page.app._save_admin_center_tab_now = _save  # type: ignore[method-assign]
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        first = page.app.screen
        assert isinstance(first, ConfigCenterModal)
        await page.press("2")
        await page.wait_for(lambda _state: first._active_tab == "logs")
        await page.wait_for(
            lambda _state: page.app._admin_center_tab_completed_generation == 1
        )
        assert page.app._last_admin_center_tab == "logs"
        assert page.app._admin_center_tab_queued is None

        await page.press("escape")
        await page.expect_no_modal()
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        second = page.app.screen
        assert isinstance(second, ConfigCenterModal)
        await page.press("2")
        await page.wait_for(lambda _state: second._active_tab == "logs")
        await page.wait_for(
            lambda _state: page.app._admin_center_tab_completed_generation == 2
        )

        assert attempts == [
            AdminCenterTabHistory(current="logs"),
            AdminCenterTabHistory(current="logs"),
        ]
        assert load_admin_center_tab_history() == AdminCenterTabHistory(current="logs")


async def test_failed_resume_retains_prior_target_and_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def create(_self: ConfigCenterModal, tab: CenterTab) -> _StubPane:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic resume failure")
        return _StubPane(tab)

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    async with AcePage() as page:
        page.app._last_admin_center_tab = "tasks"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("number_sign")
        await page.wait_for(lambda _state: attempts == 1)
        assert modal._active_tab is None
        assert page.app._last_admin_center_tab == "tasks"

        await page.press("number_sign")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")
        assert attempts == 2


async def test_custom_opener_opens_home_resumes_and_is_displayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"keymaps": {"app": {"open_config_center": "f2"}}}},
    )
    monkeypatch.setattr(AceApp, "_schedule_axe_async_refresh", lambda self: None)
    _patch_stub_panes(monkeypatch)

    async with AcePage() as page:
        page.app._last_admin_center_tab = "tasks"
        await page.press("f2")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        hint = modal.query_one("#admin-center-home-hint", Static).render().plain
        assert "f2" in hint
        assert "resume Tasks" in hint
        assert "#" not in hint

        await page.press("f2")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")


async def test_literal_opener_remains_typeable_and_cannot_nest_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ConfigCenterModal,
        "_create_pane",
        lambda _self, tab: _InputPane(tab),
    )
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="tasks", resume_tab="logs")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "tasks")
        field = modal.query_one("#stub-filter", Input)
        await page.wait_for(lambda _state: field.has_focus)

        await page.press("number_sign")
        await page.pause()

        assert field.value == "#"
        assert page.app.screen is modal
        assert len(page.app.screen_stack) == 2
