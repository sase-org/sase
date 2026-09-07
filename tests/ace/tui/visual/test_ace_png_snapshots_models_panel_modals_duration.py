"""ACE TUI PNG snapshots for Launch Control duration picker modals."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_duration import (
    DurationPickerModal,
    KeepCurrentWindow,
)
import sase.ace.tui.modals.models_panel_duration as models_panel_duration
from sase.ace.tui.modals.models_panel_provider_rendering import (
    provider_duration_modal,
    provider_priority_duration_modal,
)
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    provider_priority,
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


async def test_models_panel_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(DurationPickerModal())
        await page.expect_modal("DurationPickerModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_duration_picker_120x40",
            title="ACE model override duration picker",
        )


async def test_models_panel_provider_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(provider_duration_modal("claude"))
        await page.expect_modal("DurationPickerModal")
        await wait_for_svg_contains(page, "Disable CLAUDE")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_duration_picker_120x40",
            title="ACE provider-disable duration picker",
        )


async def test_models_panel_provider_duration_picker_keep_window_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_duration, "now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            provider_duration_modal(
                "claude",
                keep_current=KeepCurrentWindow(expires_at=FROZEN_NOW + 6_120.0),
            )
        )
        await page.expect_modal("DurationPickerModal")
        await wait_for_svg_contains(page, "Keep current window")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_duration_picker_keep_window_120x40",
            title="ACE provider-disable duration picker keep-current window",
        )


async def test_models_panel_provider_priority_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_duration, "now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            provider_priority_duration_modal(
                "claude",
                current_priority=provider_priority("codex"),
                now=FROZEN_NOW,
            )
        )
        await page.expect_modal("DurationPickerModal")
        await wait_for_svg_contains(page, "Prioritize CLAUDE")
        await wait_for_svg_contains(page, "Replaces CODEX priority")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_priority_duration_picker_120x40",
            title="ACE provider-priority duration picker",
        )
