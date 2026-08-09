"""ACE TUI PNG snapshots for primary Models-panel states."""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.testing import AcePage
from sase.ace.tui.modals import ModelsPanel
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    builtin_only_views,
    calm_views,
    custom_builtin_warning_views,
    effort_snapshot,
    override_views,
    pool_effort_views,
    runner_limit_snapshot,
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


async def test_models_panel_empty_custom_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: builtin_only_views()
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_empty_custom_120x40",
            title="ACE models panel (empty Custom section)",
        )


async def test_models_panel_default_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_default_120x40",
            title="ACE models panel (no overrides)",
        )


async def test_models_panel_default_effort_override_png_snapshot(
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_svg_contains(page, "override · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_override_120x40",
            title="ACE models panel — active default-effort override",
        )


async def test_models_panel_runner_limit_override_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_runner_limit_snapshot",
        lambda self: (runner_limit_snapshot(), True),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_svg_contains(page, "override · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_runner_limit_override_120x40",
            title="ACE models panel — active runner-limit override",
        )


async def test_models_panel_smartest_max_effort_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel, "build_alias_views", lambda *a, **k: calm_views())
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_smartest_max_effort_120x40",
            title="ACE models panel (maximum-effort smartest target)",
        )


async def test_models_panel_pool_effort_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Show the default, pool availability/next member, and row effort."""
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: pool_effort_views()
    )
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_pool_effort_120x40",
            title="ACE models panel (pool and effort)",
        )


async def test_models_panel_effort_provenance_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: pool_effort_views()
    )
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_provenance_120x40",
            title="ACE models panel (effort provenance)",
        )


async def test_models_panel_pool_suspended_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel,
        "build_alias_views",
        lambda *a, **k: pool_effort_views(suspended=True),
    )
    monkeypatch.setattr(models_panel, "default_reasoning_effort", lambda: "xhigh")
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j", "j", "j", "j", "j", "j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_pool_suspended_120x40",
            title="ACE models panel (pool suspended by override)",
        )


async def test_models_panel_overrides_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel, "build_alias_views", lambda *a, **k: override_views()
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")

        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_overrides_120x40",
            title="ACE models panel (overrides active)",
        )


async def test_models_panel_custom_builtin_warning_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        models_panel,
        "build_alias_views",
        lambda *a, **k: custom_builtin_warning_views(),
    )
    monkeypatch.setattr(models_panel, "_now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(ModelsPanel())
        await page.expect_modal("ModelsPanel")
        await page.press("j")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_custom_builtin_warning_120x40",
            title="ACE models panel (misplaced builtin warning)",
        )
