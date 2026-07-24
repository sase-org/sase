"""ACE TUI PNG snapshots for Models-panel navigation and drill-in states."""

from __future__ import annotations

import pytest
from textual.widgets import Input, OptionList

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    calm_views,
    effort_snapshot,
    ownership_views,
    override_views,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _open_alias_edit_picker(page: AcePage) -> None:
    await wait_for_startup(page)
    await page.press("4")
    await page.expect_state("artifacts_subtab", "prs")
    page.app.push_screen(ModelsPanel())
    await page.expect_modal("ModelsPanel")
    # default -> coders bucket -> epic_lander -> big_epic_lander ->
    # phase_worker bucket -> xsmall member, where @coder is a safe persistent
    # reference.
    await page.press("j", "j", "j", "j", "l", "e")
    await page.expect_modal("ModelPickerModal")


async def _open_override_picker(page: AcePage) -> None:
    await wait_for_startup(page)
    await page.press("4")
    await page.expect_state("artifacts_subtab", "prs")
    page.app.push_screen(ModelsPanel())
    await page.expect_modal("ModelsPanel")
    await page.press("o")
    await page.expect_modal("ModelPickerModal")


async def test_models_panel_alias_picker_filtered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Models-panel Edit path shows a filtered, highlighted alias row."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_alias_edit_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "@coder"
        picker_list = page.app.screen.query_one("#model-picker-list", OptionList)
        await wait_for_state(
            page,
            lambda: (
                picker_list.highlighted is not None
                and picker_list.get_option_at_index(picker_list.highlighted).id
                == "@coder"
            ),
            description="filtered @coder alias highlighted",
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
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_alias_edit_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "gpt-5.6-sol"
        picker_list = page.app.screen.query_one("#model-picker-list", OptionList)
        await wait_for_state(
            page,
            lambda: (
                "__header_codex__" in {option.id for option in picker_list.options}
                and "@medium_phase_worker"
                in {option.id for option in picker_list.options}
            ),
            description="codex provider rows and aliases visible",
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
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(
        query='"visual"',
        size=(70, 32),
        changespecs=changespecs(),
    ) as page:
        await _open_alias_edit_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "gpt-5.6-sol"
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
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_effort_snapshot",
        lambda self: (effort_snapshot(), True),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
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
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_effort_snapshot",
        lambda self: (effort_snapshot(), True),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_override_picker(page)
        picker_input = page.app.screen.query_one("#model-picker-filter", Input)
        picker_input.value = "@coder"
        picker_list = page.app.screen.query_one("#model-picker-list", OptionList)
        await wait_for_state(
            page,
            lambda: (
                picker_list.highlighted is not None
                and picker_list.get_option_at_index(picker_list.highlighted).id
                == "@coder"
            ),
            description="override picker @coder alias highlighted",
        )
        await page.press("enter")
        await page.expect_modal("DefaultEffortLevelModal")
        await wait_for_svg_contains(page, "Append an effort to @coder")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_effort_picker_120x40",
            title="ACE models panel — effort after alias selection",
        )


async def test_models_panel_coders_drilled_in_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: override_views()
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_coders_drilled_in_120x40",
            title="ACE models panel (coders bucket open)",
        )


async def test_models_panel_phase_worker_drilled_in_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_phase_worker_drilled_in_120x40",
            title="ACE models panel (phase_worker bucket open)",
        )


async def test_models_panel_bucket_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: ownership_views()
    )
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: "Research-swarm model roles: lead, second-opinion, extra.",
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j")
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
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: ownership_views()
    )
    monkeypatch.setattr(
        "sase.llm_provider.alias_view.model_alias_bucket_description",
        lambda name: "Research-swarm model roles: lead, second-opinion, extra.",
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "l")
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
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: ownership_views()
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "l")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_mixed_builtin_bucket_120x40",
            title="ACE models panel (mixed built-in bucket open)",
        )
