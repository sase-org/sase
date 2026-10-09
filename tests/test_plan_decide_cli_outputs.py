"""Completion, gate/inventory/show, and submission coverage.

Split from ``tests.test_plan_decide_cli``: covers the ``-D``
completion provider, the ``show``/``list``/``gate show`` decision
output helpers, the validate JSON envelope, and the live-gate decide
submission. Shared fixtures live in ``tests._plan_decide_cli_shared``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.main.plan_decide import DecideError
from tests._plan_decide_cli_shared import PENDING_TALE, make_definitions


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
    from sase.main import plan_approve_pending
    from sase.main.plan_approve_pending import approve_pending_plan
    from sase.main.plan_pending import PendingPlan
    from sase.notifications.models import Notification

    definitions = [dict(item) for item in make_definitions()]
    monkeypatch.setattr(
        plan_approve_pending,
        "_live_gate_decisions",
        lambda _plan: (definitions, 7, {"approve"}),
    )
    monkeypatch.setattr("sase.main.plan_decide.caller_for_decide", lambda: "human")
    monkeypatch.setattr(
        plan_approve_pending, "ensure_plan_notification_available", lambda _n: None
    )
    context_sentinel = object()
    monkeypatch.setattr(
        plan_approve_pending,
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
        plan_approve_pending, "execute_plan_approval_response", _fake_execute
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

    result = approve_pending_plan(
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
