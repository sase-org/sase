"""PNG snapshot coverage for structured report notification surfaces."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.report_modal import ReportModal
from sase.notifications import Notification, NotificationReport
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


def _release_report() -> dict[str, object]:
    return {
        "title": "Releases",
        "blocks": [
            {
                "kind": "headline",
                "text": "2 merged today · 3 pending · 1 blocked",
                "tone": "ok",
            },
            {"kind": "heading", "text": "RECENT"},
            {
                "kind": "rows",
                "columns": ["REPOSITORY", "PR", "VERSION", "MERGED"],
                "rows": [
                    {
                        "cells": [
                            "sase-org/sase-core",
                            "#46",
                            "0.9.3",
                            "07-29 10:14",
                        ],
                        "tone": "ok",
                    },
                    {
                        "cells": [
                            "sase-org/sase-core",
                            "#45",
                            "0.9.2",
                            "07-29 09:39",
                        ],
                        "tone": "ok",
                    },
                    {
                        "cells": [
                            "sase-org/sase-telegram",
                            "#12",
                            "0.2.0",
                            "07-28 17:41",
                        ],
                        "tone": "ok",
                    },
                ],
            },
            {"kind": "heading", "text": "PENDING"},
            {
                "kind": "rows",
                "columns": ["REPOSITORY", "PR", "STATE", "AGE"],
                "rows": [
                    {
                        "cells": [
                            "sase-org/sase",
                            "#312",
                            "checks not green",
                            "14m",
                        ],
                        "tone": "warn",
                    },
                    {
                        "cells": [
                            "sase-org/sase-github",
                            "#88",
                            "base branch not green",
                            "2h",
                        ],
                        "tone": "error",
                    },
                    {
                        "cells": [
                            "sase-org/sase-telegram",
                            "—",
                            "no release PR",
                            "—",
                        ],
                        "tone": "muted",
                    },
                ],
            },
            {"kind": "divider"},
            {
                "kind": "text",
                "text": "window 30d · merges recorded 11",
                "tone": "muted",
            },
        ],
    }


_REPORT_PATH = "/srv/sase/ci_watch_releases.report.json"


def _notification() -> Notification:
    return Notification(
        id="visual-release-report",
        timestamp="2026-07-29T10:14:17-04:00",
        sender="ci_watch",
        icon="🚦",
        notes=["Merged release PR #46 for sase-org/sase-core"],
        tags=["release"],
        action="ViewReport",
        action_data={
            "report_path": _REPORT_PATH,
            "report_title": "Release readiness",
        },
    )


def _freeze_report_ages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_report.format_relative_time",
        lambda _timestamp: "2m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.report_modal.format_relative_time",
        lambda _timestamp: "2m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "2m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_absolute_time",
        lambda _timestamp, now=None: "today 08:00:00",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "2m ago",
    )


def _resolved_report() -> NotificationReport:
    return NotificationReport(
        document=_release_report(),
        source="live",
        title="Release readiness",
        path=_REPORT_PATH,
        updated_at="2026-07-29T10:14:17-04:00",
        error=None,
    )


async def test_notification_report_pane_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notification = _notification()
    patch_startup_loaders(monkeypatch, agents=[])
    _freeze_report_ages(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_report.load_notification_report",
        lambda _notification: _resolved_report(),
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

        assert_page_svg_contains(page, "Release readiness")
        assert_page_svg_contains(page, "live · updated 2m ago")
        assert_page_svg_contains(page, "checks not green")
        assert_page_svg_contains(page, "sent")
        assert_page_svg_contains(page, "today 08:00:00")
        ace_png_visual.assert_page_png(
            page,
            "notification_report_pane_120x40",
            title="ACE release report notification preview",
        )


async def test_notification_report_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _resolved_report()
    patch_startup_loaders(monkeypatch, agents=[])
    _freeze_report_ages(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(ReportModal(report))
        await page.expect_modal("ReportModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Release readiness")
        assert_page_svg_contains(page, "live · updated 2m ago")
        assert_page_svg_contains(page, "base branch not green")
        ace_png_visual.assert_page_png(
            page,
            "notification_report_modal_120x40",
            title="ACE full release report",
        )
