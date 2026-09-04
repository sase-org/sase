"""Coverage for the Patches pane's ``ArtifactEntryNavigator`` adapter."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.testing.fixtures import DEFAULT_PATCHES
from sase.ace.tui.widgets.artifacts.entry_navigation import (
    ArtifactEntryNavigator,
    ArtifactEntryTarget,
    LinkRequestState,
)
from sase.ace.tui.widgets.artifacts.panes import ArtifactsPatchesPane
from sase.ace.tui.widgets.artifacts.patch_entry import patch_row_target
from sase.ace.tui.widgets.artifacts.view import ArtifactsView
from sase.ace.tui.widgets.patch_list import PatchList


def test_patches_pane_implements_the_shared_navigator_abc() -> None:
    assert isinstance(ArtifactsPatchesPane(), ArtifactEntryNavigator)


@pytest.mark.asyncio
async def test_entry_targets_reflect_visible_patches_in_visual_order() -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        assert pane.entry_targets() == tuple(
            patch_row_target(patch) for patch in DEFAULT_PATCHES
        )


@pytest.mark.asyncio
async def test_selected_entry_target_tracks_current_idx() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("patches"))
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        assert pane.selected_entry_target() == patch_row_target(DEFAULT_PATCHES[0])

        await page.press("j")
        await page.expect_state("idx", 1)
        assert pane.selected_entry_target() == patch_row_target(DEFAULT_PATCHES[1])


@pytest.mark.asyncio
async def test_select_entry_target_focuses_the_list_and_clears_banner_focus() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("patches"))
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        page.app._current_patch_group_key = ("some", "banner")  # type: ignore[attr-defined]

        target = patch_row_target(DEFAULT_PATCHES[2])
        assert pane.select_entry_target(target) is True

        assert page.app.current_idx == 2  # type: ignore[attr-defined]
        assert page.app._current_patch_group_key is None  # type: ignore[attr-defined]
        assert pane.query_one("#list-panel", PatchList).has_focus


@pytest.mark.asyncio
async def test_select_entry_target_returns_false_for_unknown_target() -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        unknown = ArtifactEntryTarget(pane_id="patches", parts=("nope", "missing"))
        assert pane.select_entry_target(unknown) is False


@pytest.mark.asyncio
async def test_request_entry_target_selects_immediately_since_patches_preload() -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        target = patch_row_target(DEFAULT_PATCHES[1])
        assert pane.request_entry_target(target) is LinkRequestState.SELECTED
        assert page.app.current_idx == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_request_entry_target_reports_missing_for_unknown_target() -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        unknown = ArtifactEntryTarget(pane_id="patches", parts=("nope", "missing"))
        assert pane.request_entry_target(unknown) is LinkRequestState.MISSING


@pytest.mark.asyncio
async def test_host_limit_query_adapter_reads_and_rewrites_the_app_query() -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        original = page.app._display_patch_query()  # type: ignore[attr-defined]
        assert pane.host_limit_query() == original

        pane.apply_host_limit_query("limit:all", grow=True)

        assert page.app._display_patch_query() == "limit:all"  # type: ignore[attr-defined]
        assert pane.host_limit_query() == "limit:all"


@pytest.mark.asyncio
async def test_conditional_footer_entries_and_jump_hint_methods_are_inert() -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        assert pane.conditional_footer_entries() == ()
        # Patches paint their own adaptive jump hints; these must not raise.
        pane.apply_entry_jump_hints({})
        pane.clear_entry_jump_hints()


@pytest.mark.asyncio
async def test_artifacts_view_returns_patches_navigator_without_raising() -> None:
    async with AcePage(initial_tab="patches") as page:
        view = page.query_one_widget("#artifacts-view", ArtifactsView)
        navigator = view.entry_navigator("patches")
        assert isinstance(navigator, ArtifactEntryNavigator)
        assert navigator.entry_targets() == tuple(
            patch_row_target(patch) for patch in DEFAULT_PATCHES
        )


@pytest.mark.asyncio
async def test_toggle_mark_stores_a_stable_target_and_survives_grouping_reorder() -> (
    None
):
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("patches"))
        pane = page.query_one_widget("#artifacts-patches-pane", ArtifactsPatchesPane)
        target = patch_row_target(DEFAULT_PATCHES[0])

        await page.press("m")

        assert page.app._artifacts_marked_targets["patches"] == {target}  # type: ignore[attr-defined]
        assert page.app.marked_indices == {0}  # type: ignore[attr-defined]

        # Re-sort the visible rows (BY_DATE instead of BY_PROJECT); the mark
        # must keep tracking the same Patch by identity, not by index.
        page.app._patch_grouping_mode = page.app._patch_grouping_mode.__class__.BY_DATE  # type: ignore[attr-defined]
        page.app._refresh_display()  # type: ignore[attr-defined]

        assert target in pane.entry_targets()
        assert page.app._artifacts_marked_targets["patches"] == {target}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_clear_marks_empties_the_patches_mark_set() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("patches"))
        await page.press("m")
        assert page.app.marked_indices == {0}  # type: ignore[attr-defined]

        await page.press("u")

        assert page.app._artifacts_marked_targets["patches"] == set()  # type: ignore[attr-defined]
        assert page.app.marked_indices == set()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_marks_survive_an_ordinary_reload() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("patches"))
        target = patch_row_target(DEFAULT_PATCHES[0])

        await page.press("m")
        assert page.app._artifacts_marked_targets["patches"] == {target}  # type: ignore[attr-defined]

        page.app._reload_and_reposition()  # type: ignore[attr-defined]

        assert page.app._artifacts_marked_targets["patches"] == {target}  # type: ignore[attr-defined]
        assert page.app.marked_indices == {0}  # type: ignore[attr-defined]
