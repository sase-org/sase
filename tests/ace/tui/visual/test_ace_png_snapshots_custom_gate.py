"""PNG snapshots for branch-driven ACE gate modals."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
)
from sase.ace.tui.modals.gate_action_controls import GateActionsData
from sase.ace.tui.modals.gate_branch_controls import GateBranchData
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
from sase.notification_gates.model_operations import GateOperation
from sase.notification_gates.models import GateGroup, GateOption
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
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


def _option_with_inputs(option_id: str, label: str, *, icon: str) -> GateOption:
    return GateOption.from_mapping(
        {
            "id": option_id,
            "label": label,
            "icon": icon,
            "default_selected": True,
            "command": {"argv": [f"commands/{option_id}"]},
            "inputs": [
                {
                    "id": "target_env",
                    "label": "Target environment",
                    "type": "line",
                    "required": True,
                },
                {
                    "id": "mode",
                    "label": "Mode",
                    "type": "enum",
                    "choices": ["fast", "thorough"],
                },
                {
                    "id": "token",
                    "label": "Access token",
                    "type": "line",
                    "secret": True,
                },
            ],
        },
        0,
        default_feedback="optional",
    )


_NO_ACTIONS = GateActionsData()


def _actions(*, draft: bool = False) -> GateActionsData:
    operations = (
        GateOperation.from_mapping(
            {
                "id": "edit_manifest",
                "kind": "edit_file",
                "target": "release-preview.md",
                "edit_target": "origin",
                "label": "Edit manifest",
                "icon": "\u270f\ufe0f",
                "key": "e",
                "description": "Accepted only when the manifest validates.",
            },
            0,
        ),
        GateOperation.from_mapping(
            {
                "id": "show_diff",
                "kind": "run_command",
                "command": {"argv": ["commands/show_diff"]},
                "label": "Show diff",
                "icon": "\U0001f50d",
                "key": "x",
                "display": "markdown",
            },
            1,
        ),
    )
    if not draft:
        return GateActionsData(operations=operations)
    return GateActionsData(
        operations=operations,
        draft_operation_id="edit_manifest",
        draft_path="~/.sase/plans/202608/release.md",
    )


def _data(
    *,
    options: tuple[GateOption, ...],
    branches: tuple[tuple[str, ...], ...],
    groups: tuple[GateGroup, ...] = (),
    preview: bool = True,
    frontmatter: bool = False,
    actions: GateActionsData = _NO_ACTIONS,
) -> CustomGateModalData:
    preview_text = (
        "# Production deployment\n\n"
        "- Version: `0.10.2`\n"
        "- Region: `us-east-1`\n"
        "- Health checks: passing\n"
    )
    if frontmatter:
        preview_text = (
            "---\n"
            "owner: release-guardian\n"
            "environment: production\n"
            "goal: >\n"
            "  Verify the signed build is healthy before deployment.\n"
            "---\n\n"
            f"{preview_text}"
        )
    return CustomGateModalData(
        request_id="deploy-production-42",
        title="Custom Gate",
        sender="release-guardian",
        icon="🛡️",
        notes=(
            "The release agent is ready to deploy the signed build.",
            "Choose one resolution branch.",
        ),
        attachments=("release-preview.md", "deployment-manifest.json"),
        preview_name="release-preview.md" if preview else None,
        preview_text=preview_text if preview else None,
        gate=GateBranchData(
            query="visual query",
            options=options,
            groups=groups,
            branches=branches,
            primary_branch=branches[0],
        ),
        gate_title="Approve production deployment",
        actions=actions,
    )


async def _snapshot_modal(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    data: CustomGateModalData,
    snapshot_name: str,
    title: str,
    size: tuple[int, int] = (120, 40),
) -> None:
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=size,
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
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


async def test_custom_gate_no_preview_png_snapshot(
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
        data=_data(
            options=options,
            branches=(("approve",), ("cancel",)),
            preview=False,
        ),
        snapshot_name="custom_gate_no_preview_120x40",
        title="ACE compact custom gate without preview",
    )


async def test_custom_gate_frontmatter_png_snapshot(
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
        data=_data(
            options=options,
            branches=(("approve",), ("cancel",)),
            frontmatter=True,
        ),
        snapshot_name="custom_gate_frontmatter_120x40",
        title="ACE custom gate frontmatter highlighting",
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
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PlanApprovalModal(str(plan), default_choice="tale"))
        await page.expect_modal("PlanApprovalModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "plan_gate_tale_five_controls_120x40",
            title="ACE tale plan gate five controls",
        )


async def test_tale_plan_gate_frontmatter_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "frontmatter-plan.md"
    plan.write_text(
        "---\n"
        "tier: tale\n"
        "title: Frontmatter syntax highlighting in gate review documents\n"
        "goal: >\n"
        "  Make plan metadata clear and readable without changing document layout.\n"
        "---\n\n"
        "# Frontmatter highlighting\n\n"
        "Render YAML metadata before the Markdown plan body.\n",
        encoding="utf-8",
    )
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PlanApprovalModal(str(plan), default_choice="tale"))
        await page.expect_modal("PlanApprovalModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "plan_gate_frontmatter_120x40",
            title="ACE tale plan gate frontmatter highlighting",
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
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PlanApprovalModal(str(plan), default_choice="epic"))
        await page.expect_modal("PlanApprovalModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "plan_gate_epic_action_120x40",
            title="ACE epic plan gate action",
        )


async def test_narrow_plan_gate_stacked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = tmp_path / "narrow-plan.md"
    plan.write_text(
        "# Narrow plan\n\nReview the document above the available actions.\n",
        encoding="utf-8",
    )
    patch_startup_loaders(monkeypatch, agents=[])
    async with AcePage(
        query='"visual"',
        size=(90, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PlanApprovalModal(str(plan), default_choice="tale"))
        await page.expect_modal("PlanApprovalModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "plan_gate_tale_stacked_90x40",
            title="ACE narrow stacked tale plan gate",
        )


async def test_custom_gate_actions_section_png_snapshot(
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
        data=_data(
            options=options,
            branches=(("approve",), ("cancel",)),
            actions=_actions(),
        ),
        snapshot_name="custom_gate_actions_120x40",
        title="ACE custom gate Actions section",
    )


async def test_custom_gate_inputs_section_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = (
        _option_with_inputs("deploy", "Deploy signed build", icon="🚀"),
        _option("cancel", "Cancel release", icon="🛑"),
    )
    # Two-pane mode (preview_text set) gives the Actions column unbounded
    # height (no compact-mode 30-row cap); trimmed notes/attachments plus a
    # taller viewport fit every field -- a required line, an enum, and a
    # secret -- without scrolling.
    data = CustomGateModalData(
        request_id="deploy-production-42",
        title="Custom Gate",
        sender="release-guardian",
        icon="🛡️",
        notes=("Choose one resolution branch.",),
        attachments=(),
        preview_name="release-preview.md",
        preview_text="# Production deployment\n\nVersion: `0.10.2`\n",
        gate=GateBranchData(
            query="visual query",
            options=options,
            groups=(),
            branches=(("deploy",), ("cancel",)),
            primary_branch=("deploy",),
        ),
        gate_title="Approve production deployment",
    )
    await _snapshot_modal(
        ace_png_visual,
        monkeypatch,
        data=data,
        snapshot_name="custom_gate_inputs_120x45",
        title="ACE custom gate Inputs section",
        size=(120, 45),
    )


async def test_custom_gate_draft_banner_png_snapshot(
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
        data=_data(
            options=options,
            branches=(("approve",), ("cancel",)),
            actions=_actions(draft=True),
        ),
        snapshot_name="custom_gate_draft_banner_120x40",
        title="ACE custom gate unaccepted draft banner",
    )
