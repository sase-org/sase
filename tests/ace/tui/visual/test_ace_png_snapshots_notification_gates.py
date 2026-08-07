"""PNG snapshots for the always-populated notification gate detail pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.notification_gates.summary import (
    GateSummary,
    GateSummaryBranch,
    GateSummaryOption,
)
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

_NOTE = (
    "Bead sase-gn.10.2 must pin sase-core-rs to >=0.19.0 before the snooze close "
    "path can be covered against a real store."
)


def _options(*, selected: tuple[str, ...] = ()) -> tuple[GateSummaryOption, ...]:
    return (
        GateSummaryOption(
            id="bump",
            label="Bump the floor and verify",
            icon="🚀",
            argv=("commands/bump",),
            feedback="optional",
            default_selected=True,
            selected="bump" in selected,
        ),
        GateSummaryOption(
            id="verify",
            label="Verify service health",
            icon="🩺",
            argv=("commands/verify",),
            feedback="disabled",
            default_selected=True,
            selected="verify" in selected,
        ),
    )


def _branches(*, selected: tuple[str, ...] = ()) -> tuple[GateSummaryBranch, ...]:
    return (
        GateSummaryBranch(
            option_ids=("bump", "verify"),
            label="Bump the floor and verify",
            icon="🚀",
            is_primary=True,
            options=_options(selected=selected),
        ),
        GateSummaryBranch(
            option_ids=("reject",),
            label="Leave the floor alone",
            icon=None,
            is_primary=False,
            options=(
                GateSummaryOption(
                    id="reject",
                    label="Leave the floor alone",
                    icon=None,
                    argv=("commands/reject",),
                    feedback="required",
                    default_selected=True,
                    selected="reject" in selected,
                ),
            ),
        ),
    )


def _notification() -> Notification:
    return Notification(
        id="visual-pin-core",
        timestamp="2026-08-01T00:57:22-04:00",
        sender="sase-gn.10.2",
        icon="🚀",
        notes=[_NOTE],
        tags=["beads", "release"],
        action="CustomGate",
        action_data={
            "request_id": "pin-core-0.19",
            "gate_title": "Pin sase-core-rs to >=0.19.0",
        },
        files=["request.diff"],
    )


def _pending_summary() -> GateSummary:
    return GateSummary(
        kind="custom",
        display_title="Custom Gate",
        title="Pin sase-core-rs to >=0.19.0",
        request_id="pin-core-0.19",
        status="pending",
        deadline_at="2026-08-01T01:09:22-04:00",
        query="(bump AND verify) OR reject",
        branches=_branches(),
        selected_option_ids=(),
        feedback=None,
        attachments=("request.diff",),
        error_count=0,
        bundle_path=None,
        unavailable_reason=None,
    )


def _answered_summary() -> GateSummary:
    return GateSummary(
        kind="custom",
        display_title="Custom Gate",
        title="Pin sase-core-rs to >=0.19.0",
        request_id="pin-core-0.19",
        status="answered",
        deadline_at=None,
        query="(bump AND verify) OR reject",
        branches=_branches(selected=("bump", "verify")),
        selected_option_ids=("bump", "verify"),
        feedback="Verified locally before landing.",
        attachments=("request.diff",),
        error_count=0,
        bundle_path=None,
        unavailable_reason=None,
    )


def _modal_with_cached_summary(summary: GateSummary) -> NotificationModal:
    notification = _notification()
    modal = NotificationModal([notification])
    modal._gate_summary_cache[notification.id] = ((), summary)
    return modal


def _patch_modal_determinism(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "7h ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_absolute_time",
        lambda _timestamp, now=None: "today 00:57:22",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "7h ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_gate.format_relative_until",
        lambda _timestamp: "12m",
    )


async def test_pending_custom_gate_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_modal_determinism(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(_modal_with_cached_summary(_pending_summary()))
        await page.expect_modal("NotificationModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Pin sase-core-rs to")
        assert_page_svg_contains(page, "Awaiting your decision")
        assert_page_svg_contains(page, "Bump the floor and verify")
        assert_page_svg_contains(page, "Leave the floor alone")
        assert_page_svg_contains(page, "Attachments")
        ace_png_visual.assert_page_png(
            page,
            "notification_gate_pending_120x40",
            title="ACE pending custom gate detail card",
        )


async def test_answered_custom_gate_card_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_modal_determinism(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(_modal_with_cached_summary(_answered_summary()))
        await page.expect_modal("NotificationModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Answered")
        assert_page_svg_contains(page, "Verified locally before landing.")
        ace_png_visual.assert_page_png(
            page,
            "notification_gate_answered_120x40",
            title="ACE answered custom gate detail card",
        )
