"""Mounted Models panel row-model and cursor movement tests."""

from unittest.mock import MagicMock

from textual.widgets import OptionList, Static

from sase.ace.tui.modals.models_panel import ModelsPanel
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_worker_bucket_views,
    patch_alias_views,
)


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
