"""PNG coverage for the SASE Admin Center landing page."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.mark.parametrize(
    ("size", "resume_tab", "snapshot_name"),
    [
        ((120, 40), None, "config_center_home_120x40"),
        ((100, 24), None, "config_center_home_100x24"),
        ((120, 40), "procs", "config_center_home_resume_procs_120x40"),
        ((100, 24), "procs", "config_center_home_resume_procs_100x24"),
    ],
)
async def test_config_center_home_png_snapshot(
    size: tuple[int, int],
    resume_tab: CenterTab | None,
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        patches=patches(),
        size=size,
    ) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.press("3")
        await page.expect_state("artifacts_subtab", "patches")
        page.app._last_admin_center_tab = resume_tab
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        await page.wait_for(lambda _state: bool(modal.query("#admin-center-home-card")))
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            snapshot_name,
            title=f"ACE SASE Admin Center — home ({size[0]}x{size[1]})",
        )
