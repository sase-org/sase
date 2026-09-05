"""ACE TUI PNG visual snapshots for the Projects-tab InitPlanModal."""

from __future__ import annotations

import pytest
from textual.widgets import Button

from sase.ace.testing import AcePage
from sase.ace.tui.modals.init_plan_modal import InitPlanModal
from sase.ace.tui.modals.projects_pane_init import InitScope
from sase.ace.tui.modals.projects_pane_init_payload import InitCheckPayload
from sase.current_project import CurrentProject
from tests.ace.tui.modals.projects_pane_init_test_helpers import (
    danger_payload,
    mixed_all_payload,
    single_update_payload,
    tty_blocked_payload,
)
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_projects_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_project_records,
    _patch_xprompt_sources,
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


def _patch_admin_center(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current_project: CurrentProject | None = None,
) -> None:
    """Stub every Admin Center pane so the modal background is deterministic."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_project_records(monkeypatch, current_project=current_project)


async def _show_init_plan(
    page: AcePage,
    scope: InitScope,
    payload: InitCheckPayload,
) -> InitPlanModal:
    _, pane = await _open_projects_modal(page)
    await page.wait_for(lambda _s: pane._selected_project_name() == "sase")
    modal = InitPlanModal(scope, payload)
    page.app.push_screen(modal)
    await page.expect_modal("InitPlanModal")
    await page.wait_for(lambda _s: len(modal.query("#init-plan-container")) > 0)
    await wait_for_visual_idle(page)
    return modal


async def test_config_center_projects_init_plan_single_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-project update preview: argv, planner rows, memory warning."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _show_init_plan(
            page,
            InitScope.for_projects(("sase",), ("sase",)),
            single_update_payload(),
        )
        await wait_for_svg_contains(page, "Initialize sase")
        await wait_for_svg_contains(page, "sase init -p sase --yes")

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_init_plan_single_120x40",
            title="ACE SASE Admin Center — Initialize sase (single-project update)",
        )


async def test_config_center_projects_init_plan_all_mixed_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-projects preview with mixed drift, current, and unavailable rows."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _show_init_plan(page, InitScope.everything(), mixed_all_payload())
        await wait_for_svg_contains(page, "4 enabled")
        await wait_for_svg_contains(page, "sase init --all --yes")

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_init_plan_all_mixed_120x40",
            title="ACE SASE Admin Center — Initialize all projects (mixed status)",
        )


async def test_config_center_projects_init_plan_danger_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overwrite action uses the danger confirm variant."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        modal = await _show_init_plan(
            page,
            InitScope.for_projects(("sase",), ("sase",)),
            danger_payload(),
        )
        await page.wait_for(
            lambda _s: modal.query_one("#init-plan-container").has_class(
                "confirm-dialog--danger"
            )
        )
        await wait_for_svg_contains(page, "AGENTS.md")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_init_plan_danger_120x40",
            title="ACE SASE Admin Center — Initialize sase (danger overwrite)",
        )


async def test_config_center_projects_init_plan_tty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TTY-blocked plan shows the Run in terminal valve and a disabled confirm."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        modal = await _show_init_plan(
            page,
            InitScope.for_projects(("sase",), ("sase",)),
            tty_blocked_payload(),
        )
        await page.wait_for(lambda _s: len(modal.query("#init-plan-terminal")) > 0)
        terminal = modal.query_one("#init-plan-terminal", Button)
        assert "Run in terminal" in str(terminal.label)
        await wait_for_svg_contains(page, "needs a terminal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_init_plan_tty_120x40",
            title="ACE SASE Admin Center — Initialize sase (TTY-blocked valve)",
        )


async def test_config_center_projects_init_plan_diffs_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``d`` expands the payload's unified diffs in the preview."""
    _patch_admin_center(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        modal = await _show_init_plan(
            page,
            InitScope.for_projects(("sase",), ("sase",)),
            single_update_payload(),
        )
        await page.press("d")
        await page.wait_for(
            lambda _s: (
                "d hide diffs"
                in (modal.query_one("#init-plan-container").border_subtitle or "")
            )
        )
        await wait_for_svg_contains(page, "bug")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_init_plan_diffs_120x40",
            title="ACE SASE Admin Center — Initialize sase (full-diff expansion)",
        )


async def test_config_center_projects_init_plan_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-project preview wraps on a narrow terminal."""
    _patch_admin_center(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=(80, 24),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await _show_init_plan(
            page,
            InitScope.for_projects(("sase",), ("sase",)),
            single_update_payload(),
        )
        await wait_for_svg_contains(page, "Initialize sase")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_projects_init_plan_narrow_80x24",
            title="ACE SASE Admin Center — Initialize sase (narrow terminal)",
        )
