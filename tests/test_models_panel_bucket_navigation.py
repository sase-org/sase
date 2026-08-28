"""Mounted Models panel bucket drill-in and restore tests."""

import threading
from unittest.mock import MagicMock

from textual.widgets import OptionList, Static

from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.ace.tui.modals.models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    LaunchModelSettingRow,
)
from sase.llm_provider.config import (
    BIG_EPIC_LANDER_MODEL_FIELD,
    DEFAULT_MODEL_FIELD,
    EPIC_LANDER_MODEL_FIELD,
    LaunchModelSettingSnapshot,
)
from sase.llm_provider.model_launch_settings import LaunchModelField
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_bucketed_views,
    patch_alias_views,
    wait_for,
    wait_for_snapshot_idle,
)


def _launch_setting_row(
    field: LaunchModelField,
    label: str,
) -> LaunchModelSettingRow:
    return LaunchModelSettingRow(
        field=field,
        label=label,
        detail="Used when a launch has no explicit %model directive.",
        snapshot=LaunchModelSettingSnapshot(
            field=field,
            config_path=f"llm_provider.{field}",
            raw_value="@large",
            provider="claude",
            model="opus",
            effort=None,
            provenance="shipped",
            referenced_alias="large",
            override_key=f"setting:{field}",
        ),
    )


def _launch_setting_rows() -> tuple[
    LaunchModelSettingRow | BigEpicPhaseThresholdSettingRow, ...
]:
    return (
        _launch_setting_row(DEFAULT_MODEL_FIELD, "default model"),
        _launch_setting_row(EPIC_LANDER_MODEL_FIELD, "epic lander"),
        _launch_setting_row(BIG_EPIC_LANDER_MODEL_FIELD, "big epic lander"),
        BigEpicPhaseThresholdSettingRow(5),
    )


async def test_panel_l_drills_into_bucket_and_h_restores_bucket(monkeypatch) -> None:
    patch_alias_views(
        monkeypatch,
        make_bucketed_views(),
        bucket_descriptions={"research": "Research roles."},
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        highlight_row(panel, "bucket:research")

        assert panel._highlighted_row_id() == "bucket:research"
        assert "l/enter" in str(panel.query_one("#models-panel-footer", Static).content)
        assert (
            "Research roles."
            in panel.query_one("#models-panel-description", Static).content.plain
        )

        await pilot.press("l")
        await pilot.pause()
        assert panel._active_bucket == "research"
        assert panel._highlighted_row_id() == "research_a"
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Launch Control › ▌ research · custom bucket"
        )
        assert "h" in str(panel.query_one("#models-panel-footer", Static).content)

        await pilot.press("h")
        await pilot.pause()
        assert panel._active_bucket is None
        assert panel._highlighted_row_id() == "bucket:research"
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Launch Control"
        )


async def test_panel_enter_drills_into_bucket(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_bucketed_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await wait_for(pilot, lambda: "bucket:research" in panel._row_by_id)
        highlight_row(panel, "bucket:research")
        await pilot.press("enter")
        await pilot.pause()

        assert panel._active_bucket == "research"
        assert panel._highlighted_row_id() == "research_a"


async def test_delayed_provider_snapshot_keeps_bucket_for_guarded_edit(
    monkeypatch,
) -> None:
    """A late initial snapshot must not steal a bucket selection before `e`."""
    views = make_bucketed_views()
    patch_alias_views(monkeypatch, views)
    snapshot = ProviderRoutingSnapshot(
        statuses=(),
        provider_disables={},
        alias_views=tuple(views),
        provider_colors={},
        captured_at=0.0,
        launch_model_rows=_launch_setting_rows(),
    )
    started = threading.Event()
    release = threading.Event()

    def load_snapshot(self: ModelsPanel) -> ProviderRoutingSnapshot:
        started.set()
        release.wait()
        return snapshot

    monkeypatch.setattr(ModelsPanel, "_load_provider_routing_snapshot", load_snapshot)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel._views = list(views)
        panel.notify = MagicMock()  # type: ignore[method-assign]
        try:
            pilot.app.push_screen(panel)
            await wait_for(pilot, started.is_set)
            await wait_for(pilot, lambda: panel._provider_snapshot_worker is not None)
            worker = panel._provider_snapshot_worker
            assert worker is not None
            await wait_for(pilot, lambda: "bucket:research" in panel._row_by_id)
            assert "launch:default_model" in panel._row_by_id
            assert "setting:big_epic_phase_threshold" in panel._row_by_id
            highlight_row(panel, "bucket:research")
            assert panel._highlighted_row_id() == "bucket:research"

            release.set()
            await worker.wait()
            await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
            assert panel._highlighted_row_id() == "bucket:research"
            assert "launch:default_model" in panel._row_by_id

            await pilot.press("e")
            await pilot.pause()

            assert pilot.app.screen is panel
            panel.notify.assert_called_once_with(
                "Press `l`/`enter` to open this bucket"
            )
        finally:
            release.set()


async def test_refresh_auto_leaves_bucket_when_last_member_disappears(
    monkeypatch,
) -> None:
    views = make_bucketed_views()
    patch_alias_views(monkeypatch, views)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "bucket:research")
        await pilot.press("l")
        await pilot.pause()
        assert panel._active_bucket == "research"

        views[:] = [view for view in views if view.bucket != "research"]
        panel._refresh_rows(keep="research_a")
        await wait_for_snapshot_idle(pilot, panel)

        assert panel._active_bucket is None
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Launch Control"
        )
        assert "plain" in panel._row_by_id


async def test_panel_mixed_bucket_sections_title_and_restore(monkeypatch) -> None:
    views = [
        make_alias_view("large", "role"),
        make_alias_view(
            "phase_reviewer",
            "user",
            configured=True,
            configured_source="custom",
            bucket="worker",
        ),
    ]
    patch_alias_views(monkeypatch, views)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "bucket:worker")
        await pilot.press("l")
        await pilot.pause()

        option_list = panel.query_one("#models-panel-list", OptionList)
        assert panel._active_bucket == "worker"
        assert panel._highlighted_row_id() == "phase_reviewer"
        assert option_list.option_count == 1
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Launch Control › ▌ worker · custom bucket"
        )

        panel._refresh_rows(keep="phase_reviewer")
        await wait_for_snapshot_idle(pilot, panel)
        assert panel._highlighted_row_id() == "phase_reviewer"

        await pilot.press("h")
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)
        assert panel._highlighted_row_id() == "bucket:worker"
