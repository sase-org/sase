"""Plan approval modal wiring: focus flow, esc store, toasts, and gate cards."""

from __future__ import annotations

from sase.ace.tui.modals.plan_decision_sheet import PlanDecisionDraft
from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_esc_store_freeze_and_settled",
    "test_gate_card_decisions_block_pending_and_answered",
    "test_gate_card_pending_toggles_use_checkboxes",
    "test_modal_decisions_focus_step_reset_and_enter",
    "test_modal_result_carries_displayed_revision_and_decisions",
    "test_toast_second_line_and_plan_document_sheet",
]


async def test_modal_decisions_focus_step_reset_and_enter(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals._plan_approval_modal_state import esc_drafts
    from sase.ace.tui.modals.plan_approval_modal import (
        PlanApprovalModal,
        PlanApprovalResult,
    )

    class _TestApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    results: list[PlanApprovalResult | None] = []
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=plan_decision_definitions(tmp_path),
        review_revision=7,
        request_id="req-decisions-1",
    )

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        assert modal.query_one("#plan-decisions-header")
        assert not modal.query("#plan-approval-cancel")
        assert modal.query_one("#plan-decision-0")
        assert modal._decision_draft.value_for("grouping") == "pane"
        await pilot.press("l")
        await pilot.pause()
        assert modal._decision_draft.value_for("grouping") == "mode"
        assert esc_drafts.get("req-decisions-1", {}).get("grouping") == "mode"
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("k")
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        assert modal._decision_draft.value_for("grouping") == "pane"
        await pilot.press("l")
        await pilot.pause()
        assert modal._decision_draft.value_for("grouping") == "mode"
        await pilot.press("R")
        await pilot.pause()
        assert modal._decision_draft.value_for("grouping") == "pane"
        await pilot.press("space")
        await pilot.pause()
        assert modal._decision_draft.value_for("grouping") == "mode"
        await pilot.press("r")
        await pilot.pause()
        assert modal._decision_draft.value_for("grouping") == "pane"
        await pilot.press("enter")
        await pilot.pause()

    assert results[0] is not None
    assert results[0].review_revision == 7
    reopened = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=plan_decision_definitions(tmp_path),
        review_revision=7,
        request_id="req-decisions-1",
    )
    assert reopened._decision_draft.value_for("grouping") == "pane"


def test_esc_store_freeze_and_settled(tmp_path) -> None:
    from sase.ace.tui.modals._plan_approval_modal_state import (
        DECISIONS_FROZEN_MESSAGE,
        esc_drafts,
    )
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    assert "Decisions are fixed for this review" in DECISIONS_FROZEN_MESSAGE
    esc_drafts["req-esc-1"] = {"grouping": "mode"}
    modal = PlanApprovalModal(
        "/tmp/plan.md",
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=[plan_decision_definitions(tmp_path)[0]],
        review_revision=1,
        request_id="req-esc-1",
    )
    assert modal._decision_draft.value_for("grouping") == "mode"
    settled = PlanApprovalModal(
        "/tmp/plan.md",
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=[plan_decision_definitions(tmp_path)[0]],
        review_revision=1,
        request_id="req-settled-1",
        settled_text="Approved via CLI · → coder + commit",
    )
    before = settled._decision_draft.value_for("grouping")
    settled._apply_draft_edit(lambda: settled._decision_draft.step("grouping", 1))
    assert settled._decision_draft.value_for("grouping") == before


def test_toast_second_line_and_plan_document_sheet(tmp_path) -> None:
    from sase.ace.tui.actions.agents._toasts import _plan_toast
    from sase.notifications import Notification

    notification = Notification(
        id="n1",
        timestamp="2026-10-08T00:00:00+00:00",
        sender="agent",
        notes=["Tale ready for review: plan.md", "2 decisions · 🧠 1"],
        files=["/tmp/plan.md"],
        action="PlanApproval",
        action_data={"original_plan_file": "/tmp/plan.md"},
    )
    message, _severity = _plan_toast(notification)
    assert "2 decisions" in message

    from sase.sdd._plan_display_models import PlanDisplay

    summary = PlanDisplay(
        title="T",
        goal="G",
        authored_tier="tale",
        effective_tier="tale",
        actual_path="/tmp/plan.md",
        display_path="/tmp/plan.md",
        committed=None,
        exists=True,
        readable=True,
        frontmatter_readable=True,
        phase_availability="unavailable",
        phases=(),
        validation_ok=True,
        validation_diagnostics=(),
        size=None,
        size_defaulted=False,
        provenance=(),
    )
    from sase.sdd._plan_display_rendering import plan_logical_text

    without = plan_logical_text(summary)
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
    sheet = draft.sheet()
    with_sheet = plan_logical_text(summary, sheet=sheet)
    assert with_sheet.plain != without.plain
    assert "grouping" in with_sheet.plain


def test_modal_result_carries_displayed_revision_and_decisions(tmp_path) -> None:
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
    from sase.notification_gates.branches import GateBranchData
    from sase.notification_gates.models import GateOption

    def _option(option_id: str, decisions: bool) -> GateOption:
        props: dict = {}
        if decisions:
            props["decision_grouping"] = {"enum": ["pane", "mode"]}
        return GateOption.from_mapping(
            {
                "id": option_id,
                "label": option_id,
                "command": {"argv": [f"commands/{option_id}"]},
                "input_schema": {
                    "type": "object",
                    "properties": props,
                    "additionalProperties": False,
                },
            },
            0,
        )

    gate = GateBranchData(
        query="q",
        options=(_option("approve", True), _option("commit", True)),
        groups=(),
        branches=(("approve", "commit"),),
        primary_branch=("approve", "commit"),
    )
    modal = PlanApprovalModal(
        "/tmp/plan.md",
        default_choice="tale",
        plan_content="# Plan\n",
        gate=gate,
        decision_definitions=[plan_decision_definitions(tmp_path)[0]],
        review_revision=9,
        request_id="req-9",
    )
    modal._decision_draft.step("grouping", 1)
    result = modal._result_for_selection(("approve", "commit"))
    assert result.review_revision == 9
    assert result.option_inputs["approve"] == {"decision_grouping": "mode"}
    assert result.option_inputs["commit"] == {"decision_grouping": "mode"}


def test_gate_card_decisions_block_pending_and_answered() -> None:
    from sase.ace.tui.modals.notification_modal_gate import _plan_decisions_block
    from sase.notification_gates.summary import GateSummary

    definitions = ({"id": "grouping", "default": "pane", "effective_default": "pane"},)
    pending = GateSummary(
        kind="plan",
        display_title="Plan",
        title="T",
        request_id="r",
        status="pending",
        deadline_at=None,
        query="q",
        branches=(),
        selected_option_ids=(),
        feedback=None,
        attachments=(),
        error_count=0,
        bundle_path=None,
        unavailable_reason=None,
        plan_decision_definitions=definitions,
        plan_decision_values={"grouping": "pane"},
    )
    block = _plan_decisions_block(pending)
    assert block is not None
    answered = GateSummary(
        kind="plan",
        display_title="Plan",
        title="T",
        request_id="r",
        status="answered",
        deadline_at=None,
        query="q",
        branches=(),
        selected_option_ids=("approve",),
        feedback=None,
        attachments=(),
        error_count=0,
        bundle_path=None,
        unavailable_reason=None,
        plan_decision_definitions=definitions,
        plan_decision_values={"grouping": "mode"},
    )
    assert _plan_decisions_block(answered) is not None


def test_gate_card_pending_toggles_use_checkboxes() -> None:
    from rich.console import Console

    from sase.ace.tui.modals.notification_modal_gate import _plan_decisions_block
    from sase.notification_gates.summary import GateSummary

    definitions = (
        {
            "id": "grouping",
            "kind": "choice",
            "default": "pane",
            "effective_default": "pane",
        },
        {
            "id": "tui_note",
            "kind": "toggle",
            "default": True,
            "effective_default": False,
        },
    )
    pending = GateSummary(
        kind="plan",
        display_title="Plan",
        title="T",
        request_id="r",
        status="pending",
        deadline_at=None,
        query="q",
        branches=(),
        selected_option_ids=(),
        feedback=None,
        attachments=(),
        error_count=0,
        bundle_path=None,
        unavailable_reason=None,
        plan_decision_definitions=definitions,
        plan_decision_values={"grouping": "pane", "tui_note": False},
    )
    block = _plan_decisions_block(pending)
    assert block is not None
    console = Console(width=80, record=True)
    console.print(block)
    out = console.export_text()
    assert "◉ grouping" in out
    assert "⬜ tui_note" in out
    answered_toggle = GateSummary(
        kind="plan",
        display_title="Plan",
        title="T",
        request_id="r",
        status="answered",
        deadline_at=None,
        query="q",
        branches=(),
        selected_option_ids=("approve",),
        feedback=None,
        attachments=(),
        error_count=0,
        bundle_path=None,
        unavailable_reason=None,
        plan_decision_definitions=definitions,
        plan_decision_values={"grouping": "mode", "tui_note": True},
    )
    block2 = _plan_decisions_block(answered_toggle)
    assert block2 is not None
    console2 = Console(width=80, record=True)
    console2.print(block2)
    out2 = console2.export_text()
    assert "tui_note: yes" in out2
    assert "grouping: mode" in out2
