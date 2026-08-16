"""ACE TUI PNG snapshots for Launch Control apostrophe entry-jump."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from textual.widgets import OptionList

import sase.ace.tui.modals.models_panel as models_panel
import sase.ace.tui.modals.models_panel_providers as models_panel_providers
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from sase.llm_provider import AliasView
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    ownership_views,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
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
            ready = screen._provider_snapshot_worker is None
            ready = ready and any(
                row_id.startswith("bucket:") or not row_id.startswith("launch:")
                for row_id in screen._row_by_id
                if not row_id.startswith("setting:")
            )
        except Exception:
            return False
        return ready

    await wait_for_state(
        page,
        launch_row_is_ready,
        description="Launch Control rows loaded",
    )


def _highlight_row(page: AcePage, row_id: str) -> None:
    screen = page.app.screen
    assert isinstance(screen, ModelsPanel)
    option_list = screen.query_one("#models-panel-list", OptionList)
    screen._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    screen._update_context()


async def _open_models_panel(page: AcePage) -> ModelsPanel:
    await wait_for_startup(page)
    await page.press("2")
    await page.expect_state("artifacts_subtab", "patches")
    panel = ModelsPanel()
    page.app.push_screen(panel)
    await page.expect_modal("ModelsPanel")
    await _wait_for_models_panel_ready(page)
    return panel


async def test_models_panel_jump_top_level_png_snapshot(
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
        panel = await _open_models_panel(page)
        panel.action_jump_to_entry()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_jump_top_level_120x40",
            title="ACE Launch Control (top-level jump hints)",
        )


async def test_models_panel_jump_mixed_bucket_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_alias_views(monkeypatch, ownership_views)
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        panel = await _open_models_panel(page)
        _highlight_row(page, "bucket:worker")
        await page.press("l")
        await wait_for_visual_idle(page)

        panel.action_jump_to_entry()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_jump_mixed_bucket_120x40",
            title="ACE Launch Control (mixed bucket jump hints)",
        )


async def test_models_panel_jump_narrow_png_snapshot(
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

    async with AcePage(
        query='"visual"',
        size=(70, 32),
        patches=patches(),
    ) as page:
        panel = await _open_models_panel(page)
        panel.action_jump_to_entry()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_jump_top_level_70x32",
            title="ACE Launch Control — narrow top-level jump hints",
        )
