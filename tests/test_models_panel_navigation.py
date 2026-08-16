"""Mounted Models panel navigation and layout tests."""

import threading
from unittest.mock import MagicMock

import pytest
from textual.containers import Container
from textual.widgets import OptionList, Static

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.model_picker_modal import ModelPickerModal
from sase.ace.tui.modals.models_panel import ModelsPanel, ModelsPanelResult
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
    StyledModelsPanelTestApp,
    make_alias_view,
    make_bucketed_views,
    make_long_pool_views,
    make_worker_bucket_views,
    make_override,
    patch_alias_views,
    wait_for,
)


def highlight_row(panel: ModelsPanel, row_id: str) -> None:
    option_list = panel.query_one("#models-panel-list", OptionList)
    panel._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    panel._update_context()


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
        _launch_setting_row(DEFAULT_MODEL_FIELD, "launch model"),
        _launch_setting_row(EPIC_LANDER_MODEL_FIELD, "epic lander"),
        _launch_setting_row(BIG_EPIC_LANDER_MODEL_FIELD, "big epic lander"),
        BigEpicPhaseThresholdSettingRow(5),
    )


async def test_panel_escape_closes_unchanged(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    result: ModelsPanelResult | None = None

    async with ModelsPanelTestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert isinstance(result, ModelsPanelResult)
    assert result.changed is False


async def test_panel_o_opens_model_picker(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_panel_x_clears_active_override(monkeypatch) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("xsmall", "role"),
            make_alias_view("small", "role", override=make_override()),
            make_alias_view("medium", "role"),
            make_alias_view("large", "role"),
        ],
    )
    clear_mock = MagicMock(return_value=True)
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)
    result: ModelsPanelResult | None = None

    async with ModelsPanelTestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        panel = pilot.app.screen
        assert isinstance(panel, ModelsPanel)
        highlight_row(panel, "small")
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    clear_mock.assert_called_once_with("small")
    assert isinstance(result, ModelsPanelResult)
    assert result.changed is True


async def test_panel_x_without_override_does_not_clear(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())
    clear_mock = MagicMock()
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        clear_mock.assert_not_called()
        assert panel._changed is False


async def test_panel_description_strip_updates_on_highlight(monkeypatch) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("large", "role", description="Default launch model."),
            make_alias_view(
                "blogger",
                "user",
                configured=True,
                configured_source="custom",
                description="Draft blog posts.",
            ),
        ],
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        assert panel._highlighted_row_id() == "launch:default_model"
        description = panel.query_one("#models-panel-description", Static)
        assert "Used when a launch has no explicit" in description.content.plain
        highlight_row(panel, "blogger")
        await pilot.pause()
        assert "Draft blog posts." in description.content.plain


async def test_panel_does_not_warn_for_clean_alias_views(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()

        panel.notify.assert_not_called()


async def test_panel_warns_once_and_keeps_alias_warning_through_refresh(
    monkeypatch,
) -> None:
    views = [
        make_alias_view("large", "role"),
        make_alias_view(
            "small",
            "role",
            configured=True,
            configured_source="custom",
            override=make_override(),
        ),
    ]
    patch_alias_views(monkeypatch, views)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()

        panel.notify.assert_called_once_with(
            "Builtin alias @small is configured under "
            "llm_provider.model_aliases.custom. Move its model value from "
            "llm_provider.model_aliases.custom to "
            "llm_provider.model_aliases.builtin.",
            severity="warning",
        )

        option_list = panel.query_one("#models-panel-list", OptionList)
        alias_index = option_list.get_option_index("small")
        alias_row = option_list.get_option_at_index(alias_index).prompt.plain
        assert alias_row.startswith("  ! small")
        assert "override · 1h left" in alias_row
        highlight_row(panel, "small")
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "@small" in description
        assert "llm_provider.model_aliases.custom" in description
        assert "llm_provider.model_aliases.builtin" in description

        panel._refresh_rows(keep="small")
        await pilot.pause()
        alias_index = option_list.get_option_index("small")
        assert option_list.get_option_at_index(alias_index).prompt.plain.startswith(
            "  ! small"
        )
        panel.notify.assert_called_once()

        views[:] = [
            make_alias_view("large", "role"),
            make_alias_view(
                "small",
                "role",
                configured=True,
                configured_source="builtin",
                override=make_override(),
            ),
        ]
        panel._refresh_rows(keep="small")
        await pilot.pause()
        repaired_alias_index = option_list.get_option_index("small")
        repaired_alias_row = option_list.get_option_at_index(
            repaired_alias_index
        ).prompt.plain
        assert repaired_alias_row.startswith("  small")
        assert "override · 1h left" in repaired_alias_row
        panel.notify.assert_called_once()


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


async def test_panel_size_alias_navigation_and_order(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        assert list(panel._row_by_id) == [
            "launch:default_model",
            "launch:epic_lander_model",
            "launch:big_epic_lander_model",
            "setting:big_epic_phase_threshold",
            "setting:default_effort",
            "setting:runner_limit",
            "xsmall",
            "small",
            "medium",
            "large",
            "xlarge",
        ]
        assert panel._highlighted_row_id() == "launch:default_model"
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "llm_provider.default_model" in description

        highlight_row(panel, "xsmall")
        assert panel._highlighted_row_id() == "xsmall"
        await pilot.press("j")
        assert panel._highlighted_row_id() == "small"

        await pilot.press("j")
        assert panel._highlighted_row_id() == "medium"


@pytest.mark.parametrize("member_steps", [[], ["j", "j"]])
async def test_panel_size_aliases_open_override_picker(
    monkeypatch, member_steps: list[str]
) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press(*member_steps, "o")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelPickerModal)


@pytest.mark.parametrize("key", ["o", "x", "e", "r"])
async def test_alias_actions_on_bucket_are_guarded(monkeypatch, key: str) -> None:
    patch_alias_views(monkeypatch, make_bucketed_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "bucket:research")
        await pilot.press(key)
        await pilot.pause()

        assert pilot.app.screen is panel
        panel.notify.assert_called_once_with("Press `l`/`enter` to open this bucket")


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
        assert release.wait(timeout=5)
        return snapshot

    monkeypatch.setattr(ModelsPanel, "_load_provider_routing_snapshot", load_snapshot)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel._views = list(views)
        panel.notify = MagicMock()  # type: ignore[method-assign]
        try:
            pilot.app.push_screen(panel)
            await wait_for(pilot, started.is_set)
            await wait_for(pilot, lambda: "bucket:research" in panel._row_by_id)
            assert "launch:default_model" in panel._row_by_id
            assert "setting:big_epic_phase_threshold" in panel._row_by_id
            highlight_row(panel, "bucket:research")
            assert panel._highlighted_row_id() == "bucket:research"

            release.set()
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
        await pilot.pause()

        assert panel._active_bucket is None
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Launch Control"
        )
        assert "plain" in panel._row_by_id


async def test_panel_navigation_skips_headers_and_empty_hint_with_wrap(
    monkeypatch,
) -> None:
    views = [
        make_alias_view("large", "role"),
        make_alias_view(
            "researcher",
            "user",
            configured=True,
            configured_source="custom",
        ),
    ]
    patch_alias_views(monkeypatch, views)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        option_list = panel.query_one("#models-panel-list", OptionList)

        assert panel._highlighted_row_id() == "launch:default_model"
        assert option_list.get_option_at_index(0).disabled is True
        assert set(panel._row_by_id) == {
            "launch:default_model",
            "launch:epic_lander_model",
            "launch:big_epic_lander_model",
            "setting:big_epic_phase_threshold",
            "setting:default_effort",
            "setting:runner_limit",
            "large",
            "researcher",
        }

        highlight_row(panel, "large")
        await pilot.press("j")
        assert panel._highlighted_row_id() == "researcher"
        await pilot.press("j")
        assert panel._highlighted_row_id() == "launch:default_model"
        await pilot.press("k")
        assert panel._highlighted_row_id() == "researcher"

        views[:] = [make_alias_view("large", "role")]
        panel._refresh_rows(keep="large")
        await pilot.pause()
        assert (
            option_list.get_option_at_index(option_list.option_count - 1).disabled
            is True
        )
        assert "llm_provider.model_aliases.custom" in (
            option_list.get_option_at_index(option_list.option_count - 1).prompt.plain
        )

        await pilot.press("j", "k")
        assert panel._highlighted_row_id() == "large"


async def test_panel_decorative_option_ids_never_resolve_to_actions(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        option_list = panel.query_one("#models-panel-list", OptionList)

        decorative_ids = [
            str(option.id)
            for option in (
                option_list.get_option_at_index(index)
                for index in range(option_list.option_count)
            )
            if option.disabled
        ]
        assert all(row_id not in panel._row_by_id for row_id in decorative_ids)

        for row_id in decorative_ids:
            monkeypatch.setattr(
                panel, "_highlighted_row_id", lambda row_id=row_id: row_id
            )
            assert panel._selected_row() is None
            panel.action_enter_bucket()
            panel.action_override()
            panel.action_clear()
            panel.action_edit()
            panel.action_reset()

        assert pilot.app.screen is panel
        panel.notify.assert_not_called()


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
        await pilot.pause()
        assert panel._highlighted_row_id() == "phase_reviewer"

        await pilot.press("h")
        await pilot.pause()
        assert panel._highlighted_row_id() == "bucket:worker"


async def test_panel_title_shows_configured_default_effort(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    effort = MagicMock(return_value="xhigh")
    monkeypatch.setattr(models_panel, "default_reasoning_effort", effort)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        title = panel.query_one("#models-panel-title", Static).content.plain
        assert title == "Launch Control"
        effort.assert_called_once_with()


async def test_panel_preferred_width_fits_production_description(monkeypatch) -> None:
    """The description strip has a non-zero content area with production CSS."""
    description_text = (
        "Model used when a prompt has no %model directive; delegates to @large "
        "unless configured."
    )
    assert len(description_text) == 88
    patch_alias_views(
        monkeypatch,
        [make_alias_view("large", "role", description=description_text)],
    )

    async with StyledModelsPanelTestApp().run_test(size=(120, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)
        description = panel.query_one("#models-panel-description", Static)
        assert container.region.width == 110
        highlight_row(panel, "large")
        assert description.content.plain == description_text
        assert description.content_size.width >= len(description_text)
        assert description.content_size.height == 2


async def test_panel_width_is_contained_by_narrow_viewport(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])

    async with StyledModelsPanelTestApp().run_test(size=(80, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)

        assert container.region.x >= 0
        assert container.region.right <= panel.size.width


async def test_panel_long_pool_description_fits_at_preferred_width(
    monkeypatch,
) -> None:
    """A wrapped 4-member pool must show every member without clipping anything."""
    patch_alias_views(monkeypatch, make_long_pool_views())

    async with StyledModelsPanelTestApp().run_test(size=(120, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)
        option_list = panel.query_one("#models-panel-list", OptionList)
        description = panel.query_one("#models-panel-description", Static)
        footer = panel.query_one("#models-panel-footer", Static)

        highlight_row(panel, "cheaper")
        await pilot.pause()

        assert "gpt-5.5-mini" in description.content.plain
        assert description.content_size.height >= 3
        assert description.outer_size.height >= description.content_size.height

        assert option_list.outer_size.height >= 3
        assert footer.region.bottom <= container.region.bottom
        assert container.region.bottom <= panel.size.height

        highlight_row(panel, "worker_0")
        await pilot.pause()
        assert "Worker tier 0." in description.content.plain
        assert description.content_size.height == 2


async def test_panel_short_description_keeps_four_row_minimum(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_long_pool_views())

    async with StyledModelsPanelTestApp().run_test(size=(120, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        description = panel.query_one("#models-panel-description", Static)

        highlight_row(panel, "worker_0")
        await pilot.pause()

        assert description.outer_size.height == 4


async def test_panel_long_pool_description_fits_at_narrow_viewport(
    monkeypatch,
) -> None:
    """The same long pool wraps further at 80 columns but must stay fully visible."""
    patch_alias_views(monkeypatch, make_long_pool_views())

    async with StyledModelsPanelTestApp().run_test(size=(80, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)
        option_list = panel.query_one("#models-panel-list", OptionList)
        description = panel.query_one("#models-panel-description", Static)
        footer = panel.query_one("#models-panel-footer", Static)

        highlight_row(panel, "cheaper")
        await pilot.pause()

        assert "gpt-5.5-mini" in description.content.plain
        assert description.content_size.height >= 3
        assert description.outer_size.height >= description.content_size.height

        assert option_list.outer_size.height >= 3
        assert container.region.x >= 0
        assert container.region.right <= panel.size.width
        assert container.region.y >= 0
        assert container.region.bottom <= panel.size.height
        assert footer.region.bottom <= container.region.bottom
