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
    make_worker_bucket_views,
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
    patch_alias_views(monkeypatch, make_worker_bucket_views())

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
            make_alias_view("small_worker", "role", override=make_override()),
            make_alias_view("medium_worker", "role"),
            make_alias_view("large_worker", "role"),
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
        await pilot.press("j", "l", "x")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    clear_mock.assert_called_once_with("small_worker")
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
        assert panel._highlighted_row_id() == "default"
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
            "small_worker",
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
            "Builtin alias @small_worker is configured under "
            "llm_provider.model_aliases.custom. Move its model value from "
            "llm_provider.model_aliases.custom to "
            "llm_provider.model_aliases.builtin.",
            severity="warning",
        )

        await pilot.press("j")
        option_list = panel.query_one("#models-panel-list", OptionList)
        bucket_index = option_list.get_option_index("bucket:worker")
        bucket_row = option_list.get_option_at_index(bucket_index).prompt.plain
        assert "▸ ! bucket" in bucket_row
        assert "! 1 misplaced" in bucket_row
        assert "1 override" in bucket_row
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "@small_worker" in description
        assert "llm_provider.model_aliases.custom" in description
        assert "llm_provider.model_aliases.builtin" in description

        await pilot.press("l")
        await pilot.pause()
        coder_row = option_list.get_option_at_index(0).prompt.plain
        assert coder_row.startswith("  ! role")
        assert "override · 1h left" in coder_row

        panel._refresh_rows(keep="small_worker")
        await pilot.pause()
        assert option_list.get_option_at_index(0).prompt.plain.startswith("  ! role")
        panel.notify.assert_called_once()

        await pilot.press("h")
        await pilot.pause()
        bucket_index = option_list.get_option_index("bucket:worker")
        assert (
            "▸ ! bucket" in option_list.get_option_at_index(bucket_index).prompt.plain
        )
        panel.notify.assert_called_once()

        views[:] = [
            make_alias_view("default", "default"),
            make_alias_view(
                "small_worker",
                "role",
                configured=True,
                configured_source="builtin",
                override=make_override(),
            ),
        ]
        panel._refresh_rows(keep="bucket:worker")
        await pilot.pause()
        repaired_bucket_index = option_list.get_option_index("bucket:worker")
        repaired_bucket_row = option_list.get_option_at_index(
            repaired_bucket_index
        ).prompt.plain
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
            "Models › ▌ research · custom bucket\ndefault effort: provider default"
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


async def test_panel_worker_bucket_navigation_and_member_order(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        await pilot.press("j")
        assert panel._highlighted_row_id() == "bucket:worker"
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "Size-specific phase-agent aliases" in description
        assert "claude/opus ×2" in description

        await pilot.press("l")
        await pilot.pause()
        assert panel._active_bucket == "worker"
        assert list(panel._row_by_id) == [
            "xsmall_worker",
            "small_worker",
            "medium_worker",
            "large_worker",
            "xlarge_worker",
        ]
        assert panel._highlighted_row_id() == "xsmall_worker"

        await pilot.press("j")
        assert panel._highlighted_row_id() == "small_worker"

        await pilot.press("j")
        assert panel._highlighted_row_id() == "medium_worker"

        await pilot.press("h")
        await pilot.pause()
        assert panel._active_bucket is None
        assert panel._highlighted_row_id() == "bucket:worker"


@pytest.mark.parametrize("member_steps", [[], ["j", "j"]])
async def test_panel_worker_members_open_override_picker(
    monkeypatch, member_steps: list[str]
) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())

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
        assert panel.query_one("#models-panel-list", OptionList).option_count == 5


async def test_panel_navigation_skips_headers_and_empty_hint_with_wrap(
    monkeypatch,
) -> None:
    views = [
        make_alias_view("default", "default"),
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

        assert panel._highlighted_row_id() == "default"
        assert option_list.get_option_at_index(0).disabled is True
        assert option_list.get_option_at_index(2).disabled is True
        assert set(panel._row_by_id) == {"default", "researcher"}

        await pilot.press("j")
        assert panel._highlighted_row_id() == "researcher"
        await pilot.press("j")
        assert panel._highlighted_row_id() == "default"
        await pilot.press("k")
        assert panel._highlighted_row_id() == "researcher"

        views[:] = [make_alias_view("default", "default")]
        panel._refresh_rows(keep="default")
        await pilot.pause()
        assert option_list.option_count == 4
        assert option_list.get_option_at_index(3).disabled is True
        assert "llm_provider.model_aliases.custom" in (
            option_list.get_option_at_index(3).prompt.plain
        )

        await pilot.press("j", "k")
        assert panel._highlighted_row_id() == "default"


async def test_panel_decorative_option_ids_never_resolve_to_actions(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        option_list = panel.query_one("#models-panel-list", OptionList)

        decorative_ids = [
            str(option_list.get_option_at_index(index).id) for index in (0, 2, 3)
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
        make_alias_view("default", "default"),
        make_alias_view(
            "small_worker",
            "role",
        ),
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
        await pilot.press("j", "l")
        await pilot.pause()

        option_list = panel.query_one("#models-panel-list", OptionList)
        assert panel._active_bucket == "worker"
        assert panel._highlighted_row_id() == "small_worker"
        assert option_list.option_count == 4
        assert option_list.get_option_at_index(0).disabled is True
        assert option_list.get_option_at_index(2).disabled is True
        assert panel.query_one("#models-panel-title", Static).content.plain == (
            "Models › worker · built-in bucket"
            "\ndefault effort: provider default"
            "\nmax running agents: 10"
        )

        await pilot.press("j")
        assert panel._highlighted_row_id() == "phase_reviewer"
        panel._refresh_rows(keep="phase_reviewer")
        await pilot.pause()
        assert panel._highlighted_row_id() == "phase_reviewer"
        await pilot.press("j")
        assert panel._highlighted_row_id() == "small_worker"
        await pilot.press("k")
        assert panel._highlighted_row_id() == "phase_reviewer"

        await pilot.press("h")
        await pilot.pause()
        assert panel._highlighted_row_id() == "bucket:worker"


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
