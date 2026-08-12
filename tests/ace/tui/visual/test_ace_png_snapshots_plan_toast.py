"""ACE TUI PNG visual snapshots for tier-aware plan/epic approval toasts."""

from __future__ import annotations

import pytest
from textual.widgets._toast import Toast

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._toasts import _format_notification_toast

from tests._notification_toasts_helpers import _make
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _toast_is_mounted(page: AcePage) -> bool:
    return bool(list(page.app.screen.query(Toast)))


async def test_epic_plan_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The epic toast shows the Epic tier word and phase/wave/size counts."""
    patch_startup_loaders(monkeypatch)
    notification = _make(
        action="EpicApproval",
        action_data={
            "agent_name": "y4",
            "original_plan_file": "/plans/agent_group_clan_collapse.md",
            "plan_tier": "epic",
            "plan_phase_count": "7",
            "plan_wave_count": "3",
            "plan_phase_sizes": "xsmall=1,small=2,medium=3,large=1",
        },
    )
    message, severity = _format_notification_toast(notification)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        notifications=True,
        startup_policy="real",
    ) as page:
        page.app.notify(message, severity=severity)
        await page.wait_for(lambda _s: _toast_is_mounted(page))
        page.app.screen.set_focus(None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "plan_toast_epic_120x40",
            title="ACE epic plan approval toast",
        )


async def test_tale_plan_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tale toast shows the Tale tier word and no detail line."""
    patch_startup_loaders(monkeypatch)
    notification = _make(
        action="PlanApproval",
        action_data={
            "agent_name": "y4",
            "original_plan_file": "/plans/bead_wait_store_diagnostics.md",
            "plan_tier": "tale",
        },
    )
    message, severity = _format_notification_toast(notification)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        notifications=True,
        startup_policy="real",
    ) as page:
        page.app.notify(message, severity=severity)
        await page.wait_for(lambda _s: _toast_is_mounted(page))
        page.app.screen.set_focus(None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "plan_toast_tale_120x40",
            title="ACE tale plan approval toast",
        )
