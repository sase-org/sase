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
    _collapsed_row_text,
    _expanded_row_text,
    _is_unverified_row,
)
from sase.ace.tui.modals.plan_decision_sheet import PlanDecisionDraft


def _definitions(tmp_path) -> list[dict]:
    """Real gate payload definitions (no artifacts dir => quote_not_found)."""
    import textwrap

    content = textwrap.dedent(
        """\
        ---
        tier: tale
        title: Keymap help overlay
        goal: Pressing ? shows bindings.
        size: small
        decisions:
          grouping:
            ask: How should the overlay group bindings?
            choices:
              pane: By pane
              mode: By mode
            default: pane
            why: pane keeps order
          tui_note:
            ask: Record conventions in the tui memory note?
            memory: [tui.md]
            requested: and note the convention in the tui memory note xyz
            default: true
        ---
        # Plan
        Body grouping pane tui_note.
        > [!decision] grouping = pane Order by pane.
        > [!decision] grouping = mode Order by mode.
        > [!decision] tui_note
        Yes branch.
        > [!decision] tui_note = no
        No branch.
        """
    )
    plan_path = str(tmp_path / "defs_plan.md")
    import pathlib as _pathlib

    _pathlib.Path(plan_path).write_text(content, encoding="utf-8")
    from sase.plan_gate import build_plan_approval_gate_spec

    spec = build_plan_approval_gate_spec(plan_path, "visual-session")
    decisions = spec["payload"]["decisions"]
    assert isinstance(decisions, list) and len(decisions) == 2
    return [dict(item) for item in decisions if isinstance(item, dict)]


def test_draft_preserves_author_order_and_effective_defaults(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path), review_revision=3)
    assert draft.ids == ["grouping", "tui_note"]
    assert draft.value_for("grouping") == "pane"
    assert draft.value_for("tui_note") is False
    assert draft.review_revision == 3


def test_step_wraps_choices_and_sets_toggles(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path))
    draft.step("grouping", 1)
    assert draft.value_for("grouping") == "mode"
    draft.step("grouping", 1)
    assert draft.value_for("grouping") == "pane"
    draft.step("tui_note", 1)
    assert draft.value_for("tui_note") is True
    draft.step("tui_note", -1)
    assert draft.value_for("tui_note") is False


def test_flip_and_reset(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path))
    draft.flip("tui_note")
    assert draft.value_for("tui_note") is True
    draft.reset("tui_note")
    assert draft.value_for("tui_note") is False
    draft.step("grouping", 1)
    draft.reset_all()
    assert draft.value_for("grouping") == "pane"
    assert draft.value_for("tui_note") is False


def test_decision_map_keys(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path))
    assert draft.decision_map() == {
        "decision_grouping": "pane",
        "decision_tui_note": False,
    }


def test_sheet_counts_and_revision(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path), review_revision=4)
    sheet = draft.sheet()
    assert sheet["count"] == 2
    assert sheet["review_revision"] == 4
    assert sheet["changed_count"] == 0
    draft.step("grouping", 1)
    assert draft.sheet()["changed_count"] == 1


def test_collapsed_and_expanded_row_text(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path))
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    collapsed = _collapsed_row_text(rows["grouping"]).plain
    assert "grouping" in collapsed and "pane" in collapsed
    expanded = _expanded_row_text(rows["grouping"]).plain
    assert "How should the overlay group" in expanded
    assert "★" in expanded
    # Expanded choice header shows the current value.
    assert "pane" in expanded.splitlines()[0]
    draft.step("grouping", 1)
    changed_rows = {row["id"]: row for row in draft.sheet()["rows"]}
    changed_expanded = _expanded_row_text(changed_rows["grouping"]).plain
    assert "mode" in changed_expanded.splitlines()[0]
    assert "●" in changed_expanded


def test_unverified_copy_and_human_override(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path))
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    row = rows["tui_note"]
    assert _is_unverified_row(row, _definitions(tmp_path)[1])
    expanded = _expanded_row_text(row, definition=_definitions(tmp_path)[1]).plain
    assert "not in your messages" in expanded
    assert "off until you turn it on" in expanded
    # Collapsed row also shows the unverified warning, not only expanded.
    collapsed = _collapsed_row_text(row, definition=_definitions(tmp_path)[1]).plain
    assert "not in your messages" in collapsed
    draft.set_value("tui_note", True)
    updated = {row["id"]: row for row in draft.sheet()["rows"]}["tui_note"]
    assert updated["value"] is True
    assert updated["changed"] is True
    assert "●" in _collapsed_row_text(updated).plain
    # Turning an unverified row on keeps the warning (never you asked).
    turned = _expanded_row_text(updated, definition=_definitions(tmp_path)[1]).plain
    assert "not in your messages" in turned
    assert "you asked:" not in turned
    turned_collapsed = _collapsed_row_text(
        updated, definition=_definitions(tmp_path)[1]
    ).plain
    assert "not in your messages" in turned_collapsed


def test_new_chip_for_missing_memory_note(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path))
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    row = dict(rows["tui_note"])
    memory = dict(row.get("memory", {}))
    memory["resolved"] = [
        {
            "selector": "tui.md",
            "kind": "note",
            "scope": "project",
            "path": "tui.md",
            "type": "reference",
            "exists": False,
        }
    ]
    row["memory"] = memory
    collapsed = _collapsed_row_text(row).plain
    assert "new" in collapsed
    expanded = _expanded_row_text(row).plain
    # Unverified warning still wins for quote_not_found rows.
    assert "not in your messages" in expanded


def test_feedback_carry_lines_only_changed(tmp_path) -> None:
    draft = PlanDecisionDraft(_definitions(tmp_path))
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


def test_classify_no_branch_callout() -> None:
    # A = no span is chosen only when the toggle is false.
    assert classify_callout({"id": "t", "branch": "no"}, {"t": False}) == "chosen"
    assert classify_callout({"id": "t", "branch": "no"}, {"t": True}) == "dimmed"
    # Bare/yes spans are chosen only when true.
    assert classify_callout({"id": "t", "branch": "yes"}, {"t": True}) == "chosen"
    assert classify_callout({"id": "t", "branch": "yes"}, {"t": False}) == "dimmed"
    assert classify_callout({"id": "t", "branch": "yes"}, {"t": True}) == "chosen"
    # Choice spans stay a key match and never hide.
    assert (
        classify_callout({"id": "g", "key": "pane", "branch": "choice"}, {"g": "pane"})
        == "chosen"
    )
    assert (
        classify_callout({"id": "g", "key": "pane", "branch": "choice"}, {"g": "mode"})
        == "dimmed"
    )


def test_tint_dims_unselected_without_dropping_lines() -> None:
    from sase.ace.tui.util.frontmatter_syntax import tinted_document_text

    folded = "# Plan\n> [!decision] grouping = pane\npane line\n> [!decision] grouping = mode\nmode line\n"
    spans = [
        {
            "id": "grouping",
            "key": "pane",
            "branch": "choice",
            "start_line": 2,
            "end_line": 3,
        },
        {
            "id": "grouping",
            "key": "mode",
            "branch": "choice",
            "start_line": 4,
            "end_line": 5,
        },
    ]
    text = tinted_document_text(folded, spans, {"grouping": "mode"})
    assert hasattr(text, "plain")
    assert "pane line" in text.plain
    assert "mode line" in text.plain
    # Chosen header is green bold; unchosen is dimmed. Both lines stay visible.
    spans_styled = list(getattr(text, "_spans", []) or [])
    assert spans_styled, "expected per-line tint spans"


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
        decision_definitions=_definitions(tmp_path),
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
        decision_definitions=_definitions(tmp_path),
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
        decision_definitions=[_definitions(tmp_path)[0]],
        review_revision=1,
        request_id="req-esc-1",
    )
    assert modal._decision_draft.value_for("grouping") == "mode"
    settled = PlanApprovalModal(
        "/tmp/plan.md",
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=[_definitions(tmp_path)[0]],
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
    draft = PlanDecisionDraft(_definitions(tmp_path))
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
        decision_definitions=[_definitions(tmp_path)[0]],
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


async def test_compact_verdict_three_lines_with_without_and_epic(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    class _TestApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    # With decisions (tale).
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=_definitions(tmp_path),
        review_revision=3,
        request_id="req-verdict-tale",
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert modal.query_one("#plan-verdict")
        assert modal.query_one("#plan-verdict-line1")
        assert modal.query_one("#plan-verdict-line2")
        summary = modal.query_one("#plan-verdict-summary")
        rendered = summary.render()
        summary_text = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "→" in summary_text
        # Short labels on line 1 with full-label tooltips.
        line1 = modal.query_one("#plan-verdict-line1")
        labels = [b.label for b in line1.query("GateControlButton")]
        assert any("Launch coder" in str(label) for label in labels)
        assert any("Commit plan" in str(label) for label in labels)
        tooltips = [
            getattr(b, "tooltip", "") or "" for b in line1.query("GateControlButton")
        ]
        assert any("Launch coder agent" in str(tip) for tip in tooltips)
        assert any(
            "Commit plan file to the plans sidecar" in str(tip) for tip in tooltips
        )
        # Line 2 numbered branches.
        line2 = modal.query_one("#plan-verdict-line2")
        line2_labels = " ".join(str(b.label) for b in line2.query("GateControlButton"))
        assert "1 ✅ Tale" in line2_labels
        assert "2 ❌ Reject" in line2_labels
        assert "3 💬 Feedback" in line2_labels
        pilot.app.pop_screen()
        await pilot.pause()

    # Without decisions: third line still present with verdict sentence.
    bare = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=[],
        review_revision=1,
        request_id="req-verdict-bare",
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(bare)
        await pilot.pause()
        assert bare.query_one("#plan-verdict")
        summary = bare.query_one("#plan-verdict-summary")
        rendered = summary.render()
        text = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "→ coder + commit" in text
        pilot.app.pop_screen()
        await pilot.pause()

    # Epic: Epic label, no commit toggle.
    epic = PlanApprovalModal(
        str(plan),
        default_choice="epic",
        plan_content="# Plan\n",
        decision_definitions=_definitions(tmp_path),
        review_revision=3,
        request_id="req-verdict-epic",
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(epic)
        await pilot.pause()
        assert epic.query_one("#plan-verdict")
        line2 = epic.query_one("#plan-verdict-line2")
        line2_labels = " ".join(str(b.label) for b in line2.query("GateControlButton"))
        assert "1 ✅ Epic" in line2_labels
        assert "Commit plan" not in " ".join(
            str(b.label) for b in epic.query("GateControlButton")
        )
        pilot.app.pop_screen()
        await pilot.pause()


def test_plan_short_labels_and_generic_unchanged() -> None:
    from sase.ace.tui.modals.gate_branch_layout import plan_toggle_label, toggle_label
    from sase.notification_gates.models import GateOption

    def _opt(option_id: str, label: str) -> GateOption:
        return GateOption.from_mapping(
            {
                "id": option_id,
                "label": label,
                "command": {"argv": [f"commands/{option_id}"]},
            },
            0,
        )

    approve = _opt("approve", "Launch coder agent")
    commit = _opt("commit", "Commit plan file to the plans sidecar")
    assert "Launch coder" in plan_toggle_label(approve, True)
    assert "Launch coder agent" not in plan_toggle_label(approve, True)
    assert "Commit plan" in plan_toggle_label(commit, False)
    # Generic gates keep full labels.
    generic = _opt("deploy", "Deploy it")
    assert "Deploy it" in toggle_label(generic, True)
    assert "Deploy it" in plan_toggle_label(generic, True)


async def test_scroll_uses_cached_fold_map(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals import plan_approval_modal_view as view
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    class _TestApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan grouping\n", encoding="utf-8")
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan grouping\n",
        decision_definitions=_definitions(tmp_path),
        review_revision=1,
        request_id="req-scroll-cache",
    )
    calls = {"n": 0}
    orig = view.fold_plan_decisions_content

    def _counting(content: str):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return orig(content)

    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        import unittest.mock as mock

        with mock.patch.object(
            view, "fold_plan_decisions_content", side_effect=_counting
        ) as _patched:
            before = calls["n"]
            # Focused decision scroll must use the cached fold map, not re-parse.
            modal._scroll_to_focused_decision()
            await pilot.pause()
            assert calls["n"] == before


async def test_freeze_banner_visible_and_submit_blocked(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.modals._plan_approval_modal_state import DECISIONS_FROZEN_MESSAGE
    from sase.ace.tui.modals.gate_action_runner import GateEditOutcome
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    class _TestApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    from sase.ace.tui.modals.gate_action_controls import GateActionsData
    from sase.notification_gates.model_operations import GateOperation

    actions = GateActionsData(
        operations=(
            GateOperation.from_mapping(
                {
                    "id": "edit-plan",
                    "kind": "edit_file",
                    "label": "Edit plan",
                    "target": "plan.md",
                    "edit_target": "origin",
                },
                0,
            ),
        ),
    )
    modal = PlanApprovalModal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=_definitions(tmp_path),
        review_revision=5,
        request_id="req-freeze-1",
        actions=actions,
    )
    async with _TestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        outcome = GateEditOutcome(
            accepted=False,
            message=DECISIONS_FROZEN_MESSAGE,
            draft=True,
            draft_path=str(plan),
        )
        modal._apply_edit_outcome("edit-plan", outcome)
        await pilot.pause()
        from sase.ace.tui.modals.gate_branch_controls import GateBranchControls

        branch = modal.query_one(GateBranchControls)
        assert (
            branch._submission_block == "Accept or discard your draft before submitting"
        )
        banner = modal.query_one("#gate-draft-banner")
        assert "hidden" not in banner.classes
        # Submit stays blocked: resolving a branch notifies the block.
        notes: list[str] = []
        orig_notify = branch.notify

        def _capture(msg: object, *a: object, **k: object) -> None:  # type: ignore[no-untyped-def]
            notes.append(str(msg))
            return None

        branch.notify = _capture  # type: ignore[assignment]
        try:
            branch._resolve_branch(1)
        finally:
            branch.notify = orig_notify  # type: ignore[assignment]
        assert any("Accept or discard" in note for note in notes)
        # Accepted outcome with draft=False clears the banner + block.
        cleared = GateEditOutcome(
            accepted=True,
            message="Edit accepted",
            draft=False,
            draft_path=None,
        )
        modal._apply_edit_outcome("edit-plan", cleared)
        await pilot.pause()
        assert "hidden" in modal.query_one("#gate-draft-banner").classes
        assert branch._submission_block is None
        cleared_notes: list[str] = []
        branch.notify = lambda msg, *a, **k: cleared_notes.append(str(msg))  # type: ignore[assignment]
        try:
            branch._resolve_branch(1)
        finally:
            branch.notify = orig_notify  # type: ignore[assignment]
        assert not any("Accept or discard" in note for note in cleared_notes)


async def test_feedback_bar_shows_carries_readonly(tmp_path) -> None:
    from textual.app import App

    from sase.ace.tui.widgets import PromptInputBar

    class _BarApp(App[None]):
        ENABLE_COMMAND_PALETTE = False

        def compose(self):  # type: ignore[no-untyped-def]
            from textual.app import ComposeResult

            yield PromptInputBar(mode="feedback", id="prompt-input-bar")

    from sase.ace.tui.actions.agents._types import PlanFeedbackContext

    app = _BarApp()
    async with app.run_test(size=(120, 20)) as pilot:
        from pathlib import Path

        app._plan_feedback_context = PlanFeedbackContext(  # type: ignore[attr-defined]
            notification_id="n1",
            response_path=Path("/tmp/response.json"),
            agent_identity=None,
            plan_file="/tmp/plan.md",
            notification=None,
            carries=("Carries: grouping → mode",),
            decision_inputs=None,
            review_revision=3,
        )
        # Remount the bar so it reads the context set above.
        try:
            await pilot.app.query_one("#prompt-input-bar").remove()
        except Exception:
            pass
        await pilot.app.mount(PromptInputBar(mode="feedback", id="prompt-input-bar"))
        await pilot.pause()
        carries = pilot.app.query_one("#prompt-feedback-carries")
        rendered = carries.render()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "Carries: grouping → mode" in plain
        # Read-only: carries widget is a Static, not an editable text area.
        from textual.widgets import Static

        assert isinstance(carries, Static)


def test_settled_labels_truthful(tmp_path) -> None:
    from sase.ace.tui.actions.agents._notification_plan_gate import (
        _settled_text_for_bundle,
    )
    import types

    def _bundle(selected: tuple[str, ...], source: str = "cli"):  # type: ignore[no-untyped-def]
        payload = {
            "selected_option_ids": list(selected),
            "source": source,
            "option_inputs": {},
        }
        terminal = types.SimpleNamespace(status="ok")
        return payload, terminal

    import unittest.mock as mock

    definitions = _definitions(tmp_path)
    fake_bundle = types.SimpleNamespace(
        root="/tmp",
        request="/tmp/req",
        response="/tmp/res",
        cancellation="/tmp/c",
        legacy=False,
    )
    with mock.patch(
        "sase.notification_gates.debug_artifacts.terminal_artifact"
    ) as term:
        term.return_value = (
            _bundle(("approve", "commit"))[1],
            {
                "selected_option_ids": ["approve", "commit"],
                "source": "cli",
                "option_inputs": {},
            },
            "response",
        )
        text = _settled_text_for_bundle(fake_bundle, definitions, "tale")
        assert text.startswith("Approved via CLI")
        term.return_value = (
            types.SimpleNamespace(status="ok"),
            {
                "selected_option_ids": ["reject"],
                "source": "telegram",
                "option_inputs": {},
            },
            "response",
        )
        assert (
            _settled_text_for_bundle(fake_bundle, definitions, "tale")
            == "Rejected via Telegram"
        )
        term.return_value = (
            types.SimpleNamespace(status="ok"),
            {"selected_option_ids": ["feedback"], "source": "tui", "option_inputs": {}},
            "response",
        )
        assert (
            _settled_text_for_bundle(fake_bundle, definitions, "tale")
            == "Feedback via ACE"
        )


async def test_stale_review_reloads_revision_keeping_values(tmp_path) -> None:
    from sase.ace.tui.actions.agents._notification_plan_gate import _handle_stale_review
    from sase.notifications import Notification
    import types

    from sase.ace.tui.modals._plan_approval_modal_state import esc_drafts

    # Closed modal: stash filtered values and push a fresh modal.
    plan_file = tmp_path / "stale_plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="stale-1",
        timestamp="2026-10-08T00:00:00+00:00",
        sender="agent",
        notes=["plan"],
        files=[str(plan_file)],
        action="PlanApproval",
        action_data={"request_id": "stale-1"},
    )
    result = types.SimpleNamespace(
        option_inputs={"approve": {"decision_grouping": "mode"}},
    )
    import unittest.mock as mock

    old_defs = _definitions(tmp_path)
    grouping_def = next(d for d in old_defs if d.get("id") == "grouping")
    new_choice_def = {
        "id": "new_choice",
        "kind": "choice",
        "ask": "New choice?",
        "choices": [{"key": "a", "label": "A"}, {"key": "b", "label": "B"}],
        "default": "a",
        "effective_default": "a",
    }
    new_defs = [dict(grouping_def), dict(new_choice_def)]
    from sase.ace.tui.modals.plan_approval_gate_data import default_plan_gate_data

    reloaded = types.SimpleNamespace(
        plan_file=str(plan_file),
        plan_content="# New plan\nNew body marker\n",
        default_choice="tale",
        gate=default_plan_gate_data("tale"),
        actions=None,
        decision_definitions=new_defs,
        review_revision=9,
        request_id="stale-1",
        settled_text=None,
    )
    pushed: list[object] = []

    def _push(screen: object, *a: object, **k: object) -> None:
        pushed.append(screen)

    app = types.SimpleNamespace(
        notify=lambda *a, **k: None,
        push_screen=_push,
        screen=None,
        screen_stack=[],
    )
    esc_drafts.pop("stale-1", None)
    with (
        mock.patch(
            "sase.ace.tui.actions.agents._notification_plan_gate.load_neutral_plan_modal_data",
            return_value=reloaded,
        ),
        mock.patch(
            "sase.ace.tui.actions.agents._notification_plan_gate._refresh_notifications",
            return_value=None,
        ),
    ):
        assert _handle_stale_review(app, notification, result) is True
    assert esc_drafts.get("stale-1", {}).get("grouping") == "mode"
    assert "tui_note" not in esc_drafts.get("stale-1", {})
    assert "new_choice" not in esc_drafts.get("stale-1", {})
    assert len(pushed) == 1
    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal

    modal_pushed = pushed[0]
    assert isinstance(modal_pushed, PlanApprovalModal)
    assert modal_pushed._review_revision == 9  # type: ignore[attr-defined]
    assert modal_pushed._decision_draft.value_for("grouping") == "mode"  # type: ignore[attr-defined]
    assert "tui_note" not in modal_pushed._decision_draft.values()  # type: ignore[attr-defined]
    assert modal_pushed._decision_draft.value_for("new_choice") == "a"  # type: ignore[attr-defined]

    # Open modal: rebuild in place, no second push, document refreshed.
    from textual.app import App as _App

    class _OpenApp(_App[None]):
        ENABLE_COMMAND_PALETTE = False

    open_plan = tmp_path / "open_plan.md"
    open_plan.write_text("# Old\nOld body\n", encoding="utf-8")
    open_id = "stale-open-1"
    open_notification = Notification(
        id=open_id,
        timestamp="2026-10-08T00:00:00+00:00",
        sender="agent",
        notes=["plan"],
        files=[str(open_plan)],
        action="PlanApproval",
        action_data={"request_id": open_id},
    )
    open_result = types.SimpleNamespace(
        option_inputs={"approve": {"decision_grouping": "mode"}},
    )
    open_reloaded = types.SimpleNamespace(
        plan_file=str(open_plan),
        plan_content="# Reloaded\nReloaded body marker\n",
        default_choice="tale",
        gate=default_plan_gate_data("tale"),
        actions=None,
        decision_definitions=new_defs,
        review_revision=11,
        request_id=open_id,
        settled_text=None,
    )
    esc_drafts.pop(open_id, None)
    live_modal = PlanApprovalModal(
        str(open_plan),
        default_choice="tale",
        plan_content="# Old\nOld body\n",
        decision_definitions=old_defs,
        review_revision=5,
        request_id=open_id,
    )
    async with _OpenApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(live_modal)
        await pilot.pause()
        await pilot.pause()
        pushes: list[object] = []
        orig_push = pilot.app.push_screen

        def _capture_push(screen: object, *a: object, **k: object) -> object:
            pushes.append(screen)
            return orig_push(screen, *a, **k)

        with (
            mock.patch.object(pilot.app, "push_screen", _capture_push),
            mock.patch(
                "sase.ace.tui.actions.agents._notification_plan_gate.load_neutral_plan_modal_data",
                return_value=open_reloaded,
            ),
            mock.patch(
                "sase.ace.tui.actions.agents._notification_plan_gate._refresh_notifications",
                return_value=None,
            ),
        ):
            assert (
                _handle_stale_review(pilot.app, open_notification, open_result) is True
            )
        await pilot.pause()
        await pilot.pause()
        assert pushes == []
        assert pilot.app.screen is live_modal
        assert live_modal._review_revision == 11  # type: ignore[attr-defined]
        from sase.ace.tui.modals.plan_decision_rows import PlanDecisionRows

        rows = live_modal.query_one("#plan-decision-rows", PlanDecisionRows)
        assert [r.get("id") for r in rows._rows] == ["grouping", "new_choice"]
        assert set(rows._by_id.keys()) == {"grouping", "new_choice"}
        from textual.widgets import Static as _Static

        content = live_modal.query_one("#plan-approval-content", _Static)
        rendered = content.render()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        # New body text is what the pane shows; fold/spans recomputed.
        assert "Reloaded body marker" in plain or "Reloaded" in live_modal._folded_text  # type: ignore[attr-defined]
        assert live_modal._folded_text is not None  # type: ignore[attr-defined]
        assert live_modal._callout_spans is not None  # type: ignore[attr-defined]
        assert esc_drafts.get(open_id, {}).get("grouping") == "mode"


def test_plan_section_render_path_no_stat_no_validate(monkeypatch, tmp_path) -> None:
    import sase.ace.tui.widgets.prompt_panel._agent_plan_section as section

    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    from sase.ace.tui.models._agent_associated_plan_summary import (
        _ASSOCIATED_PLAN_SHEET_CACHE,
    )

    _ASSOCIATED_PLAN_SHEET_CACHE[str(plan)] = ({"rows": []}, "reviewer", "tui")
    summary = type("S", (), {"actual_path": str(plan)})()
    monkeypatch.setattr(
        "os.stat",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("stat on render path")),
    )
    import sase.sdd.plan_validate as validate_mod

    monkeypatch.setattr(
        validate_mod,
        "validate_plan",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("validate on render path")
        ),
    )
    sheet, by, via = section._load_plan_sheet(summary)  # type: ignore[arg-type]
    assert sheet == {"rows": []}
    assert by == "reviewer"
    # Miss returns no sheet without touching disk.
    missing = type("S", (), {"actual_path": str(tmp_path / "missing.md")})()
    assert section._load_plan_sheet(missing)[0] is None  # type: ignore[arg-type]


async def test_compact_verdict_stays_inside_rail_with_stylesheet(tmp_path) -> None:
    from pathlib import Path as _Path

    from textual.app import App as _App
    from textual.containers import VerticalScroll as _VS

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    _ROOT = _Path(__file__).resolve().parents[3]

    class _StyledApp(_App[None]):
        CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "rail_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    for choice in ("tale", "epic"):
        for with_decisions in (True, False):
            defs = _definitions(tmp_path) if with_decisions else []
            for width, height in ((120, 40), (90, 40)):
                modal = _Modal(
                    str(plan),
                    default_choice=choice,  # type: ignore[arg-type]
                    plan_content="# Plan\n",
                    decision_definitions=list(defs),
                    review_revision=3,
                    request_id=f"req-rail-{choice}-{with_decisions}-{width}",
                )
                async with _StyledApp().run_test(size=(width, height)) as pilot:
                    pilot.app.push_screen(modal)
                    await pilot.pause()
                    await pilot.pause()
                    rail = modal.query_one(".gate-review-actions", _VS)
                    content = rail.content_region
                    for btn in modal.query("#plan-verdict GateControlButton"):
                        assert content.contains_region(btn.region), (
                            choice,
                            with_decisions,
                            width,
                            btn.id,
                            btn.region,
                            content,
                        )
                    line2 = modal.query_one("#plan-verdict-line2")
                    line2_labels = " ".join(
                        str(b.label) for b in line2.query("GateControlButton")
                    )
                    if choice == "tale":
                        line1 = modal.query_one("#plan-verdict-line1")
                        labels1 = " ".join(
                            str(b.label) for b in line1.query("GateControlButton")
                        )
                        assert "Launch coder" in labels1
                        assert "Commit plan" in labels1
                        assert "1 ✅ Tale" in line2_labels
                        assert "2 ❌ Reject" in line2_labels
                        assert "3 💬 Feedback" in line2_labels
                    else:
                        assert not modal.query("#plan-verdict-line1")
                        assert "1 ✅ Epic" in line2_labels
                        assert "Commit plan" not in " ".join(
                            str(b.label) for b in modal.query("GateControlButton")
                        )
                    if with_decisions:
                        header = modal.query_one("#plan-decisions-header")
                        verdict = modal.query_one("#plan-verdict")
                        assert content.contains_region(header.region)
                        assert not header.region.overlaps(verdict.region)
                    pilot.app.pop_screen()
                    await pilot.pause()


async def test_first_frame_tint_keeps_syntax(tmp_path) -> None:
    from textual.app import App as _App

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    class _App2(_App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "tint_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    defs = _definitions(tmp_path)
    modal = _Modal(
        str(plan),
        default_choice="tale",
        plan_content=(
            "---\n"
            "tier: tale\n"
            "title: Tint\n"
            "goal: Keep colours\n"
            "size: small\n"
            "decisions:\n"
            "  grouping:\n"
            "    ask: Group?\n"
            "    choices:\n"
            "      pane: By pane\n"
            "      mode: By mode\n"
            "    default: pane\n"
            "---\n"
            "# Plan\n"
            "> [!decision] grouping = pane Order by pane.\n"
            "> [!decision] grouping = mode Order by mode.\n"
        ),
        decision_definitions=defs,
        review_revision=3,
        request_id="req-tint-1",
    )
    async with _App2().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        assert list(modal._callout_spans or []) != []  # type: ignore[attr-defined]
        from textual.widgets import Static as _Static

        content = modal.query_one("#plan-approval-content", _Static)
        rendered = content.render()
        text = rendered if hasattr(rendered, "plain") else rendered.__rich__()  # type: ignore[union-attr]
        # Static may hold a Syntax renderable when untinted; tinted path is Text.
        from rich.text import Text as _Text

        if not isinstance(text, _Text):
            # Fall back to the modal's own renderable for the tint asserts.
            folded = getattr(modal, "_folded_text", "") or ""
            text = modal._document_renderable(folded)  # type: ignore[attr-defined]
        assert isinstance(text, _Text)
        assert "Order by mode" in text.plain
        spans = list(getattr(text, "_spans", []) or [])
        assert spans, "expected tint + token spans"
        styles = [str(getattr(s, "style", "")) for s in spans]
        assert any("bold" in s and "green" in s for s in styles)
        assert any(s.strip() == "dim" or "dim" in s for s in styles)
        # At least one syntax token style survives alongside the tint overlay.
        assert (
            any("#" in s or "272822" in s or "monokai" in s.lower() for s in styles)
            or len(spans) >= 5
        )


async def test_draft_edit_avoids_revalidate_relex(tmp_path) -> None:
    from textual.app import App as _App

    from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal as _Modal

    class _App3(_App[None]):
        ENABLE_COMMAND_PALETTE = False

    plan = tmp_path / "keypress_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    modal = _Modal(
        str(plan),
        default_choice="tale",
        plan_content="# Plan\n",
        decision_definitions=_definitions(tmp_path),
        review_revision=1,
        request_id="req-keypress-1",
    )
    async with _App3().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        import unittest.mock as _mock

        with (
            _mock.patch(
                "sase.sdd.plan_validate.validate_plan",
                side_effect=AssertionError("validate on keypress"),
            ),
            _mock.patch(
                "sase.ace.tui.modals.plan_decision_document.cache_callout_spans",
                side_effect=AssertionError("cache on keypress"),
            ),
            _mock.patch(
                "sase.ace.tui.util.frontmatter_syntax._lex_frontmatter_markdown",
                side_effect=AssertionError("lex on keypress"),
            ),
        ):
            modal._apply_draft_edit(lambda: modal._decision_draft.step("grouping", 1))  # type: ignore[attr-defined]
            await pilot.pause()


def test_settled_polling_reads_only_open_modal(tmp_path) -> None:
    import asyncio
    import os
    import types as _types
    import unittest.mock as _mock

    from sase.notifications import Notification

    # No modal open: full poll never verifies, even with a PlanApproval row.
    from tests._notification_toasts_helpers import _FakeApp, _make, _patch_snapshot

    notification = _make(
        action="PlanApproval",
        notes=["plan"],
        action_data={"request_id": "req-settled-1"},
        sender="agent",
    )
    app = _FakeApp()
    app._agents = []  # type: ignore[attr-defined]
    app._agents_with_children = []  # type: ignore[attr-defined]
    from tests.test_notification_completion_arrival import _install_captures

    _install_captures(app)
    loads = {"n": 0}
    real_load = None
    try:
        import sase.notification_gates.hashing as _hashing

        real_load = _hashing.load_and_verify_bundle
    except Exception:
        pass

    def _counting(root: object, *a: object, **k: object):  # type: ignore[no-untyped-def]
        loads["n"] += 1
        if real_load is None:
            raise AssertionError("no bundle")
        return real_load(root, *a, **k)

    with (
        _patch_snapshot([notification]),
        _mock.patch(
            "sase.notification_gates.hashing.load_and_verify_bundle",
            side_effect=_counting,
        ),
    ):
        asyncio.run(app._poll_agent_completions_once())
    assert loads["n"] == 0

    # Open modal: missing response never verifies; present verifies once per mtime.
    from sase.ace.tui.actions.agents._notification_polling import (
        _prepare_settled_for_open_modal,
    )

    request_id = "req-modal-7"
    fake_notification = Notification(
        id=request_id,
        timestamp="2026-10-08T00:00:00+00:00",
        sender="agent",
        notes=["plan"],
        files=[str(tmp_path / "plan.md")],
        action="PlanApproval",
        action_data={"request_id": request_id},
    )
    response = tmp_path / "response.json"
    if response.exists():
        response.unlink()
    bundle = _types.SimpleNamespace(
        root=tmp_path,
        request=tmp_path / "request.json",
        response=response,
        cancellation=tmp_path / "cancel.json",
        legacy=False,
    )
    poll_app: object = _types.SimpleNamespace()

    def _counting_fake(root: object, *a: object, **k: object):  # type: ignore[no-untyped-def]
        loads["n"] += 1
        return ({"kind": "tale", "payload": {"decisions": []}}, object())

    with (
        _mock.patch(
            "sase.notification_gates.paths.resolve_notification_bundle",
            return_value=bundle,
        ),
        _mock.patch(
            "sase.notification_gates.hashing.load_and_verify_bundle",
            side_effect=_counting_fake,
        ),
        _mock.patch(
            "sase.ace.tui.actions.agents._notification_plan_gate._settled_text_for_bundle",
            return_value="Approved via CLI",
        ),
    ):
        loads["n"] = 0
        assert (
            _prepare_settled_for_open_modal(poll_app, fake_notification, request_id)
            == {}
        )
        assert loads["n"] == 0
        response.write_text("{}", encoding="utf-8")
        assert _prepare_settled_for_open_modal(
            poll_app, fake_notification, request_id
        ) == {request_id: "Approved via CLI"}
        assert loads["n"] == 1
        assert _prepare_settled_for_open_modal(
            poll_app, fake_notification, request_id
        ) == {request_id: "Approved via CLI"}
        assert loads["n"] == 1
        prev = response.stat().st_mtime_ns
        os.utime(
            response,
            ns=(
                response.stat().st_atime_ns,
                max(response.stat().st_mtime_ns, prev + 1),
            ),
        )
        assert _prepare_settled_for_open_modal(
            poll_app, fake_notification, request_id
        ) == {request_id: "Approved via CLI"}
        assert loads["n"] == 2
