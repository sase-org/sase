"""Unit coverage for ACE Plan Decisions (sase-1hi.6)."""

from __future__ import annotations

from sase.ace.tui.modals.notification_modal_options import (
    _plan_decisions_inbox_suffix,
)
from sase.ace.tui.modals.plan_approval_decisions import build_decision_option_inputs
from sase.ace.tui.modals.plan_decision_document import (
    classify_callout,
    fold_plan_decisions_content,
    scroll_target_for_decision,
)
from sase.ace.tui.modals.plan_decision_rows import (
    collapsed_row_text,
    expanded_row_text,
    is_unverified_row,
)
from sase.ace.tui.modals.plan_decision_sheet import PlanDecisionDraft


def _definitions() -> list[dict]:
    return [
        {
            "id": "grouping",
            "kind": "choice",
            "ask": "How should the overlay group bindings?",
            "choices": [
                {"key": "pane", "label": "By pane"},
                {"key": "mode", "label": "By mode"},
            ],
            "default": "pane",
            "effective_default": "pane",
        },
        {
            "id": "tui_note",
            "kind": "toggle",
            "ask": "Record conventions in the tui memory note?",
            "default": True,
            "effective_default": False,
            "memory": {"selectors": ["tui.md"], "resolved": [{"type": "reference"}]},
            "provenance": "quote_not_found",
            "requested": "and note the convention in the tui memory",
        },
    ]


def test_draft_preserves_author_order_and_effective_defaults() -> None:
    draft = PlanDecisionDraft(_definitions(), review_revision=3)
    assert draft.ids == ["grouping", "tui_note"]
    assert draft.value_for("grouping") == "pane"
    assert draft.value_for("tui_note") is False
    assert draft.review_revision == 3


def test_step_wraps_choices_and_sets_toggles() -> None:
    draft = PlanDecisionDraft(_definitions())
    draft.step("grouping", 1)
    assert draft.value_for("grouping") == "mode"
    draft.step("grouping", 1)
    assert draft.value_for("grouping") == "pane"
    draft.step("tui_note", 1)
    assert draft.value_for("tui_note") is True
    draft.step("tui_note", -1)
    assert draft.value_for("tui_note") is False


def test_flip_and_reset() -> None:
    draft = PlanDecisionDraft(_definitions())
    draft.flip("tui_note")
    assert draft.value_for("tui_note") is True
    draft.reset("tui_note")
    assert draft.value_for("tui_note") is False
    draft.step("grouping", 1)
    draft.reset_all()
    assert draft.value_for("grouping") == "pane"
    assert draft.value_for("tui_note") is False


def test_decision_map_keys() -> None:
    draft = PlanDecisionDraft(_definitions())
    assert draft.decision_map() == {
        "decision_grouping": "pane",
        "decision_tui_note": False,
    }


def test_sheet_counts_and_revision() -> None:
    draft = PlanDecisionDraft(_definitions(), review_revision=4)
    sheet = draft.sheet()
    assert sheet["count"] == 2
    assert sheet["review_revision"] == 4
    assert sheet["changed_count"] == 0
    draft.step("grouping", 1)
    assert draft.sheet()["changed_count"] == 1


def test_collapsed_and_expanded_row_text() -> None:
    draft = PlanDecisionDraft(_definitions())
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    collapsed = collapsed_row_text(rows["grouping"]).plain
    assert "grouping" in collapsed and "pane" in collapsed
    expanded = expanded_row_text(rows["grouping"]).plain
    assert "How should the overlay group" in expanded
    assert "★" in expanded


def test_unverified_copy_and_human_override() -> None:
    draft = PlanDecisionDraft(_definitions())
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    row = rows["tui_note"]
    assert is_unverified_row(row, _definitions()[1])
    expanded = expanded_row_text(row, definition=_definitions()[1]).plain
    assert "not in your messages" in expanded
    assert "off until you turn it on" in expanded
    draft.set_value("tui_note", True)
    updated = {row["id"]: row for row in draft.sheet()["rows"]}["tui_note"]
    assert updated["value"] is True
    assert updated["changed"] is True
    assert "●" in collapsed_row_text(updated).plain


def test_feedback_carry_lines_only_changed() -> None:
    draft = PlanDecisionDraft(_definitions())
    assert draft.feedback_carry_lines() == []
    draft.step("grouping", 1)
    draft.set_value("tui_note", True)
    lines = draft.feedback_carry_lines()
    assert lines[0] == "Carries: grouping → mode"
    assert lines[1] == "Carries: tui_note → yes"


def test_fold_maps_many_yaml_lines_to_one() -> None:
    content = (
        "---\ntier: tale\ntitle: T\ngoal: G\nsize: small\n"
        "decisions:\n  grouping:\n    ask: Q?\n    default: pane\n---\n# Plan\n"
    )
    folded, raw_to_folded, line, count = fold_plan_decisions_content(content)
    assert count == 1
    assert line is not None
    assert "decisions: 1 · answered in the Decisions panel" in folded
    assert raw_to_folded[line + 1] == line


def test_scroll_prefers_callout_then_id_and_uses_fold() -> None:
    content = "---\ndecisions: 1 · answered in the Decisions panel\n---\n# grouping\n"
    callouts = [
        {
            "id": "grouping",
            "key": "pane",
            "branch": "pane",
            "start_line": 4,
            "end_line": 4,
        }
    ]
    assert scroll_target_for_decision("grouping", callouts, content, {3: 1}) == 1
    assert scroll_target_for_decision("grouping", [], content, None) is not None
    assert scroll_target_for_decision("missing", [], content, None) is None


def test_classify_callout_chosen_and_dimmed() -> None:
    assert classify_callout({"id": "g", "key": "pane"}, {"g": "pane"}) == "chosen"
    assert classify_callout({"id": "g", "key": "pane"}, {"g": "mode"}) == "dimmed"
    assert classify_callout({"id": "t"}, {"t": False}) == "dimmed"
    assert classify_callout({"id": "t"}, {"t": True}) == "chosen"


def test_inbox_suffix_counts_and_memory() -> None:
    assert _plan_decisions_inbox_suffix(["a", "2 decisions · 🧠 1"]) == " · ◉2 🧠"
    assert _plan_decisions_inbox_suffix(["a", "1 decision · 🧠 0"]) == " · ◉1"
    assert _plan_decisions_inbox_suffix(["a"]) == ""
    assert _plan_decisions_inbox_suffix(["a", "no decisions here"]) == ""


def test_decision_option_inputs_same_map_and_reject_omits() -> None:
    from sase.notification_gates.models import GateOption

    def option(option_id: str, decisions: bool) -> GateOption:
        props: dict = {"feedback": {"type": "string"}}
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

    from sase.notification_gates.branches import GateBranchData

    gate = GateBranchData(
        query="q",
        options=(
            option("approve", True),
            option("commit", True),
            option("reject", False),
        ),
        groups=(),
        branches=(("approve", "commit"), ("reject",)),
        primary_branch=("approve", "commit"),
    )
    decision_map = {"decision_grouping": "mode"}
    merged = build_decision_option_inputs(gate, ("approve", "commit"), decision_map)
    assert merged == {
        "approve": {"decision_grouping": "mode"},
        "commit": {"decision_grouping": "mode"},
    }
    assert build_decision_option_inputs(gate, ("reject",), decision_map) == {}


def test_receipt_has_no_gate_card_and_is_silent() -> None:
    from sase.notification_gates.summary import gate_summary_from_notification
    from sase.notifications import Notification

    notification = Notification(
        id="receipt-1",
        timestamp="2026-10-08T00:00:00+00:00",
        sender="plan-decisions",
        notes=["🤖 Auto-approved tale · x"],
        tags=["plan_decisions_receipt"],
        silent=True,
        action=None,
    )
    assert gate_summary_from_notification(notification) is None
    assert notification.silent is True


def test_custom_gate_decision_handlers_noop() -> None:
    from sase.ace.tui.modals.custom_gate_modal import CustomGateModal

    assert CustomGateModal.action_decision_next is not None
    assert CustomGateModal.action_decision_prev is not None
    assert CustomGateModal.action_decision_reset is not None
    assert CustomGateModal.action_decision_reset_all is not None


async def test_modal_decisions_focus_step_reset_and_enter(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals.plan_approval_modal import (
        _ESC_DRAFTS,
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
        decision_definitions=_definitions(),
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
        assert _ESC_DRAFTS.get("req-decisions-1", {}).get("grouping") == "mode"
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
        decision_definitions=_definitions(),
        review_revision=7,
        request_id="req-decisions-1",
    )
    assert reopened._decision_draft.value_for("grouping") == "pane"


def test_esc_store_freeze_and_settled() -> None:
    from sase.ace.tui.modals.plan_approval_modal import (
        _DECISIONS_FROZEN_MESSAGE,
        _ESC_DRAFTS,
        PlanApprovalModal,
    )

    assert "Decisions are fixed for this review" in _DECISIONS_FROZEN_MESSAGE
    _ESC_DRAFTS["req-esc-1"] = {"grouping": "mode"}
    modal = PlanApprovalModal(
        "/tmp/plan.md",
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=[_definitions()[0]],
        review_revision=1,
        request_id="req-esc-1",
    )
    assert modal._decision_draft.value_for("grouping") == "mode"
    settled = PlanApprovalModal(
        "/tmp/plan.md",
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=[_definitions()[0]],
        review_revision=1,
        request_id="req-settled-1",
        settled_text="Approved via CLI · → coder + commit",
    )
    before = settled._decision_draft.value_for("grouping")
    settled._apply_draft_edit(lambda: settled._decision_draft.step("grouping", 1))
    assert settled._decision_draft.value_for("grouping") == before


def test_toast_second_line_and_plan_document_sheet() -> None:
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
    draft = PlanDecisionDraft(_definitions())
    sheet = draft.sheet()
    with_sheet = plan_logical_text(summary, sheet=sheet)
    assert with_sheet.plain != without.plain
    assert "grouping" in with_sheet.plain


def test_modal_result_carries_displayed_revision_and_decisions() -> None:
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
        decision_definitions=[_definitions()[0]],
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
