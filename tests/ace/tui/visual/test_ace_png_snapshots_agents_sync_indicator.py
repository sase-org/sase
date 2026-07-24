"""ACE PNG snapshot for the pending agents-repository sync badge."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentsSyncIndicator
from sase.agents_sync.models import (
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncStatusSnapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_agents_sync_indicator_pending_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await wait_for_svg_contains(page, "visual_auth")
        indicator = page.app.query_one(
            "#agents-sync-indicator",
            AgentsSyncIndicator,
        )
        indicator.set_status(
            SyncStatusSnapshot(
                100.0,
                (
                    ProjectSyncStatus(
                        "alpha",
                        "Alpha",
                        "ready",
                        pending_updates=(
                            CapturedIncomingHood(
                                "alpha",
                                "Alpha",
                                "refs/remotes/origin/main",
                                "a" * 40,
                                "alpha-foo",
                                2,
                                "exact",
                                "alice",
                                "zeus",
                                "foo",
                                "b" * 64,
                                2,
                                1,
                                1.0,
                            ),
                        ),
                    ),
                    ProjectSyncStatus(
                        "beta",
                        "Beta",
                        "ready",
                        pending_updates=(
                            CapturedIncomingHood(
                                "beta",
                                "Beta",
                                "refs/remotes/origin/main",
                                "c" * 40,
                                "beta-bar",
                                2,
                                "exact",
                                "bob",
                                "hera",
                                "bar",
                                "d" * 64,
                                1,
                                0,
                                1.0,
                            ),
                        ),
                    ),
                ),
            )
        )
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ⇅ 2 ",
            description="agents-sync indicator",
        )
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "agents_sync_indicator_pending_120x40",
            title="ACE agents-repository sync indicator",
        )
