"""ACE TUI PNG snapshots for Models-panel navigation and drill-in states."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from textual.widgets import Input, OptionList

import sase.ace.tui.modals.models_panel as models_panel
import sase.ace.tui.modals.models_panel_providers as models_panel_providers
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from sase.llm_provider import AliasView
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    calm_views,
    effort_snapshot,
    ownership_views,
    override_views,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_alias_views(
    monkeypatch: pytest.MonkeyPatch, factory: Callable[[], list[AliasView]]
) -> None:
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: factory())
    monkeypatch.setattr(
        models_panel_providers, "build_alias_views", lambda *a, **k: factory()
    )


async def _wait_for_models_panel_ready(page: AcePage) -> None:
    def launch_row_is_ready() -> bool:
        screen = page.app.screen
        if not isinstance(screen, ModelsPanel):
            return False
        try:
            option_list = screen.query_one("#models-panel-list", OptionList)
            option_list.get_option_index("launch:default_model")
        except Exception:
            return False
        return True

    await wait_for_state(
        page,
        launch_row_is_ready,
        description="Models-panel launch rows loaded",
    )


def _highlight_row(page: AcePage, row_id: str) -> None:
    screen = page.app.screen
    assert isinstance(screen, ModelsPanel)
    option_list = screen.query_one("#models-panel-list", OptionList)
    screen._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    screen._update_context()


async def _open_alias_edit_picker(page: AcePage) -> None:
    await wait_for_startup(page)
    await page.press("2")
    await page.expect_state("artifacts_subtab", "patches")
    page.app.push_screen(ModelsPanel())
    await page.expect_modal("ModelsPanel")
    await _wait_for_models_panel_ready(page)
    _highlight_row(page, "xsmall_worker")
    await page.press("e")
    await page.expect_modal("ModelPickerModal")


async def _open_override_picker(page: AcePage) -> None:
    await wait_for_startup(page)
    await page.press("2")
    await page.expect_state("artifacts_subtab", "patches")
    page.app.push_screen(ModelsPanel())
    await page.expect_modal("ModelsPanel")
    await _wait_for_models_panel_ready(page)
    _highlight_row(page, "xsmall_worker")
    await page.press("o")
    await page.expect_modal("ModelPickerModal")


async def test_models_panel_alias_picker_filtered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Models-panel Edit path shows a filtered, highlighted alias row."""
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_edit_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "@medium_worker"
        picker_list = page.app.screen.query_one("#model-picker-list", OptionList)
        await wait_for_state(
            page,
            lambda: (
                picker_list.highlighted is not None
                and picker_list.get_option_at_index(picker_list.highlighted).id
                == "@medium_worker"
            ),
            description="filtered @medium_worker alias highlighted",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_picker_filtered_120x40",
            title="ACE models panel — filtered alias picker",
        )


async def test_models_panel_alias_picker_reordered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider/model rows stay above matching alias rows in the alias picker."""
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_edit_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "fable"
        picker_list = page.app.screen.query_one("#model-picker-list", OptionList)
        await wait_for_state(
            page,
            lambda: (
                "__header_claude__" in {option.id for option in picker_list.options}
                and "@medium_worker" in {option.id for option in picker_list.options}
            ),
            description="claude provider rows and aliases visible",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_picker_reordered_120x40",
            title="ACE models panel — alias-enabled picker reordered",
        )


async def test_models_panel_alias_picker_reordered_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(
        query='"visual"',
        size=(70, 32),
        patches=patches(),
    ) as page:
        await _open_alias_edit_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "fable"
        await wait_for_svg_contains(page, "ALIASES")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_picker_reordered_70x32",
            title="ACE models panel — narrow alias-enabled picker",
        )


async def test_models_panel_builtin_selection_effort_step_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_effort_snapshot",
        lambda self: (effort_snapshot(), True),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_override_picker(page)
        await page.press("enter")
        await page.expect_modal("DefaultEffortLevelModal")
        await wait_for_svg_contains(page, "Reasoning Effort")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_builtin_effort_picker_120x40",
            title="ACE models panel — effort after builtin model",
        )


async def test_models_panel_alias_selection_effort_step_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_effort_snapshot",
        lambda self: (effort_snapshot(), True),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_override_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "@medium_worker"
        picker_list = page.app.screen.query_one("#model-picker-list", OptionList)
        await wait_for_state(
            page,
            lambda: (
                picker_list.highlighted is not None
                and picker_list.get_option_at_index(picker_list.highlighted).id
                == "@medium_worker"
            ),
            description="override picker @medium_worker alias highlighted",
        )
        await page.press("enter")
        await page.expect_modal("DefaultEffortLevelModal")
        await wait_for_svg_contains(page, "Append an effort to @medium_worker")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_effort_picker_120x40",
            title="ACE models panel — effort after alias selection",
        )


async def test_models_panel_worker_override_drilled_in_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, override_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "medium_worker")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_worker_override_drilled_in_120x40",
            title="ACE models panel (worker bucket open with override)",
        )


async def test_models_panel_worker_drilled_in_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, calm_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "medium_worker")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_worker_drilled_in_120x40",
            title="ACE models panel (worker bucket open)",
        )


async def test_models_panel_bucket_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, ownership_views)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: "Research-swarm model roles: lead, second-opinion, extra.",
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "bucket:research")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_bucket_120x40",
            title="ACE models panel (bucket collapsed)",
        )


async def test_models_panel_bucket_drilled_in_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, ownership_views)
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: "Research-swarm model roles: lead, second-opinion, extra.",
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "bucket:research")
        await page.press("l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_bucket_drilled_in_120x40",
            title="ACE models panel (bucket open)",
        )


async def test_models_panel_mixed_builtin_bucket_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, ownership_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await _wait_for_models_panel_ready(page)
        _highlight_row(page, "bucket:worker")
        await page.press("l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_mixed_builtin_bucket_120x40",
            title="ACE models panel (mixed built-in bucket open)",
        )
