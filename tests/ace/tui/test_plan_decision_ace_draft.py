"""Plan decision draft model: ordering, stepping, cards, and carry lines."""

from __future__ import annotations

from rich.cells import cell_len

from sase.ace.tui.modals.plan_decision_cards import (
    collapsed_card,
    expanded_card,
    _is_unverified_row,
    render_lines,
)
from sase.ace.tui.modals.plan_decision_sheet import PlanDecisionDraft
from tests.ace.tui._plan_decision_ace_shared import plan_decision_definitions

__all__ = [
    "test_card_builders_wrap_at_widths",
    "test_collapsed_and_expanded_cards",
    "test_decision_map_keys",
    "test_draft_preserves_author_order_and_effective_defaults",
    "test_feedback_carry_lines_only_changed",
    "test_flip_and_reset",
    "test_new_chip_for_missing_memory_note",
    "test_sheet_counts_and_revision",
    "test_step_wraps_choices_and_sets_toggles",
    "test_toggle_chip_glyphs_measure_one_cell",
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


def _card_plain(card) -> str:  # type: ignore[no-untyped-def]
    return "\n".join(render_lines(card.renderable, 76))


def test_collapsed_and_expanded_cards(tmp_path) -> None:
    definitions = plan_decision_definitions(tmp_path)
    draft = PlanDecisionDraft(definitions)
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    collapsed = _card_plain(collapsed_card(rows["grouping"], definitions[0], 76))
    assert "grouping" in collapsed and "pane" in collapsed
    expanded = _card_plain(expanded_card(rows["grouping"], definitions[0], 76))
    assert "How should the overlay group" in expanded
    assert "★" in expanded
    # Expanded choice header shows the current value.
    assert "pane" in expanded.splitlines()[0]
    draft.step("grouping", 1)
    changed_rows = {row["id"]: row for row in draft.sheet()["rows"]}
    changed_expanded = _card_plain(
        expanded_card(changed_rows["grouping"], definitions[0], 76)
    )
    assert "mode" in changed_expanded.splitlines()[0]
    assert "●" in changed_expanded


def test_unverified_copy_and_human_override(tmp_path) -> None:
    definitions = plan_decision_definitions(tmp_path)
    draft = PlanDecisionDraft(definitions)
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    row = rows["tui_note"]
    assert _is_unverified_row(row, definitions[1])
    expanded = _card_plain(expanded_card(row, definitions[1], 76))
    assert "not in your messages; turn on to allow" in expanded
    # Collapsed cards preview the short yellow warning instead of the ask.
    collapsed = _card_plain(collapsed_card(row, definitions[1], 76))
    assert "⚠ quote not found · off" in collapsed
    draft.set_value("tui_note", True)
    updated = {row["id"]: row for row in draft.sheet()["rows"]}["tui_note"]
    assert updated["value"] is True
    assert updated["changed"] is True
    assert "●" in _card_plain(collapsed_card(updated, definitions[1], 76))
    # Turning an unverified row on keeps the warning (never you asked).
    turned = _card_plain(expanded_card(updated, definitions[1], 76))
    assert "not in your messages" in turned
    assert "you asked:" not in turned
    turned_collapsed = _card_plain(collapsed_card(updated, definitions[1], 76))
    assert "⚠ quote not found · off" in turned_collapsed


def test_new_chip_for_missing_memory_note(tmp_path) -> None:
    definitions = plan_decision_definitions(tmp_path)
    draft = PlanDecisionDraft(definitions)
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
    collapsed = _card_plain(collapsed_card(row, definitions[1], 76))
    assert "⚠ quote not found" in collapsed
    expanded = _card_plain(expanded_card(row, definitions[1], 76))
    # Unverified warning still wins for quote_not_found rows.
    assert "not in your messages" in expanded
    assert "new" in expanded


def _syncthing_maxcopy_rows(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    import json

    from tests.ace.tui.visual._ace_plan_decisions_png_fixtures import (
        MAXCOPY_PLAN,
        MEMORY_QUOTE,
        SYNCTHING_PLAN,
    )

    from sase.plan_gate import build_plan_approval_gate_spec

    collected = []
    for name, content in (
        ("syncthing.md", SYNCTHING_PLAN),
        ("maxcopy.md", MAXCOPY_PLAN),
    ):
        plan = tmp_path / name
        plan.write_text(content, encoding="utf-8")
        if name == "maxcopy.md":
            artifacts = tmp_path / "artifacts"
            artifacts.mkdir(exist_ok=True)
            (artifacts / "agent_meta.json").write_text(
                json.dumps({"prompt_origin": "typed"}), encoding="utf-8"
            )
            (artifacts / "submitted_prompt.md").write_text(
                f"Please do the work {MEMORY_QUOTE} thanks.\n", encoding="utf-8"
            )
            monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        else:
            monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        spec = build_plan_approval_gate_spec(plan, "visual-session")
        draft = PlanDecisionDraft(
            [dict(item) for item in spec["payload"].get("decisions", [])]
        )
        collected.extend(draft.sheet()["rows"])
    return collected


def test_card_builders_wrap_at_widths(tmp_path, monkeypatch) -> None:
    rows = _syncthing_maxcopy_rows(tmp_path, monkeypatch)
    assert len(rows) == 9
    for width in (46, 76, 100):
        for row in rows:
            assert isinstance(row, dict)
            cards = [
                collapsed_card(row, None, width),
                collapsed_card(row, None, width, preview_lines=1),
                expanded_card(row, None, width),
            ]
            for card in cards:
                lines = render_lines(card.renderable, width)
                assert lines, (row.get("id"), width)
                for line in lines:
                    assert cell_len(line) <= width, (row.get("id"), width, line)
            # Nothing clipped: every word of each ask, label, and why
            # appears somewhere in the expanded card. Wrapped and folded
            # lines lose their breaks, so compare spaceless on both sides.
            expanded_lines = render_lines(cards[2].renderable, width)
            expanded_text = "\n".join(expanded_lines)
            expanded_flat = "".join(
                "".join(line.replace("▌", "").split()) for line in expanded_lines
            )
            for source in (
                str(row.get("ask", "")),
                str(row.get("why", "")),
                *[
                    str(choice.get("label", ""))
                    for choice in (row.get("choices") or [])
                    if isinstance(choice, dict)
                ],
            ):
                for word in source.split():
                    assert "".join(word.split()) in expanded_flat, (
                        row.get("id"),
                        width,
                        word,
                    )
            # Ellipsis only in the header id and the collapsed preview.
            for line in render_lines(cards[2].renderable, width)[1:]:
                assert "…" not in line, (row.get("id"), width, line)
            # No `default:` line; the why footnote carries the default mark.
            assert "default:" not in expanded_text, (row.get("id"), width)
            if isinstance(row.get("why"), str) and row["why"].strip():
                assert "why ★" in expanded_text, (row.get("id"), width)


def test_toggle_chip_glyphs_measure_one_cell(tmp_path) -> None:
    definitions = plan_decision_definitions(tmp_path)
    draft = PlanDecisionDraft(definitions)
    rows = {row["id"]: row for row in draft.sheet()["rows"]}
    assert cell_len("☐") == 1
    assert cell_len("☑") == 1
    collapsed = _card_plain(collapsed_card(rows["tui_note"], definitions[1], 76))
    assert "☐ no ★" in collapsed
    # 🧠 only ever starts a line, never sits mid-line.
    for line in collapsed.splitlines():
        assert "🧠" not in line or line.lstrip().startswith("🧠"), line
    draft.set_value("tui_note", True)
    updated = {row["id"]: row for row in draft.sheet()["rows"]}["tui_note"]
    assert "☑ yes ●" in _card_plain(collapsed_card(updated, definitions[1], 76))


def test_feedback_carry_lines_only_changed(tmp_path) -> None:
    draft = PlanDecisionDraft(plan_decision_definitions(tmp_path))
    assert draft.feedback_carry_lines() == []
    draft.step("grouping", 1)
    draft.set_value("tui_note", True)
    lines = draft.feedback_carry_lines()
    assert lines[0] == "Carries: grouping → mode"
    assert lines[1] == "Carries: tui_note → yes"
