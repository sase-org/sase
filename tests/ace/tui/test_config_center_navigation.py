"""Pane activation and failure coverage for the SASE Admin Center."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from textual.widget import Widget
from textual.widgets import ContentSwitcher

from sase.ace.tui.modals.config_center_modal import (
    _HOME_ID,
    CenterTab,
    ConfigCenterModal,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from tests.ace.tui._config_center_tabs_helpers import (
    _HostApp,
    _StubPane,
    _patch_stub_panes,
)


async def test_repeated_first_navigation_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        results = await asyncio.gather(
            modal._switch_to("procs"),
            modal._switch_to("procs"),
            modal._switch_to("procs"),
        )

        assert results == [True, True, True]
        assert calls == ["procs"]
        assert len(created["procs"]) == 1
        assert len(modal.query("#procs")) == 1


async def test_activation_callback_observes_committed_success_and_not_refocus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, _calls = _patch_stub_panes(monkeypatch)
    activated: list[CenterTab] = []
    async with _HostApp().run_test() as pilot:
        modal: ConfigCenterModal

        def _activated(tab: CenterTab) -> None:
            pane = created[tab][0]
            assert modal._active_tab == tab
            assert (
                modal.query_one("#config-center-switcher", ContentSwitcher).current
                == tab
            )
            assert pane.visibility[-1] is True
            assert pane.focus_count >= 1
            activated.append(tab)

        modal = ConfigCenterModal(on_tab_activated=_activated)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert await modal._switch_to("procs") is True
        assert await modal._switch_to("procs") is True

    assert activated == ["procs"]


async def test_activation_callback_is_silent_for_construction_and_mount_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    activated: list[CenterTab] = []

    def _fail_create(_self: ConfigCenterModal, _tab: CenterTab) -> _StubPane:
        raise RuntimeError("synthetic construction failure")

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", _fail_create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(on_tab_activated=activated.append)
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert await modal._switch_to("procs") is False

    assert activated == []

    _patch_stub_panes(monkeypatch)

    def _fail_mount(_self: ContentSwitcher, _widget: Widget, **_kwargs: Any) -> Any:
        raise RuntimeError("synthetic mount failure")

    monkeypatch.setattr(ContentSwitcher, "add_content", _fail_mount)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(on_tab_activated=activated.append)
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert await modal._switch_to("procs") is False

    assert activated == []


async def test_activation_callback_is_silent_for_switch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    activated: list[CenterTab] = []
    original_sync_chrome = ConfigCenterModal._sync_chrome

    def _fail_target_header(modal: ConfigCenterModal, tab: CenterTab | None) -> None:
        if tab == "procs":
            raise RuntimeError("synthetic switch failure")
        original_sync_chrome(modal, tab)

    monkeypatch.setattr(ConfigCenterModal, "_sync_chrome", _fail_target_header)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(on_tab_activated=activated.append)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert await modal._switch_to("procs") is False
        assert modal._active_tab is None
        assert (
            modal.query_one("#config-center-switcher", ContentSwitcher).current
            == _HOME_ID
        )

    assert activated == []


async def test_activation_callback_failure_does_not_fail_navigation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_stub_panes(monkeypatch)

    def _fail_callback(_tab: CenterTab) -> None:
        raise RuntimeError("synthetic callback failure")

    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(on_tab_activated=_fail_callback)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert await modal._switch_to("procs") is True
        assert modal._active_tab == "procs"

    assert "Admin Center tab-activation callback failed" in caplog.text


async def test_construction_failure_keeps_home_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def create(_self: ConfigCenterModal, tab: CenterTab) -> _StubPane:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic construction failure")
        return _StubPane(tab)

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert await modal._switch_to("config") is False
        assert modal._active_tab is None
        assert modal.query_one("#config-center-switcher", ContentSwitcher).current == (
            _HOME_ID
        )
        assert modal.query_one("#config-center-tabs", PanelTabStrip)._active_tab is None

        assert await modal._switch_to("config") is True
        assert modal._active_tab == "config"
        assert attempts == 2


async def test_mount_failure_keeps_home_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_stub_panes(monkeypatch)
    original_add_content = ContentSwitcher.add_content
    attempts = 0

    def flaky_add_content(
        switcher: ContentSwitcher,
        widget: Widget,
        *,
        id: str | None = None,
        set_current: bool = False,
    ) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic mount failure")
        return original_add_content(
            switcher,
            widget,
            id=id,
            set_current=set_current,
        )

    monkeypatch.setattr(ContentSwitcher, "add_content", flaky_add_content)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert await modal._switch_to("logs") is False
        assert modal._active_tab is None
        assert modal._panes == {}
        assert not modal.query("#logs")

        assert await modal._switch_to("logs") is True
        assert modal._active_tab == "logs"
        assert attempts == 2
