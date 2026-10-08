"""Plan decision draft model: ordering, stepping, rows, and carry lines."""

from __future__ import annotations

from sase.ace.tui.modals.plan_decision_rows import (
    _collapsed_row_text,
    _expanded_row_text,
    _is_unverified_row,
)
from sase.ace.tui.modals.plan_decision_sheet import PlanDecisionDraft
from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_collapsed_and_expanded_row_text",
    "test_decision_map_keys",
    "test_draft_preserves_author_order_and_effective_defaults",
    "test_feedback_carry_lines_only_changed",
    "test_flip_and_reset",
    "test_new_chip_for_missing_memory_note",
    "test_sheet_counts_and_revision",
    "test_step_wraps_choices_and_sets_toggles",
    "test_unverified_copy_and_human_override",
]


def test_draft_preserves_author_order_and_effective_defaults(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path), review_revision=3)
    assert draft.ids == ["grouping", "tui_note"]
    assert draft.value_for("grouping") == "pane"
    assert draft.value_for("tui_note") is False
    assert draft.review_revision == 3


def test_step_wraps_choices_and_sets_toggles(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
    draft.step("grouping", 1)
    assert draft.value_for("grouping") == "mode"
    draft.step("grouping", 1)
    assert draft.value_for("grouping") == "pane"
    draft.step("tui_note", 1)
    assert draft.value_for("tui_note") is True
    draft.step("tui_note", -1)
    assert draft.value_for("tui_note") is False


def test_flip_and_reset(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
    draft.flip("tui_note")
    assert draft.value_for("tui_note") is True
    draft.reset("tui_note")
    assert draft.value_for("tui_note") is False
    draft.step("grouping", 1)
    draft.reset_all()
    assert draft.value_for("grouping") == "pane"
    assert draft.value_for("tui_note") is False


def test_decision_map_keys(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
    assert draft.decision_map() == {
        "decision_grouping": "pane",
        "decision_tui_note": False,
    }


def test_sheet_counts_and_revision(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path), review_revision=4)
    sheet = draft.sheet()
    assert sheet["count"] == 2
    assert sheet["review_revision"] == 4
    assert sheet["changed_count"] == 0
    draft.step("grouping", 1)
    assert draft.sheet()["changed_count"] == 1


def test_collapsed_and_expanded_row_text(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
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
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    row = rows["tui_note"]
    assert _is_unverified_row(row, plan_decision_definitions(tmp_path)[1])
    expanded = _expanded_row_text(
        row, definition=plan_decision_definitions(tmp_path)[1]
    ).plain
    assert "not in your messages" in expanded
    assert "off until you turn it on" in expanded
    # Collapsed row also shows the unverified warning, not only expanded.
    collapsed = _collapsed_row_text(
        row, definition=plan_decision_definitions(tmp_path)[1]
    ).plain
    assert "not in your messages" in collapsed
    draft.set_value("tui_note", True)
    updated = {row["id"]: row for row in draft.sheet()["rows"]}["tui_note"]
    assert updated["value"] is True
    assert updated["changed"] is True
    assert "●" in _collapsed_row_text(updated).plain
    # Turning an unverified row on keeps the warning (never you asked).
    turned = _expanded_row_text(
        updated, definition=plan_decision_definitions(tmp_path)[1]
    ).plain
    assert "not in your messages" in turned
    assert "you asked:" not in turned
    turned_collapsed = _collapsed_row_text(
        updated, definition=plan_decision_definitions(tmp_path)[1]
    ).plain
    assert "not in your messages" in turned_collapsed


def test_new_chip_for_missing_memory_note(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
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
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
    assert draft.feedback_carry_lines() == []
    draft.step("grouping", 1)
    draft.set_value("tui_note", True)
    lines = draft.feedback_carry_lines()
    assert lines[0] == "Carries: grouping → mode"
    assert lines[1] == "Carries: tui_note → yes"
