"""ACE TUI PNG snapshots for effort and runner-limit picker card modals."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortActionModal,
    DefaultEffortLevelModal,
)
from sase.ace.tui.modals.models_panel_runner_limit_cards import (
    RunnerLimitActionModal,
    RunnerLimitValueModal,
)
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    effort_snapshot,
    runner_limit_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_models_panel_default_effort_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            DefaultEffortActionModal(
                effort_snapshot(), now=FROZEN_NOW, use_chezmoi=True
            )
        )
        await page.expect_modal("DefaultEffortActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_action_120x40",
            title="ACE Launch Control — default-effort action chooser",
        )


@pytest.mark.parametrize(
    ("mode", "snapshot_name", "title"),
    [
        (
            "edit",
            "models_panel_effort_level_edit_120x40",
            "ACE Launch Control — persistent effort-level picker",
        ),
        (
            "override",
            "models_panel_effort_level_override_120x40",
            "ACE Launch Control — temporary effort-level picker",
        ),
    ],
)
async def test_models_panel_default_effort_level_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            DefaultEffortLevelModal(  # type: ignore[arg-type]
                mode, effort_snapshot(), now=FROZEN_NOW
            )
        )
        await page.expect_modal("DefaultEffortLevelModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_models_panel_runner_limit_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            RunnerLimitActionModal(
                runner_limit_snapshot(), now=FROZEN_NOW, use_chezmoi=True
            )
        )
        await page.expect_modal("RunnerLimitActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_runner_limit_action_120x40",
            title="ACE Launch Control — runner-limit action chooser",
        )


@pytest.mark.parametrize(
    ("mode", "snapshot_name", "title", "initial"),
    [
        (
            "edit",
            "models_panel_runner_limit_value_edit_120x40",
            "ACE Launch Control — persistent runner-limit editor",
            10,
        ),
        (
            "override",
            "models_panel_runner_limit_value_override_120x40",
            "ACE Launch Control — temporary runner-limit editor",
            4,
        ),
    ],
)
async def test_models_panel_runner_limit_value_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    snapshot_name: str,
    title: str,
    initial: int,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            RunnerLimitValueModal(mode, initial=initial)  # type: ignore[arg-type]
        )
        await page.expect_modal("RunnerLimitValueModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
