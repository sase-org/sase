"""Decision card, retry line, and memory-chip rendering.

Split from ``tests.test_plan_decide_cli``: covers the Section 1.4
decision card shapes, the retry and agent-boundary messages, and the
memory provenance chips. Shared fixtures live in
``tests._plan_decide_cli_shared``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.main.plan_decide import decision_card_lines
from tests._plan_decide_cli_shared import PENDING_TALE, make_definitions


def _card(*, dry_run: bool) -> list[str]:
    from sase.main.plan_decide import resolve_decide_values
    from sase.sdd.plan_decisions import sheet_binding

    definitions = make_definitions()
    values, rows = resolve_decide_values(
        definitions, {"grouping": "mode"}, caller="human"
    )
    sheet = sheet_binding(definitions, values, 4)
    return decision_card_lines(
        kind_label="tale",
        plan_name="keymap_help_overlay",
        review_revision=4,
        sheet=sheet,
        rows=rows,
        verdict="coder + commit",
        dry_run=dry_run,
    )


def test_decision_card_dry_run_shape() -> None:
    lines = _card(dry_run=True)
    assert lines[0] == "◇ Dry run · tale · keymap_help_overlay · review 4"
    assert lines[-1] == "nothing was approved (dry run)"
    body = "\n".join(lines)
    assert "grouping" in body and "mode ●" in body and "-D" in body
    assert "was ★ pane" in body
    assert "tui_note" in body and "default" in body
    assert "🧠 tui.md" in body
    summary = [line for line in lines if "coder + commit" in line]
    assert len(summary) == 1
    assert summary[0].startswith("  → ")
    assert "→ →" not in body


def test_decision_card_real_run_has_no_dry_run_lines() -> None:
    lines = _card(dry_run=False)
    body = "\n".join(lines)
    assert "Dry run" not in body
    assert "nothing was approved" not in body
    assert any("→ " in line for line in lines)


def test_retry_line_uses_accepted_answers(tmp_path: Path) -> None:
    from sase.main.plan_decide import retry_line_for_plan

    plan = tmp_path / "plan.md"
    plan.write_text(
        PENDING_TALE.replace("default: pane", "default: pane\n    answer: mode")
        .replace("default: false", "default: false\n    answer: false")
        .replace("size: small", "size: small\ndecided_by: reviewer\ndecided_via: cli"),
        encoding="utf-8",
    )
    line = retry_line_for_plan(plan)
    assert line == (
        "Retrying implementation with the accepted decisions: "
        "grouping=mode; tui_note=no."
    )


def test_retry_line_absent_for_pending_plan(tmp_path: Path) -> None:
    from sase.main.plan_decide import retry_line_for_plan

    plan = tmp_path / "plan.md"
    plan.write_text(PENDING_TALE, encoding="utf-8")
    assert retry_line_for_plan(plan) is None


def test_retry_line_absent_without_answers(tmp_path: Path) -> None:
    from sase.main.plan_decide import retry_line_for_plan

    plan = tmp_path / "plan.md"
    plan.write_text("---\ntier: tale\ntitle: T\ngoal: G\nsize: small\n---\nBody.\n")
    assert retry_line_for_plan(plan) is None


def _card_lines_for_values(raw_map: dict[str, str]) -> list[str]:
    from sase.main.plan_decide import resolve_decide_values
    from sase.sdd.plan_decisions import sheet_binding

    definitions = make_definitions()
    values, rows = resolve_decide_values(definitions, raw_map, caller="human")
    sheet = sheet_binding(definitions, values, 4)
    return decision_card_lines(
        kind_label="tale",
        plan_name="keymap_help_overlay",
        review_revision=4,
        sheet=sheet,
        rows=rows,
        verdict="coder + commit",
        dry_run=True,
    )


def test_card_clamped_source_renders_default_origin() -> None:
    from sase.main.plan_decide import decision_card_lines
    from sase.sdd.plan_decisions import sheet_binding

    definitions = make_definitions()
    sheet = sheet_binding(definitions, {"grouping": "pane", "tui_note": False}, 4)
    rows = [
        {"id": "grouping", "value": "pane", "source": "default", "changed": False},
        {"id": "tui_note", "value": False, "source": "clamped", "changed": False},
    ]
    lines = decision_card_lines(
        kind_label="tale",
        plan_name="keymap_help_overlay",
        review_revision=4,
        sheet=sheet,
        rows=rows,
        verdict="coder + commit",
        dry_run=True,
    )
    tui_line = next(line for line in lines if "tui_note" in line)
    assert "default" in tui_line
    assert "-D" not in tui_line


def test_card_unchanged_row_carries_star() -> None:
    lines = _card_lines_for_values({"grouping": "mode"})
    tui_line = next(line for line in lines if "tui_note" in line)
    assert "★" in tui_line
    grouping_line = next(line for line in lines if "grouping" in line)
    assert "●" in grouping_line
    assert "was ★ pane" in grouping_line


def test_card_memory_chips_do_not_duplicate_or_contradict() -> None:
    from sase.main.plan_decide import decision_card_lines
    from sase.sdd.plan_decisions import sheet_binding

    definitions = make_definitions()
    sheet = sheet_binding(definitions, {"grouping": "pane", "tui_note": True}, 4)
    for row in sheet["rows"]:
        if row["id"] == "tui_note" and isinstance(row.get("memory"), dict):
            row["memory"]["provenance"] = "asked"
            row["memory"]["quote"] = "and note the convention"
    rows = [
        {"id": "grouping", "value": "pane", "source": "default", "changed": False},
        {"id": "tui_note", "value": True, "source": "submitted", "changed": True},
    ]
    lines = decision_card_lines(
        kind_label="tale",
        plan_name="keymap_help_overlay",
        review_revision=4,
        sheet=sheet,
        rows=rows,
        verdict="coder + commit",
        dry_run=True,
    )
    asked_line = next(line for line in lines if "tui_note" in line)
    assert asked_line.count("you asked") == 1

    for row in sheet["rows"]:
        if row["id"] == "tui_note" and isinstance(row.get("memory"), dict):
            row["memory"]["provenance"] = "quote_not_found"
            row["memory"]["quote"] = "and note the convention"
    lines = decision_card_lines(
        kind_label="tale",
        plan_name="keymap_help_overlay",
        review_revision=4,
        sheet=sheet,
        rows=rows,
        verdict="coder + commit",
        dry_run=True,
    )
    warned_line = next(line for line in lines if "tui_note" in line)
    assert "quote not found" in warned_line
    assert "you asked:" not in warned_line


def test_host_facts_verify_requested_quote_for_default_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from sase.sdd.plan_decisions_host import _build_host_facts
    from sase.sdd.plan_validate import validate_plan

    validation = validate_plan(PENDING_TALE, "tale")
    assert validation.ok
    monkeypatch.setattr(
        "sase.sdd.plan_human_text.human_authored_texts",
        lambda _directory: (
            SimpleNamespace(
                source="prompt",
                ref="root",
                text=(
                    "please update the overlay and note the convention "
                    "in the tui memory today"
                ),
            ),
        ),
    )
    facts = _build_host_facts(validation, str(tmp_path))
    assert facts["tui_note"]["provenance"] == "asked"

    monkeypatch.setattr(
        "sase.sdd.plan_human_text.human_authored_texts", lambda _directory: ()
    )
    facts = _build_host_facts(validation, str(tmp_path))
    assert facts["tui_note"]["provenance"] == "quote_not_found"


def test_card_human_override_on_quote_not_found_row_drops_stale_off() -> None:
    from sase.main.plan_decide import decision_card_lines
    from sase.sdd.plan_decisions import sheet_binding

    definitions = make_definitions()
    sheet = sheet_binding(definitions, {"grouping": "pane", "tui_note": True}, 4)
    for row in sheet["rows"]:
        if row["id"] == "tui_note" and isinstance(row.get("memory"), dict):
            row["memory"]["provenance"] = "quote_not_found"
            row["memory"]["quote"] = "and note the convention"
    rows = [
        {"id": "grouping", "value": "pane", "source": "default", "changed": False},
        {"id": "tui_note", "value": True, "source": "submitted", "changed": True},
    ]
    lines = decision_card_lines(
        kind_label="tale",
        plan_name="keymap_help_overlay",
        review_revision=4,
        sheet=sheet,
        rows=rows,
        verdict="coder + commit",
        dry_run=True,
    )
    tui_line = next(line for line in lines if "tui_note" in line)
    assert "yes" in tui_line and "●" in tui_line
    assert "quote not found" in tui_line
    assert "· off" not in tui_line


def test_card_value_column_padding_lines_up_source_column() -> None:
    lines = _card_lines_for_values({"grouping": "mode"})
    grouping_line = next(line for line in lines if "grouping" in line)
    tui_line = next(line for line in lines if "tui_note" in line)
    assert grouping_line.index("-D") == tui_line.index("default")


def test_card_renders_new_chip_for_missing_note() -> None:
    from sase.main.plan_decide import decision_card_lines
    from sase.sdd.plan_decisions import sheet_binding

    definitions = make_definitions()
    sheet = sheet_binding(definitions, {"grouping": "pane", "tui_note": False}, 4)
    for row in sheet["rows"]:
        if row["id"] == "tui_note" and isinstance(row.get("memory"), dict):
            row["memory"]["resolved"] = [
                {
                    "selector": "fresh_note.md",
                    "kind": "note",
                    "scope": "project",
                    "path": "sase/memory/fresh_note.md",
                    "type": "reference",
                    "exists": False,
                }
            ]
            row["memory"]["selectors"] = ["fresh_note.md"]
    rows = [
        {"id": "grouping", "value": "pane", "source": "default", "changed": False},
        {"id": "tui_note", "value": False, "source": "default", "changed": False},
    ]
    lines = decision_card_lines(
        kind_label="tale",
        plan_name="keymap_help_overlay",
        review_revision=4,
        sheet=sheet,
        rows=rows,
        verdict="coder + commit",
        dry_run=True,
    )
    assert any("new" in line and "tui_note" in line for line in lines)


def test_pending_text_renders_new_chip_and_no_duplicate() -> None:
    from sase.sdd._plan_display_decisions import (
        _memory_type_chips,
        pending_decisions_text,
    )

    memory: dict[str, object] = {
        "selectors": ["fresh_note.md"],
        "resolved": [
            {
                "selector": "fresh_note.md",
                "kind": "note",
                "scope": "project",
                "path": "sase/memory/fresh_note.md",
                "type": "reference",
                "exists": False,
            }
        ],
        "provenance": "asked",
        "quote": "please record this",
    }
    assert "new" in _memory_type_chips(memory)  # type: ignore[arg-type]
    sheet = {
        "rows": [
            {
                "id": "tui_note",
                "kind": "toggle",
                "ask": "Record?",
                "default": False,
                "memory": memory,
            }
        ]
    }
    text = pending_decisions_text(sheet).plain  # type: ignore[arg-type]
    assert "new" in text
    assert text.count("you asked") == 1
