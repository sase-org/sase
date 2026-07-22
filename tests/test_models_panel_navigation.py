"""Mounted Models panel navigation and layout tests."""

from unittest.mock import MagicMock

import pytest
from textual.containers import Container
from textual.widgets import OptionList, Static

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.model_picker_modal import ModelPickerModal
from sase.ace.tui.modals.models_panel import ModelsPanel, ModelsPanelResult
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    StyledModelsPanelTestApp,
    make_alias_view,
    make_bucketed_views,
    make_coder_bucket_views,
    make_phase_worker_bucket_views,
    make_override,
    patch_alias_views,
)


async def test_panel_escape_closes_unchanged(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])
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
    patch_alias_views(monkeypatch, make_coder_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("j", "l", "o")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_panel_x_clears_active_override(monkeypatch) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("default", "default"),
            make_alias_view("coder", "role"),
            make_alias_view("small_phase_worker", "role", override=make_override()),
            make_alias_view("medium_phase_worker", "role"),
            make_alias_view("large_phase_worker", "role"),
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
        await pilot.press("j", "j", "l", "x")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    clear_mock.assert_called_once_with("small_phase_worker")
    assert isinstance(result, ModelsPanelResult)
    assert result.changed is True


async def test_panel_x_without_override_does_not_clear(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_coder_bucket_views())
    clear_mock = MagicMock()
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j", "l", "x")
        await pilot.pause()
        clear_mock.assert_not_called()
        assert panel._changed is False


async def test_panel_description_strip_updates_on_highlight(monkeypatch) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("default", "default", description="Default model."),
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
        description = panel.query_one("#models-panel-description", Static)
        assert "Default model." in description.content.plain
        await pilot.press("j")
        await pilot.pause()
        assert "Draft blog posts." in description.content.plain


async def test_panel_does_not_warn_for_clean_alias_views(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()

        panel.notify.assert_not_called()


async def test_panel_warns_once_and_keeps_bucket_warning_through_refresh(
    monkeypatch,
) -> None:
    views = [
        make_alias_view("default", "default"),
        make_alias_view(
            "codex_coder",
            "provider_coder",
            configured=True,
            configured_source="custom",
            provider="codex",
            model="o3",
        ),
        make_alias_view(
            "coder",
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
            "Builtin aliases @coder, @codex_coder are configured under "
            "llm_provider.model_aliases.custom. Move each custom entry's model "
            "value from llm_provider.model_aliases.custom to "
            "llm_provider.model_aliases.builtin.",
            severity="warning",
        )

        await pilot.press("j")
        option_list = panel.query_one("#models-panel-list", OptionList)
        bucket_row = option_list.get_option_at_index(1).prompt.plain
        assert "▸ ! bucket" in bucket_row
        assert "! 2 misplaced" in bucket_row
        assert "1 override" in bucket_row
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "@coder, @codex_coder" in description
        assert "llm_provider.model_aliases.custom" in description
        assert "llm_provider.model_aliases.builtin" in description

        await pilot.press("l")
        await pilot.pause()
        coder_row = option_list.get_option_at_index(0).prompt.plain
        assert coder_row.startswith("! role")
        assert "override · 1h left" in coder_row

        panel._refresh_rows(keep="coder")
        await pilot.pause()
        assert option_list.get_option_at_index(0).prompt.plain.startswith("! role")
        panel.notify.assert_called_once()

        await pilot.press("h")
        await pilot.pause()
        assert "▸ ! bucket" in option_list.get_option_at_index(1).prompt.plain
        panel.notify.assert_called_once()

        views[:] = [
            make_alias_view("default", "default"),
            make_alias_view(
                "coder",
                "role",
                configured=True,
                configured_source="builtin",
                override=make_override(),
            ),
            make_alias_view(
                "codex_coder",
                "provider_coder",
                configured=True,
                configured_source="builtin",
                provider="codex",
                model="o3",
            ),
        ]
        panel._refresh_rows(keep="bucket:coders")
        await pilot.pause()
        repaired_bucket_row = option_list.get_option_at_index(1).prompt.plain
        assert "!" not in repaired_bucket_row
        assert "override · 1 active" in repaired_bucket_row
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

        await pilot.press("j", "j")

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
            "Models › research\ndefault effort: provider default"
            "\nmax running agents: 10"
        )
        assert "h" in str(panel.query_one("#models-panel-footer", Static).content)

        await pilot.press("h")
        await pilot.pause()
        assert panel._active_bucket is None
        assert panel._highlighted_row_id() == "bucket:research"
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Models\ndefault effort: provider default\nmax running agents: 10"
        )


async def test_panel_enter_drills_into_bucket(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_bucketed_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j", "j")
        await pilot.press("enter")
        await pilot.pause()

        assert panel._active_bucket == "research"
        assert panel._highlighted_row_id() == "research_a"


async def test_panel_coders_bucket_navigation_and_refresh_restore(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_coder_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        await pilot.press("j")
        assert panel._highlighted_row_id() == "bucket:coders"
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "Generic coder default" in description
        assert "claude/opus ×2" in description

        await pilot.press("l")
        await pilot.pause()
        assert panel._active_bucket == "coders"
        assert list(panel._row_by_id) == ["coder", "claude_coder", "codex_coder"]
        assert panel._highlighted_row_id() == "coder"

        await pilot.press("j")
        assert panel._highlighted_row_id() == "claude_coder"
        panel._refresh_rows(keep="claude_coder")
        await pilot.pause()
        assert panel._active_bucket == "coders"
        assert panel._highlighted_row_id() == "claude_coder"

        await pilot.press("h")
        await pilot.pause()
        assert panel._active_bucket is None
        assert panel._highlighted_row_id() == "bucket:coders"


async def test_panel_phase_worker_bucket_navigation_and_member_order(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, make_phase_worker_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        await pilot.press("j", "j")
        assert panel._highlighted_row_id() == "bucket:phase_worker"
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "Size-specific phase-agent aliases" in description
        assert "claude/sonnet ×2" in description

        await pilot.press("l")
        await pilot.pause()
        assert panel._active_bucket == "phase_worker"
        assert list(panel._row_by_id) == [
            "small_phase_worker",
            "medium_phase_worker",
            "large_phase_worker",
        ]
        assert panel._highlighted_row_id() == "small_phase_worker"

        await pilot.press("j")
        assert panel._highlighted_row_id() == "medium_phase_worker"

        await pilot.press("h")
        await pilot.pause()
        assert panel._active_bucket is None
        assert panel._highlighted_row_id() == "bucket:phase_worker"


@pytest.mark.parametrize("member_steps", [[], ["j", "j"]])
async def test_panel_coders_members_open_override_picker(
    monkeypatch, member_steps: list[str]
) -> None:
    patch_alias_views(monkeypatch, make_coder_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("j", "l", *member_steps, "o")
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
        await pilot.press("j", "j")
        await pilot.press(key)
        await pilot.pause()

        assert pilot.app.screen is panel
        panel.notify.assert_called_once_with("Press `l`/`enter` to open this bucket")


async def test_refresh_auto_leaves_bucket_when_last_member_disappears(
    monkeypatch,
) -> None:
    views = make_bucketed_views()
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: views)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: None,
    )
    monkeypatch.setattr(models_panel, "_now", lambda: 0.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j", "j", "l")
        await pilot.pause()
        assert panel._active_bucket == "research"

        views[:] = [view for view in views if view.bucket != "research"]
        panel._refresh_rows(keep="research_a")
        await pilot.pause()

        assert panel._active_bucket is None
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Models\ndefault effort: provider default\nmax running agents: 10"
        )
        assert panel.query_one("#models-panel-list", OptionList).option_count == 3


async def test_panel_title_shows_configured_default_effort(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])
    effort = MagicMock(return_value="xhigh")
    monkeypatch.setattr(models_panel, "default_reasoning_effort", effort)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Models\ndefault effort: @ xhigh\nmax running agents: 10"
        )
        effort.assert_called_once_with()


async def test_panel_preferred_width_fits_production_description(monkeypatch) -> None:
    """The description strip has a non-zero content area with production CSS."""
    description_text = (
        "Model used when a prompt has no %model directive; every other alias "
        "ultimately falls back to it."
    )
    assert len(description_text) == 96
    patch_alias_views(
        monkeypatch,
        [make_alias_view("default", "default", description=description_text)],
    )

    async with StyledModelsPanelTestApp().run_test(size=(120, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)
        description = panel.query_one("#models-panel-description", Static)
        assert container.region.width == 110
        assert description.content.plain == description_text
        assert description.content_size.width >= len(description_text)
        assert description.content_size.height == 2


async def test_panel_width_is_contained_by_narrow_viewport(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])

    async with StyledModelsPanelTestApp().run_test(size=(80, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        container = panel.query_one("#models-panel-container", Container)

        assert container.region.x >= 0
        assert container.region.right <= panel.size.width
