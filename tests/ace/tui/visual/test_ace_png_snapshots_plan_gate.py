"""PNG snapshots for ACE plan approval gate modals."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
from sase.notification_gates.branches import GateBranchData
from sase.plan_approval_choices import PlanApprovalModalChoice
from tests.ace.tui.visual._ace_plan_decisions_png_fixtures import (
    EPIC_DECISIONS_PLAN,
    MAXCOPY_PLAN,
    SYNCTHING_PLAN,
    TALE_CHOICES_PLAN,
    TALE_MEMORY_PLAN,
    decision_gate_bundle,
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


def _plan_file(tmp_path: Path, name: str, text: str) -> Path:
    plan = tmp_path / name
    plan.write_text(text, encoding="utf-8")
    return plan


async def _snapshot_plan_gate(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: Path,
    default_choice: PlanApprovalModalChoice,
    snapshot_name: str,
    title: str,
    size: tuple[int, int] = (120, 40),
    gate: GateBranchData | None = None,
    plan_content: str | None = None,
    decision_definitions: list[dict] | None = None,
    review_revision: int | None = None,
    request_id: str | None = None,
    keys: tuple[str, ...] = (),
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
        page.app.push_screen(
            PlanApprovalModal(
                str(plan),
                default_choice=default_choice,
                gate=gate,
                plan_content=plan_content,
                decision_definitions=decision_definitions,
                review_revision=review_revision,
                request_id=request_id,
            )
        )
        await page.expect_modal("PlanApprovalModal")
        if keys:
            await page.press(*keys)
        if decision_definitions:
            first = decision_definitions[0]
            ask = str(first.get("ask") or "").strip()
            ident = str(first.get("id") or "").strip()
            # Compact 90-col cards list ids only; the 120-char ask paints in
            # the wider decision-card column that the full-run truncation wait
            # has to pin.
            sentinel = ask[:24] if size[0] >= 120 and ask else (ident or ask[:24])
            if sentinel:
                await wait_for_svg_contains(page, sentinel)
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


async def test_tale_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tale gate with two choice decisions from a real gate spec."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="tale-decisions.md",
        content=TALE_CHOICES_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_120x40",
        title="ACE tale plan gate with decisions",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-tale-decisions",
    )


async def test_tale_plan_gate_decisions_memory_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tale gate with a verified memory decision (the "you asked" case)."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="tale-decisions-memory.md",
        content=TALE_MEMORY_PLAN,
        verified_memory=True,
    )
    assert any(item.get("provenance") == "asked" for item in definitions), (
        "expected a verified memory definition from the gate spec"
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_memory_120x40",
        title="ACE tale plan gate with verified memory decision",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-tale-decisions-memory",
    )


async def test_tale_plan_gate_decisions_unverified_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tale gate with an unverified memory quote (quote_not_found)."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="tale-decisions-unverified.md",
        content=TALE_MEMORY_PLAN,
    )
    assert any(item.get("provenance") == "quote_not_found" for item in definitions), (
        "expected an unverified memory definition from the gate spec"
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_unverified_120x40",
        title="ACE tale plan gate with unverified memory decision",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-tale-decisions-unverified",
    )


async def test_narrow_plan_gate_decisions_stacked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Narrow tale gate with decisions from a real gate spec."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="narrow-decisions.md",
        content=TALE_CHOICES_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_stacked_90x40",
        title="ACE narrow stacked tale plan gate with decisions",
        size=(90, 40),
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-tale-decisions-stacked",
    )


async def test_epic_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Epic gate with a choice decision from a real gate spec."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="epic-decisions.md",
        content=EPIC_DECISIONS_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="epic",
        snapshot_name="plan_gate_epic_decisions_120x40",
        title="ACE epic plan gate with decisions",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=1,
        request_id="visual-epic-decisions",
    )


async def test_syncthing_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tale gate with the four-decision syncthing fixture at 120x40."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="syncthing-decisions.md",
        content=SYNCTHING_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_syncthing_120x40",
        title="ACE tale plan gate with syncthing decisions",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-syncthing-decisions",
    )


async def test_syncthing_wide_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tale gate with the four-decision syncthing fixture at 200x56."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="syncthing-decisions-wide.md",
        content=SYNCTHING_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_syncthing_200x56",
        title="ACE wide tale plan gate with syncthing decisions",
        size=(200, 56),
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-syncthing-decisions-wide",
    )


async def test_syncthing_narrow_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The pinned syncthing rail at the 90x40 narrow breakpoint."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="syncthing-decisions-narrow.md",
        content=SYNCTHING_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_syncthing_90x40",
        title="ACE narrow tale plan gate with syncthing decisions",
        size=(90, 40),
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-syncthing-decisions-narrow",
    )


async def test_syncthing_extra_wide_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The responsive rail at the user's 262x72 terminal size."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="syncthing-decisions-extra-wide.md",
        content=SYNCTHING_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_syncthing_262x72",
        title="ACE extra-wide tale plan gate with syncthing decisions",
        size=(262, 72),
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-syncthing-decisions-extra-wide",
    )


async def test_maxcopy_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Tale gate with five grammar-limit decisions (verified memory last)."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="maxcopy-decisions.md",
        content=MAXCOPY_PLAN,
        verified_memory=True,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_maxcopy_120x40",
        title="ACE tale plan gate with grammar-limit decisions",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-maxcopy-decisions",
    )


async def test_maxcopy_narrow_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The five grammar-limit decisions stay pinned at 90x40."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="maxcopy-decisions-narrow.md",
        content=MAXCOPY_PLAN,
        verified_memory=True,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_maxcopy_90x40",
        title="ACE narrow tale plan gate with grammar-limit decisions",
        size=(90, 40),
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-maxcopy-decisions-narrow",
    )


async def test_syncthing_sheet_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Full-width decision sheet at 120x40."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="syncthing-decisions-sheet.md",
        content=SYNCTHING_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_sheet_120x40",
        title="ACE tale plan gate decision sheet",
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-syncthing-sheet",
        keys=("z",),
    )


async def test_syncthing_narrow_sheet_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Full-width decision sheet at the 90x40 narrow breakpoint."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="syncthing-decisions-sheet-narrow.md",
        content=SYNCTHING_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_sheet_90x40",
        title="ACE narrow tale plan gate decision sheet",
        size=(90, 40),
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-syncthing-sheet-narrow",
        keys=("z",),
    )


async def test_syncthing_extra_wide_sheet_plan_gate_decisions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Full-width decision sheet at the user's 262x72 terminal size."""
    plan, gate, definitions = decision_gate_bundle(
        tmp_path,
        monkeypatch,
        name="syncthing-decisions-sheet-extra-wide.md",
        content=SYNCTHING_PLAN,
    )
    await _snapshot_plan_gate(
        ace_png_visual,
        monkeypatch,
        plan=plan,
        default_choice="tale",
        snapshot_name="plan_gate_tale_decisions_sheet_262x72",
        title="ACE extra-wide tale plan gate decision sheet",
        size=(262, 72),
        gate=gate,
        plan_content=plan.read_text(encoding="utf-8"),
        decision_definitions=definitions,
        review_revision=3,
        request_id="visual-syncthing-sheet-extra-wide",
        keys=("z",),
    )
