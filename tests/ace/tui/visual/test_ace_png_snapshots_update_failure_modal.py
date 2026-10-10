"""sase's TUI PNG visual snapshots for the update failure report modal."""

from __future__ import annotations

import pytest

from sase.ace._update_attempts_model import UpdateFailure
from sase.ace.testing import AcePage
from sase.ace.tui.modals.update_failure_modal import UpdateFailureModal
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
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


def _compact_failure() -> UpdateFailure:
    return UpdateFailure(
        attempt_id="visual-failure-compact",
        label="sase update",
        proc_type="comprehensive-update",
        stage="apply",
        started_at=1700000000.0,
        finished_at=1700000010.0,
        error="update failed: exit status 1",
        output_tail="line one\nline two",
        interrupted=False,
    )


def _screenshot_failure() -> UpdateFailure:
    command = (
        "git -c core.quotepath=false fetch --prune origin "
        "+refs/heads/*:refs/remotes/origin/* "
        "/very/long/repository/path/that/keeps/going/beyond/ninety/columns/tree/main"
    )
    explanation = (
        "update failed: refusing to merge: index.lock exists; "
        "another git process seems to be running"
    )
    output = "\n".join(
        [
            f"$ {command}",
            "remote: Enumerating objects: 128, done.",
            "error: cannot lock ref: index.lock exists",
            *(
                f"output row {i:02d}: fetching refs/heads/feature-{i}"
                for i in range(30)
            ),
        ]
    )
    return UpdateFailure(
        attempt_id="visual-failure-large",
        label="sase update",
        proc_type="comprehensive-update",
        stage="apply",
        started_at=1700000000.0,
        finished_at=1700000010.0,
        error=explanation,
        output_tail=output,
        interrupted=False,
    )


async def test_update_failure_modal_compact_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A two-line failure stays compact with no scroll hint."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(120, 40)) as page:
        await wait_for_startup(page)
        page.app.push_screen(UpdateFailureModal(_compact_failure()))
        await page.expect_modal("UpdateFailureModal")
        await wait_for_svg_contains(page, "Update failed")
        await wait_for_svg_contains(page, "line one")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Update failed")
        assert_page_svg_contains(page, "open Update")

        ace_png_visual.assert_page_png(
            page,
            "update_failure_modal_compact_120x40",
            title="ACE update failure report compact",
        )


async def test_update_failure_modal_expanded_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A screenshot-inspired failure uses the available screen effectively."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(160, 50)) as page:
        await wait_for_startup(page)
        page.app.push_screen(UpdateFailureModal(_screenshot_failure()))
        await page.expect_modal("UpdateFailureModal")
        await wait_for_svg_contains(page, "Update failed")
        await wait_for_svg_contains(page, "index.lock")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Update failed")
        assert_page_svg_contains(page, "last output")

        ace_png_visual.assert_page_png(
            page,
            "update_failure_modal_expanded_160x50",
            title="ACE update failure report expanded",
        )


async def test_update_failure_modal_overflow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long report on a small terminal keeps title and actions visible."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(80, 24)) as page:
        await wait_for_startup(page)
        page.app.push_screen(UpdateFailureModal(_screenshot_failure()))
        await page.expect_modal("UpdateFailureModal")
        await wait_for_svg_contains(page, "Update failed")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Update failed")
        assert_page_svg_contains(page, "open Update")

        ace_png_visual.assert_page_png(
            page,
            "update_failure_modal_overflow_80x24",
            title="ACE update failure report overflow",
        )


async def test_update_failure_modal_minimum_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At 40x12 all actions and at least one report row stay visible."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(40, 12)) as page:
        await wait_for_startup(page)
        page.app.push_screen(UpdateFailureModal(_screenshot_failure()))
        await page.expect_modal("UpdateFailureModal")
        await wait_for_svg_contains(page, "Update")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Update")

        ace_png_visual.assert_page_png(
            page,
            "update_failure_modal_minimum_40x12",
            title="ACE update failure report minimum",
        )
