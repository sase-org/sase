"""CLI-phase coverage for Plan Decisions (sase-1hi.5).

Covers ``sase plan approve -D/--decide`` parsing and validation, the
Section 1.4 decision card, the retry and agent-boundary messages, the
``-D`` completion provider, and the ``show``/``list``/``gate show``
decision output helpers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.main.plan_decide import (
    DecideError,
    already_approved_decide_error,
    decision_card_lines,
    parse_decide_assignments,
    verdict_for_kind,
)

PENDING_TALE = """---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  grouping:
    ask: How should the overlay group bindings?
    choices:
      pane: By pane, matching the footer hints
      mode: By leader mode; denser, but splits pane actions
    default: pane
    why: pane keeps the footer's order
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "and note the convention in the tui memory"
    default: false
---
# Plan

> [!decision] grouping = pane Order by pane.
> [!decision] grouping = mode Order by mode.
Body mentions tui_note.
"""


def _definitions():
    from sase.sdd.plan_decisions import build_definitions
    from sase.sdd.plan_validate import validate_plan

    validation = validate_plan(PENDING_TALE, "tale")
    assert validation.ok, [str(diagnostic) for diagnostic in validation.diagnostics]
    assert validation.plan is not None
    return build_definitions(validation, "")


def test_parse_decide_assignments_split_id_value() -> None:
    assert parse_decide_assignments(["grouping=mode", "tui_note = yes"]) == {
        "grouping": "mode",
        "tui_note": "yes",
    }


def test_parse_decide_rejects_missing_equals() -> None:
    with pytest.raises(DecideError, match="ID=VALUE"):
        parse_decide_assignments(["grouping"])


def test_parse_decide_rejects_empty_id() -> None:
    with pytest.raises(DecideError):
        parse_decide_assignments(["=mode"])


def test_parse_decide_rejects_duplicate_id() -> None:
    with pytest.raises(DecideError, match="twice"):
        parse_decide_assignments(["grouping=pane", "grouping=mode"])


def test_toggle_accepts_shared_bool_spellings() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = _definitions()
    for raw, expected in (
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("TRUE", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ):
        submitted = _build_decide_submitted(
            definitions, {"tui_note": raw}, caller="human"
        )
        assert submitted == {"tui_note": expected}


def test_toggle_rejects_unknown_spelling_with_allowed_values() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = _definitions()
    with pytest.raises(DecideError) as excinfo:
        _build_decide_submitted(definitions, {"tui_note": "maybe"}, caller="human")
    assert "bad value" in excinfo.value.header
    assert any("★" in line for line in excinfo.value.detail_lines)


def test_choice_matches_case_insensitively() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = _definitions()
    submitted = _build_decide_submitted(
        definitions, {"grouping": "MODE"}, caller="human"
    )
    assert submitted == {"grouping": "mode"}


def test_choice_rejects_prefix_match_with_starred_allowed() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = _definitions()
    with pytest.raises(DecideError) as excinfo:
        _build_decide_submitted(definitions, {"grouping": "mod"}, caller="human")
    assert "bad value" in excinfo.value.header
    allowed = " ".join(excinfo.value.detail_lines)
    assert "pane ★" in allowed
    assert "mode" in allowed


def test_unknown_id_suggests_close_match() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = _definitions()
    with pytest.raises(DecideError) as excinfo:
        _build_decide_submitted(definitions, {"groupin": "mode"}, caller="human")
    assert "grouping" in excinfo.value.header


def test_agent_memory_switch_on_is_refused() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = _definitions()
    with pytest.raises(DecideError, match="only be switched on by a human"):
        _build_decide_submitted(definitions, {"tui_note": "yes"}, caller="agent")


def test_agent_memory_switch_off_passes() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = _definitions()
    assert _build_decide_submitted(definitions, {"tui_note": "no"}, caller="agent") == {
        "tui_note": False
    }


def test_already_approved_refusal_names_decide_ids() -> None:
    error = already_approved_decide_error({"tui_note": "yes"})
    assert "already approved" in error.header
    assert "accepted answers" in error.header
    assert "tui_note" in error.header


def test_verdict_for_kind() -> None:
    assert verdict_for_kind("tale") == "coder + commit"
    assert verdict_for_kind(None) == "coder + commit"
    assert verdict_for_kind("approve") == "coder"
    assert verdict_for_kind("commit") == "commit"
    assert verdict_for_kind("epic") == "epic launch"


def test_format_values_sentence_uses_display_words() -> None:
    from sase.main.plan_decide import _format_values_sentence

    assert (
        _format_values_sentence({"grouping": "mode", "tui_note": False})
        == "grouping=mode; tui_note=no"
    )


def _card(*, dry_run: bool) -> list[str]:
    from sase.main.plan_decide import resolve_decide_values
    from sase.sdd.plan_decisions import sheet_binding

    definitions = _definitions()
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


def test_plan_decision_candidates_offer_ids_then_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.completion.candidates.catalog_plans as catalog

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "plan_request.json").write_text(
        json.dumps(
            {
                "payload": {
                    "decisions": [
                        {
                            "id": "grouping",
                            "kind": "choice",
                            "ask": "How should it group?",
                            "choices": [
                                {"key": "pane", "label": "By pane"},
                                {"key": "mode", "label": "By mode"},
                            ],
                            "default": "pane",
                        },
                        {"id": "tui_note", "kind": "toggle", "default": False},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    row = {
        "action": "PlanApproval",
        "action_data": {"response_dir": str(bundle)},
        "timestamp": datetime.now(UTC).isoformat(),
        "dismissed": False,
    }
    monkeypatch.setattr(catalog, "_load_plan_approval_rows", lambda: [row])
    monkeypatch.setattr(catalog, "_load_pending_action_store", lambda: {})
    monkeypatch.setattr(catalog, "_gate_turn_terminal", lambda _gate_id: False)

    candidates = catalog.plan_decision_candidates(None)
    values = {candidate.value for candidate in candidates}
    assert "grouping=" in values
    assert "grouping=mode" in values
    assert "grouping=pane" in values
    assert "tui_note=yes" in values
    assert "tui_note=no" in values
    starred = [
        candidate.description
        for candidate in candidates
        if candidate.value == "grouping=pane"
    ]
    assert starred and "★" in starred[0]


def test_gate_show_payload_decisions_helpers() -> None:
    from sase.notification_gates.cli_show import (
        _non_decision_schema,
        _payload_decisions,
    )

    envelope: dict[str, object] = {"payload": {"decisions": [{"id": "a"}]}}
    assert _payload_decisions(envelope) == [{"id": "a"}]
    assert _payload_decisions({"payload": {}}) is None
    assert _payload_decisions({}) is None

    only_decisions = {
        "properties": {"decision_grouping": {"enum": ["pane"]}},
        "required": ["decision_grouping"],
    }
    assert _non_decision_schema(only_decisions) is None
    mixed = {
        "properties": {
            "decision_grouping": {"enum": ["pane"]},
            "coder_prompt": {"type": "string"},
        },
        "required": ["decision_grouping"],
    }
    reduced = _non_decision_schema(mixed)
    assert isinstance(reduced, dict)
    assert list(reduced["properties"]) == ["coder_prompt"]
    assert reduced["required"] == []


def test_inventory_decision_count_cell(tmp_path: Path) -> None:
    from sase.main.plan_inventory_render import _decision_count_cell

    with_decisions = tmp_path / "with.md"
    with_decisions.write_text(PENDING_TALE, encoding="utf-8")
    assert _decision_count_cell(str(with_decisions)).plain == "2"
    plain = tmp_path / "plain.md"
    plain.write_text("---\ntier: tale\ntitle: T\ngoal: G\n---\nBody.\n")
    assert _decision_count_cell(str(plain)).plain == ""
    assert _decision_count_cell(str(tmp_path / "missing.md")).plain == ""


def test_proposed_table_shows_count_column_only_with_decisions(
    tmp_path: Path,
) -> None:
    import io

    from rich.console import Console

    from sase.main.plan_inventory_models import ProposedPlan
    from sase.main.plan_inventory_render import _proposed_table

    def row_for(plan_path: str) -> ProposedPlan:
        return ProposedPlan(
            _plan_key=plan_path,
            name="demo",
            id_prefix="12345678",
            notification_id="12345678-plan",
            timestamp="2026-01-01T00:00:00+00:00",
            age="1h",
            agent="planner",
            project="demo",
            provider_model="opus",
            plan_path=plan_path,
            title="Demo",
            tier="tale",
            response_dir=str(tmp_path),
        )

    def rendered(plan_text: str) -> str:
        plan = tmp_path / f"plan_{abs(hash(plan_text)) % 100000}.md"
        plan.write_text(plan_text, encoding="utf-8")
        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=False, width=100)
        table = _proposed_table((row_for(str(plan)),), agent_project=lambda a, p: a)
        assert table is not None
        console.print(table)
        return buffer.getvalue()

    assert "◉" in rendered(PENDING_TALE)
    assert "◉" not in rendered("---\ntier: tale\ntitle: T\ngoal: G\n---\nBody.\n")


def test_render_decide_error_ends_with_refusal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.plan_approve_render import render_decide_error

    render_decide_error(DecideError("✗ bad value 'x'.", ("  grouping: pane ★, mode",)))
    captured = capsys.readouterr()
    assert "bad value" in captured.err
    assert "pane ★" in captured.err
    assert "nothing was approved" in captured.err


def test_direct_approval_request_decide_defaults_empty() -> None:
    from sase.main.plan_direct_approval_types import DirectApprovalRequest

    assert DirectApprovalRequest(selector="x").decide == ()


def _card_lines_for_values(raw_map: dict[str, str]) -> list[str]:
    from sase.main.plan_decide import resolve_decide_values
    from sase.sdd.plan_decisions import sheet_binding

    definitions = _definitions()
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

    definitions = _definitions()
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

    definitions = _definitions()
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

    from sase.sdd.plan_decisions import _build_host_facts
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

    definitions = _definitions()
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

    definitions = _definitions()
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


def test_validate_json_envelope_holds_sheet_and_auto_note() -> None:
    from sase.main.plan_validate_handler import _decision_json_envelope
    from sase.sdd.plan_validate import validate_plan

    validation = validate_plan(PENDING_TALE, "tale")
    assert validation.ok
    envelope = _decision_json_envelope(validation)
    assert envelope is not None
    assert isinstance(envelope["sheet"], dict)
    assert "grouping" in str(envelope["sheet_text"])
    assert envelope["auto_note"] in (
        None,
        "auto-approved: every decision takes its default",
    )


def test_validate_json_stdout_is_single_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    import json

    from sase.main import plan_validate_handler

    plan = tmp_path / "plan.md"
    plan.write_text(PENDING_TALE, encoding="utf-8")
    # Cover the real outside-agent path: in_agent_context() reads SASE_AGENT
    # and SASE_ARTIFACTS_DIR (SASE_AGENT_CONTEXT exists nowhere).
    monkeypatch.delenv("SASE_AGENT", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    args = argparse.Namespace(
        plan_file=str(plan), explain=False, json=True, quiet=False
    )
    with pytest.raises(SystemExit) as excinfo:
        plan_validate_handler.handle_plan_validate_command(args)
    assert excinfo.value.code in (0, 1)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "decisions" in payload
    assert isinstance(payload["decisions"], dict)
    assert "sheet_text" in payload["decisions"]


def test_plan_decision_candidates_scope_to_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.completion.candidates.catalog_plans as catalog

    def _bundle(plan_id: str, decisions: list[dict[str, object]]) -> dict[str, object]:
        bundle = tmp_path / plan_id
        bundle.mkdir(exist_ok=True)
        (bundle / "plan_request.json").write_text(
            json.dumps({"payload": {"decisions": decisions}}), encoding="utf-8"
        )
        return {
            "id": plan_id,
            "action": "PlanApproval",
            "action_data": {"response_dir": str(bundle)},
            "timestamp": datetime.now(UTC).isoformat(),
            "dismissed": False,
        }

    row_a = _bundle(
        "aaa-plan",
        [
            {
                "id": "grouping",
                "kind": "choice",
                "ask": "Group?",
                "choices": [
                    {"key": "pane", "label": "By pane"},
                    {"key": "mode", "label": "By mode"},
                ],
                "default": "pane",
            }
        ],
    )
    row_b = _bundle(
        "bbb-plan",
        [{"id": "other_choice", "kind": "toggle", "default": True}],
    )
    monkeypatch.setattr(catalog, "_load_plan_approval_rows", lambda: [row_a, row_b])
    monkeypatch.setattr(catalog, "_load_pending_action_store", lambda: {})
    monkeypatch.setattr(catalog, "_gate_turn_terminal", lambda _gate_id: False)
    monkeypatch.setattr(
        catalog, "_archive_path_for_row", lambda row: str(row.get("id"))
    )

    merged = {candidate.value for candidate in catalog.plan_decision_candidates(None)}
    assert "grouping=" in merged
    assert "other_choice=yes" in merged

    scoped = {
        candidate.value
        for candidate in catalog.plan_decision_candidates(None, selector="aaa-plan")
    }
    assert "grouping=" in scoped
    assert "other_choice=yes" not in scoped

    fallback = {
        candidate.value
        for candidate in catalog.plan_decision_candidates(None, selector="no-such-plan")
    }
    assert fallback == merged


def test_approve_help_has_single_retry_example(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main.parser import create_parser

    parser = create_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["plan", "approve", "-h"])
    assert excinfo.value.code == 0
    help_text = capsys.readouterr().out
    assert help_text.count("retry a failed coder") == 1
    assert "relaunch a failed coder" not in help_text
    assert "-D" in help_text


def test_live_gate_decide_submission_sends_decision_inputs_and_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.main import plan_approve_handler
    from sase.main.plan_approve_handler import _approve_pending_plan
    from sase.main.plan_pending import PendingPlan
    from sase.notifications.models import Notification

    definitions = [dict(item) for item in _definitions()]
    monkeypatch.setattr(
        plan_approve_handler,
        "_live_gate_decisions",
        lambda _plan: (definitions, 7, {"approve"}),
    )
    monkeypatch.setattr("sase.main.plan_decide.caller_for_decide", lambda: "human")
    monkeypatch.setattr(
        plan_approve_handler, "ensure_plan_notification_available", lambda _n: None
    )
    context_sentinel = object()
    monkeypatch.setattr(
        plan_approve_handler,
        "plan_context_from_notification",
        lambda _n: context_sentinel,
    )
    monkeypatch.setattr(
        "sase._plan_approval_protocol.resolve_plan_approval_choice",
        lambda _files, _kind: "approve",
    )
    monkeypatch.setattr(
        "sase.plan_approval_choices.plan_approval_selection_for_choice",
        lambda _choice, **_kwargs: ("approve",),
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_render.render_gate_approval", lambda *_a, **_k: None
    )
    captured: dict[str, object] = {}
    result_sentinel = object()

    def _fake_execute(context: object, kind: object, **kwargs: object) -> object:
        captured["context"] = context
        captured["kind"] = kind
        captured["kwargs"] = kwargs
        return result_sentinel

    monkeypatch.setattr(
        plan_approve_handler, "execute_plan_approval_response", _fake_execute
    )
    notification = Notification(
        id="abcdef12-plan",
        timestamp=datetime.now(UTC).isoformat(),
        sender="plan",
        files=["/tmp/plan.md"],
        action="PlanApproval",
        action_data={"response_dir": "/tmp/plan_approval"},
    )
    plan = PendingPlan(
        notification=notification,
        name="myplan",
        display_name="myplan",
        archive_path=None,
        bundle_plan_path=None,
        title="T",
        tier="tale",
        agent="planner",
        age="1m",
    )

    result = _approve_pending_plan(
        plan,
        selector="myplan",
        kind="tale",
        coder_prompt=None,
        coder_model=None,
        wait=None,
        dry_run=False,
        project=None,
        decide=("grouping=mode",),
    )

    assert result is result_sentinel
    assert captured["context"] is context_sentinel
    assert captured["kind"] == "tale"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["option_inputs"] == {
        "approve": {"decision_grouping": "mode", "decision_tui_note": False}
    }
    assert kwargs["expected_review_revision"] == 7
    assert kwargs["source"] == "cli"


def test_show_compact_counts_and_json_attach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_show_handler import _attach_decision_json
    from sase.main.plan_show_render import _decision_counts, _decisions_section

    plan = tmp_path / "plan.md"
    plan.write_text(PENDING_TALE, encoding="utf-8")

    fake_sheet = {
        "rows": [
            {"id": "grouping", "kind": "choice", "ask": "Group?"},
            {
                "id": "tui_note",
                "kind": "toggle",
                "ask": "Record?",
                "memory": {"selectors": ["tui.md"]},
            },
        ]
    }

    class _Stamped:
        sheet = fake_sheet
        decided_by = None
        decided_via = None
        values = {"grouping": "pane", "tui_note": False}

    class _FakePlan:
        path = str(plan)

    class _FakeRecord:
        plan = _FakePlan()

    import sase.sdd.plan_decision_handoff as handoff

    monkeypatch.setattr(handoff, "load_stamped_decisions", lambda _path: _Stamped())
    record = _FakeRecord()
    section = _decisions_section(record)  # type: ignore[arg-type]
    assert section is not None
    counts = _decision_counts(record)  # type: ignore[arg-type]
    assert counts is not None
    total, memos = counts
    assert total == 2
    assert memos == 1
    payload: dict[str, object] = {}
    _attach_decision_json(payload, record)  # type: ignore[arg-type]
    assert isinstance(payload.get("decisions"), dict)
