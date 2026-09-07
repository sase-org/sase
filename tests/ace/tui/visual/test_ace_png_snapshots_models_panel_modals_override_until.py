"""ACE TUI PNG snapshots for the Launch Control override-until modal."""

from __future__ import annotations

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_time import OverrideUntilModal
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    EASTERN,
    time_modal_clock,
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


@pytest.mark.parametrize(
    ("value", "snapshot_name", "title"),
    [
        ("", "models_panel_until_neutral_120x40", "ACE override until (neutral)"),
        ("5pm", "models_panel_until_valid_120x40", "ACE override until (valid)"),
        (
            "today 1pm",
            "models_panel_until_error_120x40",
            "ACE override until (error)",
        ),
    ],
)
async def test_models_panel_override_until_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        modal = OverrideUntilModal(timezone=EASTERN, clock=time_modal_clock)
        page.app.push_screen(modal)
        await page.expect_modal("OverrideUntilModal")
        await wait_for_svg_contains(page, "Override Until")
        field = modal.query_one("#override-until-input", Input)
        if value:
            field.value = value
        expected_class = {
            "": "until-neutral",
            "5pm": "until-valid",
            "today 1pm": "until-error",
        }[value]
        preview = modal.query_one("#override-until-preview", Static)
        await wait_for_state(
            page,
            lambda: (
                field.has_focus
                and field.value == value
                and preview.has_class(expected_class)
            ),
            description=f"override-until {expected_class} preview",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
