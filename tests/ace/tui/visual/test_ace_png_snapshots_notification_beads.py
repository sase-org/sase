"""PNG snapshots for bead notification panel routing and task-triage gates."""

from __future__ import annotations

from typing import Any, cast

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
)
from sase.ace.tui.modals.gate_branch_controls import GateBranchData
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.bead._task_gate_spec import build_task_triage_gate_spec
from sase.bead.model import TaskPlusOneEvidence
from sase.notification_gates.models import GateOption
from sase.notification_gates.registry import adapter_for_kind
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


def _task_notification(
    notification_id: str,
    timestamp: str,
    bead_id: str,
    title: str,
    *,
    origin_agent: str | None = "bbugyi200.athena.claude_coder",
) -> Notification:
    action_data = {"panel": "beads"}
    if origin_agent is not None:
        action_data["origin_agent"] = origin_agent
    return Notification(
        id=notification_id,
        timestamp=timestamp,
        sender="bead",
        icon="✦",
        notes=[f"{bead_id} — {title}"],
        tags=["bead", "task"],
        action="TaskTriage",
        action_data=action_data,
    )


def _notifications() -> list[Notification]:
    return [
        Notification(
            id="visual-plan-approval",
            timestamp="2026-08-01T09:45:00-04:00",
            sender="plan",
            notes=["Review the staged notification panel plan."],
            action="PlanApproval",
        ),
        _task_notification(
            "visual-task-no-filer",
            "2026-08-01T09:44:00-04:00",
            "sase-cx",
            (
                "Flaky: test_agents_slow_tool_calls_fold_levels_png_snapshots "
                "fails only under full parallel suite"
            ),
            origin_agent=None,
        ),
        _task_notification(
            "visual-task-with-filer",
            "2026-08-01T09:43:00-04:00",
            "sase-cy",
            "Add mobile bridge retry badge",
        ),
        _task_notification(
            "visual-task-docs",
            "2026-08-01T09:42:00-04:00",
            "sase-cz",
            "Update task triage task page",
        ),
        _task_notification(
            "visual-task-cleanup",
            "2026-08-01T09:41:00-04:00",
            "sase-da",
            "Restore pending gate cleanup",
        ),
        Notification(
            id="visual-error",
            timestamp="2026-08-01T09:40:00-04:00",
            sender="axe",
            notes=["Hourly checks found 2 failures."],
            action="ViewErrorReport",
        ),
        Notification(
            id="visual-done",
            timestamp="2026-08-01T09:39:00-04:00",
            sender="user-agent",
            notes=["sase-cw finished updating the status footer."],
            tags=["done"],
            action="JumpToAgent",
        ),
    ]


def _patch_modal_determinism(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_absolute_time",
        lambda _timestamp, now=None: "today 09:44:00",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    monkeypatch.setattr(
        "sase.core.agent_identity_facade.present_agent_name",
        lambda _name: "claude_coder",
    )


def _beads_modal(*, initial_index: int = 0) -> NotificationModal:
    modal = NotificationModal(_notifications(), initial_index=initial_index)
    modal._active_notification_tag = "beads"
    return modal


async def test_notification_beads_tab_png_snapshot(
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
        page.app.push_screen(_beads_modal())
        await page.expect_modal("NotificationModal")
        await wait_for_visual_idle(page)

        # The icons push the full-label strip past the modal's width, so the
        # inactive tabs shed their labels rather than clipping off the end;
        # every tab is still on screen, and the active one still names itself.
        assert_page_svg_contains(page, "Beads")
        assert_page_svg_contains(page, "[bead]")
        assert_page_svg_contains(page, "sase-cx")
        ace_png_visual.assert_page_png(
            page,
            "notification_beads_tab_120x40",
            title="ACE notification Beads panel tab",
        )


async def test_notification_filed_by_png_snapshot(
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
        page.app.push_screen(_beads_modal(initial_index=2))
        await page.expect_modal("NotificationModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "sase-cy")
        assert_page_svg_contains(page, "filed by")
        assert_page_svg_contains(page, "@claude_coder")
        ace_png_visual.assert_page_png(
            page,
            "notification_filed_by_120x40",
            title="ACE notification Filed by meta line",
        )


def _task_triage_modal_data() -> CustomGateModalData:
    spec = build_task_triage_gate_spec(
        request_id="bead-task-triage-sase-cx-e9a1f-g1",
        bead_id="sase-cx",
        project="sase",
        title=(
            "Flaky: test_agents_slow_tool_calls_fold_levels_png_snapshots "
            "fails only under full parallel suite"
        ),
        description=(
            "The PNG snapshot test intermittently fails when the full parallel "
            "suite is active. Capture the failing seed and isolate the shared "
            "renderer state before changing goldens."
        ),
        notes="Discovered while landing sase-cw.",
        created_by="claude_coder",
        size="medium",
        refs=("research:202608/flaky-renderer.md",),
        plus_one_evidence=(
            TaskPlusOneEvidence(
                timestamp="2026-08-01T15:00:00Z",
                reporter="codex_reviewer",
                note="Reproduced under the same parallel renderer load.",
                refs=("research:202608/flaky-renderer.md",),
            ),
        ),
        producer={"agent": "bead_task_triage"},
    )
    adapter = adapter_for_kind("task_triage")
    raw_options = cast(list[dict[str, Any]], spec["options"])
    options = tuple(
        GateOption.from_mapping(
            raw_option,
            index,
            default_feedback=adapter.default_feedback,
        )
        for index, raw_option in enumerate(raw_options)
    )
    resources = cast(list[dict[str, Any]], spec["resources"])
    preview_text = next(
        str(resource["content"])
        for resource in resources
        if resource["path"] == "task.md"
    )
    presentation = cast(dict[str, Any], spec["presentation"])
    return CustomGateModalData(
        request_id=str(spec["request_id"]),
        title=adapter.display_title,
        sender=str(presentation["sender"]),
        icon=str(presentation["icon"]),
        notes=tuple(str(note) for note in presentation["notes"]),
        attachments=("task.md",),
        preview_name="task.md",
        preview_text=preview_text,
        gate=GateBranchData(
            query=str(spec["query"]),
            options=options,
            groups=(),
            branches=(("launch",), ("close",), ("snooze",)),
            primary_branch=("launch",),
        ),
        origin_agent=str(presentation["origin_agent"]),
        gate_title=str(presentation["title"]),
    )


async def test_custom_gate_task_triage_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        "sase.core.agent_identity_facade.present_agent_name",
        lambda _name: "claude_coder",
    )

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(CustomGateModal(_task_triage_modal_data()))
        await page.expect_modal("CustomGateModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Task Triage")
        assert_page_svg_contains(page, "Filed by")
        assert_page_svg_contains(page, "@claude_coder")
        assert_page_svg_contains(page, "task.md")
        assert_page_svg_contains(page, "Launch")
        assert_page_svg_contains(page, "Close")
        assert_page_svg_contains(page, "Snooze")
        ace_png_visual.assert_page_png(
            page,
            "custom_gate_task_triage_120x40",
            title="ACE task triage generic gate",
        )
