"""Mounted Models panel geometry tests under production styles."""

from textual.containers import Container
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.models_panel import ModelsPanel
from tests._models_panel_helpers import (
    StyledModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_long_pool_views,
    patch_alias_views,
    wait_for_snapshot_idle,
)


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
        await wait_for_snapshot_idle(pilot, panel)
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
        await wait_for_snapshot_idle(pilot, panel)
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
        await wait_for_snapshot_idle(pilot, panel)
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
        await wait_for_snapshot_idle(pilot, panel)
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
