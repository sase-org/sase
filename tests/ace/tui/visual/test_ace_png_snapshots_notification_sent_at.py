"""PNG snapshot coverage for the notification detail pane's sent-time line."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_tags import SNOOZED_TAB_KEY
from sase.notifications import Notification
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _notification(attachment_path: str) -> Notification:
    return Notification(
        id="visual-sent-at",
        timestamp="2026-07-31T08:00:00-04:00",
        sender="axe",
        icon="🤖",
        notes=["lint run finished"],
        files=[attachment_path],
    )


async def test_notification_sent_at_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    attachment = tmp_path / "lint_summary.txt"
    attachment.write_text("0 errors, 2 warnings\n", encoding="utf-8")
    notification = _notification(str(attachment))
    # The detail pane renders the attachment path, and ``tmp_path`` embeds a
    # per-repo scratch root plus a per-run counter. Pin the displayed path so
    # the golden stays byte-identical across workspaces and runs; the real
    # ``tmp_path`` file is still what gets opened and previewed.
    monkeypatch.setattr(
        NotificationModal,
        "_shorten_path",
        staticmethod(lambda _path: "~/.sase/notifications/lint_summary.txt"),
    )
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_absolute_time",
        lambda _timestamp, now=None: "today 08:00:00",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "4m ago",
    )

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(NotificationModal([notification]))
        await page.expect_modal("NotificationModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "sent")
        assert_page_svg_contains(page, "today 08:00:00")
        assert_page_svg_contains(page, "4m ago")
        assert_page_svg_contains(page, "0 errors, 2 warnings")
        ace_png_visual.assert_page_png(
            page,
            "notification_sent_at_120x40",
            title="ACE notification detail pane sent-time header",
        )


async def test_notification_selected_snooze_status_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timezone = ZoneInfo("America/New_York")
    now = datetime(2026, 8, 8, 10, 40, tzinfo=timezone)
    wake = datetime(2026, 8, 14, 10, 39, tzinfo=timezone)
    snoozed = Notification(
        id="visual-snoozed-long-row",
        timestamp=(now - timedelta(minutes=4)).isoformat(),
        sender="beads",
        icon="☾",
        notes=[
            "Release-blocking bead with an intentionally long title whose "
            "left-row snooze suffix is clipped"
        ],
        muted=True,
        snooze_until=wake.isoformat(),
        tags=["release-blocker"],
    )
    ordinary = Notification(
        id="visual-ordinary-row",
        timestamp=(now - timedelta(minutes=2)).isoformat(),
        sender="axe",
        notes=["Ordinary row used to keep the fixture mixed"],
    )
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_snooze_status._snooze_status_now",
        lambda: now,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_until",
        lambda _timestamp: "5d 23h",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_absolute_time",
        lambda _timestamp, now=None: "today 10:36:00",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "4m ago",
    )

    modal = NotificationModal([snoozed, ordinary])
    modal._active_notification_tag = SNOOZED_TAB_KEY

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(modal)
        await page.expect_modal("NotificationModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Snoozed")
        assert_page_svg_contains(page, "5d 23h")
        assert_page_svg_contains(page, "Fri Aug 14 at 10:39 EDT")
        ace_png_visual.assert_page_png(
            page,
            "notification_selected_snooze_status_120x40",
            title="ACE notification detail pane selected snooze status",
        )
