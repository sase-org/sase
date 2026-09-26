"""sase's TUI PNG snapshots for the Services source-grouped sidebar."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.axe_display._panel_titles import routine_health_count
from sase.ace.tui.actions.axe_display._panels import SERVICES_PANEL_ORDER
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui.visual._ace_axe_png_snapshot_tree_fixtures import (
    services_panels_all_sources_data,
    services_panels_builtin_only_data,
    services_panels_data,
    services_panels_empty_routines_data,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _assert_source_panels(
    page: AcePage,
    *,
    expected_visible: list[str],
    routine: str = "checks",
    routine_collapsed: bool = True,
) -> None:
    """Assert panel order, builtin fold, and health badge for Services."""
    assert list(SERVICES_PANEL_ORDER) == [
        "service_procs",
        "user_routines",
        "plugin_routines",
        "builtin_routines",
    ]
    index = page.app._axe_panel_index
    assert index.visible_keys() == expected_visible
    if routine_collapsed:
        assert (
            page.app._axe_fold_manager.get(f"lumberjack:{routine}")
            == FoldLevel.COLLAPSED
        )
    assert (
        routine_health_count(
            routine,
            page.app._axe_lumberjack_chop_names,
            page.app._axe_chop_snapshots,
        )
        == 1
    )


def _assert_panel_titles(page: AcePage, *labels: str) -> None:
    """Assert the source-panel border titles render from cached state."""
    titles = page.app._build_axe_panel_titles(
        page.app._axe_panel_index.panel_for_global(page.app.current_idx)
    )
    plain = {key: title.plain for key, title in titles.items()}
    for label in labels:
        assert any(label in text for text in plain.values()), plain


async def test_services_panels_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Builtin+User source panels with selection on the Scheduler row."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        assert page.app.current_idx == 0
        _assert_source_panels(
            page,
            expected_visible=["service_procs", "user_routines", "builtin_routines"],
        )
        _assert_panel_titles(page, "User Routines", "Builtin Routines")
        await wait_for_svg_contains(page, "Builtin Routines")

        ace_png_visual.assert_page_png(
            page,
            "services_panels_120x40",
            title="ACE services panels",
        )


async def test_services_panels_all_sources_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User+Plugin+Builtin panels with the plugin routine expanded."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_all_sources_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        _assert_source_panels(
            page,
            expected_visible=[
                "service_procs",
                "user_routines",
                "plugin_routines",
                "builtin_routines",
            ],
        )
        _assert_panel_titles(
            page, "User Routines", "Plugin Routines", "Builtin Routines"
        )
        await wait_for_svg_contains(page, "Plugin Routines")

        ace_png_visual.assert_page_png(
            page,
            "services_panels_all_sources_120x40",
            title="ACE services panels all sources",
        )


async def test_services_panels_builtin_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Builtin-only routines panel with the folded failure badge."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_builtin_only_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        _assert_source_panels(
            page, expected_visible=["service_procs", "builtin_routines"]
        )
        _assert_panel_titles(page, "Builtin Routines")
        await wait_for_svg_contains(page, "Builtin Routines")

        ace_png_visual.assert_page_png(
            page,
            "services_panels_builtin_only_120x40",
            title="ACE services panels builtin only",
        )


async def test_services_panels_medium_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Builtin+User source panels legible at the 100x30 medium layout."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches(), size=(100, 30)) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        _assert_source_panels(
            page,
            expected_visible=["service_procs", "user_routines", "builtin_routines"],
        )
        _assert_panel_titles(page, "User Routines", "Builtin Routines")

        ace_png_visual.assert_page_png(
            page,
            "services_panels_100x30",
            title="ACE services panels medium",
        )


async def test_services_panels_routine_selected_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected job moves the gold focus border to User Routines."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        for _ in range(7):
            await page.press("j")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        assert page.app.current_idx == 7
        assert page.app._axe_panel_index.panel_for_global(7) == "user_routines"
        _assert_source_panels(
            page,
            expected_visible=["service_procs", "user_routines", "builtin_routines"],
        )

        ace_png_visual.assert_page_png(
            page,
            "services_panels_routine_selected_120x40",
            title="ACE services panels routine selected",
        )


async def test_services_panels_after_j_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`J` jumps to the first routine row; `K` returns to Service Procs."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await page.press("J")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        first_routine = page.app._axe_panel_index.first_global("user_routines")
        assert first_routine is not None
        assert page.app.current_idx == first_routine
        assert (
            page.app._axe_panel_index.panel_for_global(page.app.current_idx)
            == "user_routines"
        )

        ace_png_visual.assert_page_png(
            page,
            "services_panels_after_J_120x40",
            title="ACE services panels after J",
        )

        await page.press("K")
        page.app._refresh_axe_display()
        await wait_for_visual_idle(page)

        assert (
            page.app._axe_panel_index.panel_for_global(page.app.current_idx)
            == "service_procs"
        )


async def test_services_panels_empty_routines_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty routines placeholder plus the stopped-scheduler badge."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_empty_routines_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        index = page.app._axe_panel_index
        assert index.visible_keys() == ["service_procs", "user_routines"]
        assert index.first_visible_routine_panel() == "user_routines"

        ace_png_visual.assert_page_png(
            page,
            "services_panels_empty_routines_120x40",
            title="ACE services panels empty routines",
        )


async def test_services_panels_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sidebar width cap and title truncation on a narrow terminal."""
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches(), size=(70, 36)) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        index = page.app._axe_panel_index
        assert index.visible_keys() == [
            "service_procs",
            "user_routines",
            "builtin_routines",
        ]

        ace_png_visual.assert_page_png(
            page,
            "services_panels_narrow_70x36",
            title="ACE services panels narrow",
        )


async def test_services_navigation_key_to_paint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Representative Services j/J/k/K navigation records paint samples."""
    perf_path = tmp_path / "tui_jk.jsonl"
    monkeypatch.setenv("SASE_TUI_PERF", "1")
    monkeypatch.setenv("SASE_TUI_PERF_PATH", str(perf_path))
    patch_startup_loaders(monkeypatch, axe_data=services_panels_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")
        await wait_for_visual_idle(page)

        assert page.app._jk_perf is not None
        for key in ("J", "K", "J", "K"):
            await page.press(key)
            page.app._refresh_axe_display()
            await wait_for_visual_idle(page)

        samples = page.app._jk_perf.samples()
        assert len(samples) >= 4
        for sample in samples:
            assert sample["tab"] == "services"
            assert sample["paint_ms"] >= 0
            assert sample["paint_ms"] < 10_000
