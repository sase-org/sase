"""PNG snapshots for ACE plan approval gate modals."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _plan_file(tmp_path: Path, name: str, text: str) -> Path:
    plan = tmp_path / name
    plan.write_text(text, encoding="utf-8")
    return plan


async def _snapshot_plan_gate(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: Path,
    default_choice: str,
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
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            PlanApprovalModal(str(plan), default_choice=default_choice)
        )
        await page.expect_modal("PlanApprovalModal")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_tale_plan_gate_five_controls_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan_file(
        tmp_path,
        "release-plan.md",
        "# Release plan\n\nDeploy the signed build safely.\n",
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_five_controls_120x40",
        title="ACE tale plan gate five controls",
    )


async def test_tale_plan_gate_frontmatter_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan_file(
        tmp_path,
        "frontmatter-plan.md",
        "---\n"
        "tier: tale\n"
        "title: Frontmatter syntax highlighting in gate review documents\n"
        "goal: >\n"
        "  Make plan metadata clear and readable without changing document layout.\n"
        "size: small\n"
        "---\n\n"
        "# Frontmatter highlighting\n\n"
        "Render YAML metadata before the Markdown plan body.\n",
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_frontmatter_120x40",
        title="ACE tale plan gate frontmatter highlighting",
    )


async def test_epic_plan_gate_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan_file(
        tmp_path,
        "epic-plan.md",
        "# Epic plan\n\nCoordinate the approved tales.\n",
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="epic",
        snapshot_name="plan_gate_epic_action_120x40",
        title="ACE epic plan gate action",
    )


async def test_narrow_plan_gate_stacked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = _plan_file(
        tmp_path,
        "narrow-plan.md",
        "# Narrow plan\n\nReview the document above the available actions.\n",
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_stacked_90x40",
        title="ACE narrow stacked tale plan gate",
        size=(90, 40),
    )
