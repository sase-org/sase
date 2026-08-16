"""Models-panel provider-routing integration tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from textual.widgets import OptionList, Static
from textual.worker import WorkerState

import sase.ace.tui.modals.models_panel as models_panel_module
import sase.ace.tui.modals.models_panel_provider_state as provider_state
import sase.ace.tui.modals.models_panel_providers as providers
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_state import (
    ProviderRoutingSnapshot,
    load_provider_routing_snapshot,
)
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    make_bucketed_views,
    patch_alias_views,
    wait_for,
)
from tests._models_panel_provider_routing_helpers import (
    disable as _disable,
    launch_setting_rows as _launch_setting_rows,
    snapshot as _snapshot,
    status as _status,
)


def test_panel_sync_row_build_uses_captured_rows_without_provider_read(
    monkeypatch,
) -> None:
    disable = _disable("codex", expires_at=None)
    panel = ModelsPanel()
    panel._provider_disables = {"codex": disable}
    panel._views = [make_alias_view("medium", "role")]
    provider_read = MagicMock(side_effect=AssertionError("synchronous provider read"))
    monkeypatch.setattr(provider_state, "get_active_provider_disables", provider_read)
    build_alias_views = MagicMock(side_effect=AssertionError("synchronous alias read"))
    monkeypatch.setattr(models_panel_module, "build_alias_views", build_alias_views)

    panel._build_options()

    provider_read.assert_not_called()
    build_alias_views.assert_not_called()


def test_provider_snapshot_worker_path_reads_authoritative_state(monkeypatch) -> None:
    disable = _disable("codex", expires_at=None)
    provider_read = MagicMock(return_value={"codex": disable})
    status_mock = MagicMock(return_value=(_status("codex", active_disable=disable),))
    view_mock = MagicMock(return_value=[make_alias_view("medium", "role")])
    color_mock = MagicMock(return_value={"codex": "#10A37F"})
    monkeypatch.setattr(provider_state, "get_active_provider_disables", provider_read)
    monkeypatch.setattr(provider_state, "build_provider_routing_statuses", status_mock)
    monkeypatch.setattr(provider_state, "build_alias_views", view_mock)
    monkeypatch.setattr(provider_state, "provider_cli_status_color_map", color_mock)

    snapshot = load_provider_routing_snapshot(100.0)

    provider_read.assert_called_once_with(100.0)
    status_mock.assert_called_once_with({"codex": disable})
    view_mock.assert_called_once_with(now=100.0, provider_disables={"codex": disable})
    color_mock.assert_called_once_with()
    assert snapshot.provider_disables == {"codex": disable}


async def test_panel_p_opens_provider_routing_modal(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    snapshot = _snapshot(_status("claude"), _status("codex"))
    monkeypatch.setattr(
        providers,
        "load_provider_routing_snapshot",
        lambda _now=None: snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ProviderRoutingModal)


async def test_panel_initial_provider_snapshot_does_not_mark_routing_changed(
    monkeypatch,
) -> None:
    views = [make_alias_view("medium", "role")]
    patch_alias_views(monkeypatch, views)
    disable = _disable("codex", expires_at=None)
    snapshot = _snapshot(
        _status("codex", active_disable=disable),
        disables={"codex": disable},
        alias_views=views,
    )
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await wait_for(pilot, lambda: panel._provider_snapshot is snapshot)

    assert panel._changed is False
    assert panel._provider_routing_changed is False
    assert panel._provider_disables == {"codex": disable}


def test_panel_ignores_stale_provider_snapshot_worker_event() -> None:
    panel = ModelsPanel()
    current_worker = SimpleNamespace(is_finished=False, cancel=MagicMock())
    stale_worker = SimpleNamespace(
        result=_snapshot(_status("codex")),
        error=None,
    )
    panel._provider_snapshot_worker = current_worker

    handled = panel._on_provider_snapshot_worker_state(
        SimpleNamespace(worker=stale_worker, state=WorkerState.SUCCESS)
    )

    assert handled is False
    assert panel._provider_snapshot_worker is current_worker
    assert panel._provider_statuses == ()


async def test_panel_expired_provider_disable_refresh_marks_routing_changed_once(
    monkeypatch,
) -> None:
    views = [make_alias_view("medium", "role")]
    patch_alias_views(monkeypatch, views)
    disable = _disable("codex", expires_at=100.0)
    before = _snapshot(
        _status("codex", active_disable=disable),
        disables={"codex": disable},
        alias_views=views,
    )
    after = _snapshot(_status("codex"), disables={}, alias_views=views)
    load_snapshot = MagicMock(return_value=after)
    clock = MagicMock(return_value=101.0)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: before,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
        panel._apply_provider_snapshot(before, update_rows=True)
        monkeypatch.setattr(panel, "_models_panel_now", clock)
        monkeypatch.setattr(panel, "_load_provider_routing_snapshot", load_snapshot)

        panel._refresh_provider_clock()
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
        assert panel._changed is True
        assert panel._provider_routing_changed is True
        panel._changed = False
        panel._provider_routing_changed = False
        panel._refresh_provider_clock()
        await pilot.pause()

    load_snapshot.assert_called_once_with()
    assert panel._provider_disables == {}
    assert panel._changed is False
    assert panel._provider_routing_changed is False


async def test_panel_provider_modal_snapshot_rebuilds_rows_and_keeps_cursor(
    monkeypatch,
) -> None:
    before_views = [
        make_alias_view("large", "role"),
        make_alias_view("medium", "role"),
    ]
    after_views = [
        make_alias_view("large", "role", provider="codex", model="o3"),
        make_alias_view("medium", "role", provider="codex", model="o3"),
    ]
    patch_alias_views(monkeypatch, before_views)
    initial_snapshot = _snapshot(_status("codex"), alias_views=before_views)
    snapshot = _snapshot(_status("codex"), alias_views=after_views)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: initial_snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
        option_list = panel.query_one("#models-panel-list", OptionList)
        option_list.highlighted = option_list.get_option_index("medium")

        panel._on_provider_modal_snapshot(snapshot, "codex")
        await pilot.pause()

        assert panel._views == after_views
        assert panel._highlighted_row_id() == "medium"
        assert panel._changed is True
        assert panel._provider_routing_changed is True


async def test_models_panel_title_shows_disabled_provider_line(monkeypatch) -> None:
    views = [make_alias_view("medium", "role")]
    patch_alias_views(monkeypatch, views)
    disable = _disable("claude", expires_at=None)
    snapshot = ProviderRoutingSnapshot(
        statuses=(_status("claude", active_disable=disable),),
        provider_disables={"claude": disable},
        alias_views=tuple(views),
        provider_colors={"claude": "#D97757"},
        captured_at=100.0,
    )
    monkeypatch.setattr(provider_state, "_now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        panel._apply_provider_snapshot(snapshot, keep="medium")
        await pilot.pause()

        title = panel.query_one("#models-panel-title", Static).content.plain
        assert "disabled providers: CLAUDE until cleared" in title


def _highlight_row(panel: ModelsPanel, row_id: str) -> None:
    option_list = panel.query_one("#models-panel-list", OptionList)
    panel._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    panel._update_context()


async def test_provider_snapshot_explicit_keep_overrides_current_row(
    monkeypatch,
) -> None:
    views = make_bucketed_views()
    patch_alias_views(monkeypatch, views)
    snapshot = _snapshot(
        _status("codex"),
        alias_views=views,
        launch_model_rows=_launch_setting_rows(),
    )
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await wait_for(pilot, lambda: panel._provider_snapshot is snapshot)
        await wait_for(pilot, lambda: "bucket:research" in panel._row_by_id)
        _highlight_row(panel, "bucket:research")
        assert panel._highlighted_row_id() == "bucket:research"

        panel._apply_provider_snapshot(snapshot, keep="plain", update_rows=True)
        await pilot.pause()

        assert panel._highlighted_row_id() == "plain"


async def test_provider_snapshot_missing_row_falls_back_to_first_launch_row(
    monkeypatch,
) -> None:
    views = make_bucketed_views()
    remaining = [view for view in views if view.bucket != "research"]
    patch_alias_views(monkeypatch, views)
    before = _snapshot(
        _status("codex"),
        alias_views=views,
        launch_model_rows=_launch_setting_rows(),
    )
    after = _snapshot(
        _status("codex"),
        alias_views=remaining,
        launch_model_rows=_launch_setting_rows(),
    )
    monkeypatch.setattr(
        ModelsPanel,
        "_load_provider_routing_snapshot",
        lambda self: before,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await wait_for(pilot, lambda: panel._provider_snapshot is before)
        await wait_for(pilot, lambda: "bucket:research" in panel._row_by_id)
        _highlight_row(panel, "bucket:research")
        assert panel._highlighted_row_id() == "bucket:research"

        panel._apply_provider_snapshot(after, update_rows=True)
        await pilot.pause()

        assert "bucket:research" not in panel._row_by_id
        assert panel._highlighted_row_id() == "launch:default_model"
