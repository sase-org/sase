"""ACE TUI PNG snapshots for Launch Control alias-history panel states."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

import sase.ace.tui.modals.alias_history_modal as alias_history_modal
from sase.ace.testing import AcePage
from sase.ace.tui.modals.alias_history_modal import AliasHistoryModal
from sase.ace.tui.modals.alias_history_state import AliasHistoryEntryRequest
from sase.llm_provider.alias_history import AliasHistoryView
from tests.ace.tui.visual._ace_models_panel_alias_history_png_snapshot_fixtures import (
    FROZEN_ALIAS_HISTORY_NOW,
    custom_alias_entry,
    empty_alias_entry,
    empty_alias_history_view,
    grouped_alias_history_view,
    grouped_bucket_entry,
    legacy_only_alias_history_view,
    populated_alias_history_view,
    single_alias_entry,
    truncated_alias_history_view,
    usage_pool_entry,
    usage_pool_history_view,
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


def _patch_history_modal(
    monkeypatch: pytest.MonkeyPatch, view: AliasHistoryView
) -> None:
    def load_alias_history(
        aliases: str | tuple[str, ...],
        *,
        limit_per_alias: int | None = None,
        include_hidden: bool = False,
        freshness: str = "cached",
        **_kwargs: object,
    ) -> AliasHistoryView:
        del limit_per_alias, include_hidden, freshness
        assert tuple(aliases) == view.aliases
        return view

    monkeypatch.setattr(alias_history_modal, "load_alias_history", load_alias_history)
    monkeypatch.setattr(
        alias_history_modal,
        "get_model_alias_history_limit",
        lambda: view.limit_per_alias,
    )
    monkeypatch.setattr(alias_history_modal, "_now", lambda: FROZEN_ALIAS_HISTORY_NOW)
    monkeypatch.setattr("sase.core.time._cached_timezone", ZoneInfo("UTC"))


async def _open_alias_history(
    page: AcePage,
    *,
    entry: AliasHistoryEntryRequest,
    view: AliasHistoryView,
) -> AliasHistoryModal:
    await wait_for_startup(page)
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    page.app.push_screen(AliasHistoryModal(entry))
    await page.expect_modal("AliasHistoryModal")
    await wait_for_state(
        page,
        lambda: (
            isinstance(page.app.screen, AliasHistoryModal)
            and page.app.screen._view is view
        ),
        description="alias history loaded",
    )
    return page.app.screen


async def test_models_panel_alias_history_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    view = populated_alias_history_view()
    _patch_history_modal(monkeypatch, view)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_history(page, entry=single_alias_entry(), view=view)
        await wait_for_svg_contains(page, "direct")
        await wait_for_svg_contains(page, "via @coder")
        await wait_for_svg_contains(page, "default")
        await wait_for_svg_contains(page, "unrecorded")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_history_populated_120x40",
            title="ACE Launch Control - alias history populated",
        )


async def test_models_panel_alias_history_grouped_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    view = grouped_alias_history_view()
    _patch_history_modal(monkeypatch, view)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_history(page, entry=grouped_bucket_entry(), view=view)
        await wait_for_svg_contains(page, "@research_a")
        await wait_for_svg_contains(page, "@research_b")
        await wait_for_svg_contains(page, "No recorded runs for @research_c.")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_history_grouped_120x40",
            title="ACE Launch Control - grouped alias history",
        )


async def test_models_panel_alias_history_truncated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    view = truncated_alias_history_view()
    _patch_history_modal(monkeypatch, view)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_history(page, entry=single_alias_entry(), view=view)
        await wait_for_svg_contains(page, "7 recorded")
        await wait_for_svg_contains(page, "2 shown")
        await wait_for_svg_contains(page, "more available")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_history_truncated_120x40",
            title="ACE Launch Control - truncated alias history",
        )


async def test_models_panel_alias_history_legacy_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    view = legacy_only_alias_history_view()
    _patch_history_modal(monkeypatch, view)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_history(page, entry=custom_alias_entry(), view=view)
        await wait_for_svg_contains(page, "no alias origin was captured for this run")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_history_legacy_only_120x40",
            title="ACE Launch Control - legacy alias history",
        )


async def test_models_panel_alias_history_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    view = empty_alias_history_view()
    _patch_history_modal(monkeypatch, view)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_history(page, entry=empty_alias_entry(), view=view)
        await wait_for_svg_contains(page, "No recorded runs for @fresh_alias.")
        await wait_for_svg_contains(
            page, "Provenance-aware alias history is only recorded"
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_history_empty_120x40",
            title="ACE Launch Control - empty alias history",
        )


async def test_models_panel_alias_history_usage_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    view = usage_pool_history_view()
    _patch_history_modal(monkeypatch, view)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_alias_history(page, entry=usage_pool_entry(), view=view)
        await wait_for_svg_contains(page, "Model usage")
        await wait_for_svg_contains(page, "unused")
        await wait_for_svg_contains(page, "members used")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_alias_history_usage_120x40",
            title="ACE Launch Control - alias history model usage",
        )
