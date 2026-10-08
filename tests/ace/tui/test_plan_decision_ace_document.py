"""Plan decision document helpers: folding, scrolling, callouts, and option inputs."""

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

__all__ = [
    "test_classify_callout_chosen_and_dimmed",
    "test_classify_no_branch_callout",
    "test_custom_gate_decision_handlers_noop",
    "test_decision_option_inputs_same_map_and_reject_omits",
    "test_fold_maps_many_yaml_lines_to_one",
    "test_inbox_suffix_counts_and_memory",
    "test_receipt_has_no_gate_card_and_is_silent",
    "test_scroll_prefers_callout_then_id_and_uses_fold",
    "test_tint_dims_unselected_without_dropping_lines",
]


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
