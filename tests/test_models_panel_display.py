"""Mounted Models panel title, description strip, and warning toast tests."""

from unittest.mock import MagicMock

from textual.widgets import OptionList, Static

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.models_panel import ModelsPanel
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_override,
    patch_alias_views,
)


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
