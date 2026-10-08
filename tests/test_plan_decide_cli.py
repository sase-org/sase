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

from sase.feature_flags.snapshot import override_flags
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

    with override_flags(plan_decisions=True):
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

    with override_flags(plan_decisions=True):
        definitions = _definitions()
        with pytest.raises(DecideError) as excinfo:
            _build_decide_submitted(definitions, {"tui_note": "maybe"}, caller="human")
        assert "bad value" in excinfo.value.header
        assert any("★" in line for line in excinfo.value.detail_lines)


def test_choice_matches_case_insensitively() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    with override_flags(plan_decisions=True):
        definitions = _definitions()
        submitted = _build_decide_submitted(
            definitions, {"grouping": "MODE"}, caller="human"
        )
        assert submitted == {"grouping": "mode"}


def test_choice_rejects_prefix_match_with_starred_allowed() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    with override_flags(plan_decisions=True):
        definitions = _definitions()
        with pytest.raises(DecideError) as excinfo:
            _build_decide_submitted(definitions, {"grouping": "mod"}, caller="human")
        assert "bad value" in excinfo.value.header
        allowed = " ".join(excinfo.value.detail_lines)
        assert "pane ★" in allowed
        assert "mode" in allowed


def test_unknown_id_suggests_close_match() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    with override_flags(plan_decisions=True):
        definitions = _definitions()
        with pytest.raises(DecideError) as excinfo:
            _build_decide_submitted(definitions, {"groupin": "mode"}, caller="human")
        assert "grouping" in excinfo.value.header


def test_agent_memory_switch_on_is_refused() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    with override_flags(plan_decisions=True):
        definitions = _definitions()
        with pytest.raises(DecideError, match="only be switched on by a human"):
            _build_decide_submitted(definitions, {"tui_note": "yes"}, caller="agent")


def test_agent_memory_switch_off_passes() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    with override_flags(plan_decisions=True):
        definitions = _definitions()
        assert _build_decide_submitted(
            definitions, {"tui_note": "no"}, caller="agent"
        ) == {"tui_note": False}


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

    with override_flags(plan_decisions=True):
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
    with override_flags(plan_decisions=True):
        line = retry_line_for_plan(plan)
    assert line == (
        "Retrying implementation with the accepted decisions: "
        "grouping=mode; tui_note=no."
    )


def test_retry_line_absent_for_pending_plan(tmp_path: Path) -> None:
    from sase.main.plan_decide import retry_line_for_plan

    plan = tmp_path / "plan.md"
    plan.write_text(PENDING_TALE, encoding="utf-8")
    with override_flags(plan_decisions=True):
        assert retry_line_for_plan(plan) is None


def test_retry_line_absent_without_answers(tmp_path: Path) -> None:
    from sase.main.plan_decide import retry_line_for_plan

    plan = tmp_path / "plan.md"
    plan.write_text("---\ntier: tale\ntitle: T\ngoal: G\nsize: small\n---\nBody.\n")
    with override_flags(plan_decisions=True):
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
