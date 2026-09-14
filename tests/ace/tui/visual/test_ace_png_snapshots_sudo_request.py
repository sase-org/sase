"""PNG snapshots for the ACE sudo request modal."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import (
    SudoCommandReviewData,
    SudoRequestModal,
    SudoRequestModalData,
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


def _data() -> SudoRequestModalData:
    return SudoRequestModalData(
        request_id="sudo-visual-42",
        title="Refresh package cache",
        sender="sudo",
        reason="Refresh a root-owned package cache before continuing setup.",
        commands=(
            SudoCommandReviewData(
                id="refresh",
                argv=("/usr/bin/apt-get", "update"),
                executable_sha256="sha256-refresh",
            ),
            SudoCommandReviewData(
                id="verify",
                argv=("/usr/bin/test", "-d", "/var/lib/apt/lists"),
                executable_sha256="sha256-verify",
            ),
        ),
        run_as="root",
        cwd="/home/visual/project",
        env=(("DEBIAN_FRONTEND", "noninteractive"),),
        timeout_seconds=60,
        stop_policy="terminate",
        output_policy="bounded",
        machine="athena",
        manifest_sha256="sha256-manifest",
        risk_badges=("root", "network", "writes"),
        requester="setup-agent",
        project="sase",
        expires_at="2026-09-14T12:10:00+00:00",
        created_at="2026-09-14T12:00:00+00:00",
    )


async def _snapshot_modal(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot_name: str,
    title: str,
    show_details: bool = False,
    size: tuple[int, int] = (120, 40),
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=size,
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        modal = SudoRequestModal(_data())
        page.app.push_screen(modal)
        await page.expect_modal("SudoRequestModal")
        await wait_for_state(
            page,
            lambda: len(modal.query("#sudo-run")) == 1,
            description="sudo request modal controls",
        )
        if show_details:
            modal.action_toggle_details()
            await wait_for_svg_contains(page, "manifest_sha256")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_sudo_request_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        snapshot_name="sudo_request_modal_120x40",
        title="ACE sudo request modal",
    )


async def test_sudo_request_modal_details_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        snapshot_name="sudo_request_modal_details_120x40",
        title="ACE sudo request modal details",
        show_details=True,
    )
