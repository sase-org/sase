"""PNG snapshots for branch-driven ACE gate modals."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
)
from sase.ace.tui.modals.gate_branch_controls import GateBranchData
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
from sase.notification_gates.models import GateGroup, GateOption
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _option(
    option_id: str,
    label: str,
    *,
    icon: str,
    feedback: str = "disabled",
    selected: bool = True,
) -> GateOption:
    return GateOption.from_mapping(
        {
            "id": option_id,
            "label": label,
            "icon": icon,
            "feedback": feedback,
            "default_selected": selected,
            "command": {"argv": [f"commands/{option_id}"]},
        },
        0,
        default_feedback="optional",
    )


def _data(
    *,
    options: tuple[GateOption, ...],
    branches: tuple[tuple[str, ...], ...],
    groups: tuple[GateGroup, ...] = (),
) -> CustomGateModalData:
    return CustomGateModalData(
        request_id="deploy-production-42",
        sender="release-guardian",
        icon="🛡️",
        notes=(
            "The release agent is ready to deploy the signed build.",
            "Choose one resolution branch.",
        ),
        attachments=("release-preview.md", "deployment-manifest.json"),
        preview_name="release-preview.md",
        preview_text=(
            "# Production deployment\n\n"
            "- Version: `0.10.2`\n"
            "- Region: `us-east-1`\n"
            "- Health checks: passing\n"
        ),
        gate=GateBranchData(
            query="visual query",
            options=options,
            groups=groups,
            branches=branches,
        ),
    )


async def _snapshot_modal(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    data: CustomGateModalData,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(CustomGateModal(data))
        await page.expect_modal("CustomGateModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_custom_gate_choices_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = (
        _option("approve", "Approve deployment", icon="✅"),
        _option("cancel", "Cancel release", icon="🛑"),
    )
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        data=_data(options=options, branches=(("approve",), ("cancel",))),
        snapshot_name="custom_gate_choices_only_120x40",
        title="ACE custom gate singleton branches",
    )


async def test_custom_gate_group_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = (
        _option("deploy", "Deploy signed build", icon="🚀", feedback="optional"),
        _option("announce", "Post release announcement", icon="📣"),
        _option("cancel", "Cancel release", icon="🛑"),
    )
    group = GateGroup(
        ("deploy", "announce"),
        "Deploy signed build",
        "🚀",
    )
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        data=_data(
            options=options,
            branches=(("deploy", "announce"), ("cancel",)),
            groups=(group,),
        ),
        snapshot_name="custom_gate_extras_120x40",
        title="ACE custom gate AND group",
    )


async def test_custom_gate_required_feedback_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = (
        _option("override", "Override warning", icon="⚠️", feedback="required"),
        _option("cancel", "Cancel release", icon="🛑"),
    )
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        data=_data(options=options, branches=(("override",), ("cancel",))),
        snapshot_name="custom_gate_required_feedback_120x40",
        title="ACE custom gate required feedback",
    )


async def test_tale_plan_gate_five_controls_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "release-plan.md"
    plan.write_text(
        "# Release plan\n\nDeploy the signed build safely.\n", encoding="utf-8"
    )
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(PlanApprovalModal(str(plan), default_choice="tale"))
        await page.expect_modal("PlanApprovalModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "plan_gate_tale_five_controls_120x40",
            title="ACE tale plan gate five controls",
        )


async def test_epic_plan_gate_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "epic-plan.md"
    plan.write_text("# Epic plan\n\nCoordinate the approved tales.\n", encoding="utf-8")
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        page.app.push_screen(PlanApprovalModal(str(plan), default_choice="epic"))
        await page.expect_modal("PlanApprovalModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "plan_gate_epic_action_120x40",
            title="ACE epic plan gate action",
        )
