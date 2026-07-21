"""ACE TUI PNG snapshots for Models-panel navigation and drill-in states."""

from __future__ import annotations

import pytest
from textual.widgets import Input, OptionList

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    bucket_views,
    calm_views,
    override_views,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_models_panel_alias_picker_filtered_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Models-panel Edit path shows a filtered, highlighted alias row."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        # default -> coders bucket -> epic_lander -> big_epic_lander ->
        # phase_worker bucket -> small member, where @coder is a safe
        # persistent reference.
        await page.press("j", "j", "j", "j", "l", "e")
        await page.expect_modal("ModelPickerModal")
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
        models_panel, "build_alias_views", lambda *a, **k: bucket_views()
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
        models_panel, "build_alias_views", lambda *a, **k: bucket_views()
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
