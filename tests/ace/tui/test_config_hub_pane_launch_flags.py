"""Config hub launch pane and feature flag coverage."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import (
    ConfigHubEntry,
    validated_config_subtab,
)
from sase.ace.tui.modals.models_panel import LaunchPane, ModelsPanelResult
from sase.feature_flags import override_flags
from tests._models_panel_helpers import make_alias_view, patch_alias_views
from tests.ace.tui._config_center_tabs_helpers import _HostApp
from tests.ace.tui._config_hub_pane_helpers import (
    _assert_hub_caption,
    _patch_hub_children,
)


async def test_launch_direct_entry_opens_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    state.config_hub.active_subtab = "memory"

    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            session_state=state,
            config_entry=ConfigHubEntry(subtab="launch"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "launch" in hub._panes)

        assert calls == ["launch"]
        assert hub._active_subtab == "launch"
        assert state.config_hub.active_subtab == "launch"
        _assert_hub_caption(hub, "launch")


async def test_launch_result_refreshes_app_indicators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    calls: list[bool] = []

    async with _HostApp().run_test() as pilot:

        def refresh_launch_indicators(
            *, provider_routing_changed: bool = False
        ) -> None:
            calls.append(provider_routing_changed)

        pilot.app._refresh_launch_indicators = refresh_launch_indicators  # type: ignore[attr-defined]
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)

        hub.on_launch_changed(
            ModelsPanelResult(changed=True, provider_routing_changed=True)
        )
        hub.on_launch_changed(ModelsPanelResult(changed=False))

    assert calls == [True]


async def test_embedded_launch_change_then_close_refreshes_indicators_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    calls: list[bool] = []
    close_calls: list[bool] = []

    async with _HostApp().run_test() as pilot:

        def refresh_launch_indicators(
            *, provider_routing_changed: bool = False
        ) -> None:
            calls.append(provider_routing_changed)

        pilot.app._refresh_launch_indicators = refresh_launch_indicators  # type: ignore[attr-defined]
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="launch"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "launch" in hub._panes)
        monkeypatch.setattr(
            hub,
            "_close_admin_center",
            lambda: close_calls.append(True),
        )
        launch = hub._panes["launch"]
        assert isinstance(launch, LaunchPane)
        await wait_for(pilot, lambda: "large" in launch._row_by_id)

        launch._mark_changed(provider_routing_changed=True)
        launch.action_close()
        await pilot.pause()

    assert calls == [True]
    assert close_calls == [True]


async def test_embedded_launch_unchanged_close_does_not_refresh_indicators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    calls: list[bool] = []
    close_calls: list[bool] = []

    async with _HostApp().run_test() as pilot:
        pilot.app._refresh_launch_indicators = (  # type: ignore[attr-defined]
            lambda *, provider_routing_changed=False: calls.append(
                provider_routing_changed
            )
        )
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="launch"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "launch" in hub._panes)
        monkeypatch.setattr(
            hub,
            "_close_admin_center",
            lambda: close_calls.append(True),
        )
        launch = hub._panes["launch"]
        assert isinstance(launch, LaunchPane)
        await wait_for(pilot, lambda: "large" in launch._row_by_id)

        launch.action_close()
        await pilot.pause()

    assert calls == []
    assert close_calls == [True]


async def test_config_hub_strip_thresholds_grow_for_six_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    with override_flags(admin_center_flags=False):
        async with _HostApp().run_test() as pilot:
            modal = ConfigCenterModal(initial_tab="config")
            pilot.app.push_screen(modal)
            await wait_for(pilot, lambda: modal._active_tab == "config")
            hub = modal.query_one("#config", ConfigHubPane)
            assert hub._compact_below == 69
            assert hub._micro_below == 60
    with override_flags(admin_center_flags=True):
        async with _HostApp().run_test() as pilot:
            modal = ConfigCenterModal(initial_tab="config")
            pilot.app.push_screen(modal)
            await wait_for(pilot, lambda: modal._active_tab == "config")
            hub = modal.query_one("#config", ConfigHubPane)
            assert hub._compact_below == 82
            assert hub._micro_below == 60


async def test_flags_resume_falls_back_when_rollout_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    state.config_hub.active_subtab = "flags"
    with override_flags(admin_center_flags=False):
        async with _HostApp().run_test() as pilot:
            modal = ConfigCenterModal(initial_tab="config", session_state=state)
            pilot.app.push_screen(modal)
            await wait_for(pilot, lambda: modal._active_tab == "config")
            hub = modal.query_one("#config", ConfigHubPane)
            await wait_for(pilot, lambda: "xprompts" in hub._panes)

            assert calls == ["xprompts"]
            assert hub._active_subtab == "xprompts"
            assert "flags" not in hub._subtab_order
            assert validated_config_subtab("flags") is None
            _assert_hub_caption(hub, "xprompts")


async def test_flags_off_prefix_keeps_five_child_numbering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    with override_flags(admin_center_flags=False):
        async with _HostApp().run_test() as pilot:
            modal = ConfigCenterModal(initial_tab="config")
            pilot.app.push_screen(modal)
            await wait_for(pilot, lambda: modal._active_tab == "config")
            hub = modal.query_one("#config", ConfigHubPane)
            await wait_for(pilot, lambda: "xprompts" in hub._panes)

            await pilot.press("0", "1")
            await wait_for(pilot, lambda: hub._active_subtab == "misc")
            _assert_hub_caption(hub, "misc")
            await pilot.press("0", "5")
            await wait_for(pilot, lambda: hub._active_subtab == "xprompts")
            await pilot.press("0", "6")
            await pilot.pause()
            assert hub._active_subtab == "xprompts"
            _assert_hub_caption(hub, "xprompts")


async def test_flags_direct_entry_shows_flags_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    with override_flags(admin_center_flags=True):
        async with _HostApp().run_test() as pilot:
            modal = ConfigCenterModal(
                initial_tab="config",
                config_entry=ConfigHubEntry(subtab="flags"),
            )
            pilot.app.push_screen(modal)
            await wait_for(pilot, lambda: modal._active_tab == "config")
            hub = modal.query_one("#config", ConfigHubPane)
            await wait_for(pilot, lambda: "flags" in hub._panes)

            assert calls == ["flags"]
            _assert_hub_caption(hub, "flags")
            assert "flags" in hub._subtab_order
