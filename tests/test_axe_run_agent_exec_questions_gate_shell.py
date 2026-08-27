"""Question marker gate-shell handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.axe import run_agent_exec_questions as questions_mod
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.transaction import GateShellCreation
from sase.main.qa_markdown import QARound
from sase.notification_gates.model_results import GateCreationResult
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import patch_plan_deps
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state

pytestmark = pytest.mark.usefixtures(patch_plan_deps.__name__)


def _fake_record(*, gate_state: str, artifacts_dir: str) -> GateShellRecord:
    return GateShellRecord(
        gate_id="round-1",
        member_agent_name="test_agent--gate",
        lane="test_agent",
        project_name="test_proj",
        artifacts_dir=artifacts_dir,
        timestamp="20260826120000",
        kind="question",
        gate_state=gate_state,  # type: ignore[arg-type]
        start_status="QUESTION",
        stop_status="ANSWERED",
        accent="#FFAF00",
        label="Question",
        reason="wait for reviewer",
        creator_agent="test_agent",
        bundle_path="/tmp/bundle",
        notification_id="notif-1",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        workspace_policy="inherit",
    )


def _fake_creation(*, gate_state: str, artifacts_dir: str) -> GateShellCreation:
    gate = GateCreationResult(
        schema_version=3,
        notification_id="notif-1" if gate_state == "pending" else None,
        request_id="round-1",
        kind="question",
        bundle_path=Path("/tmp/bundle"),
        request_path=Path("/tmp/bundle/request.json"),
        response_path=Path("/tmp/bundle/response.json"),
        preview_path=None,
        continuation_mode="agent_question",
        auto_resolution={},
        hashes={},
    )
    record = _fake_record(gate_state=gate_state, artifacts_dir=artifacts_dir)
    return GateShellCreation(
        gate=gate, record=record, project_file=None, claim_move=None, cl_name=None
    )


def _questions() -> list[dict[str, Any]]:
    return [
        {
            "question": "Which database?",
            "options": [{"label": "SQLite"}, {"label": "PostgreSQL"}],
        }
    ]


def test_non_auto_creates_a_gate_shell_and_ends_gated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)

    creation = _fake_creation(
        gate_state="pending", artifacts_dir=str(tmp_path / "gate-member")
    )
    (tmp_path / "gate-member").mkdir()

    monkeypatch.setattr(
        "sase.question_shell.resolve_question_chain_parent", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "sase.question_shell.create_question_gate_shell", lambda *a, **k: creation
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active", lambda: False
    )

    def fail_wait_for_gate(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("wait_for_gate must not be called")

    monkeypatch.setattr(
        "sase.notification_gates.poller.wait_for_gate", fail_wait_for_gate
    )

    gate_marker_calls: list[dict[str, Any]] = []

    def fake_handle_gate_marker(
        gate_data: dict[str, Any], _ctx: Any, _state: Any
    ) -> str:
        gate_marker_calls.append(gate_data)
        return "gated"

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.handle_gate_marker", fake_handle_gate_marker
    )

    outcome = questions_mod.handle_questions_marker(
        {"questions": _questions()}, ctx, state
    )

    assert outcome == "gated"
    assert state.question_gate_artifacts_dir == creation.record.artifacts_dir
    assert gate_marker_calls == [
        {
            "gate_id": "round-1",
            "member_artifacts_dir": str(tmp_path / "gate-member"),
            "member_agent_name": "test_agent--gate",
            "kind": "question",
        }
    ]
    assert not (Path(state.current_artifacts_dir) / "pending_question.json").exists()


def test_auto_continues_in_process_with_no_second_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)

    creation = _fake_creation(
        gate_state="answered", artifacts_dir=str(tmp_path / "gate-member")
    )
    (tmp_path / "gate-member").mkdir()
    assert creation.should_handoff is False

    monkeypatch.setattr(
        "sase.question_shell.resolve_question_chain_parent", lambda *a, **k: None
    )
    monkeypatch.setattr(
        "sase.question_shell.create_question_gate_shell", lambda *a, **k: creation
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active", lambda: True
    )
    monkeypatch.setattr(
        "sase.question_shell.question_rounds",
        lambda *a, **k: [
            QARound(
                questions=_questions(),
                answers=[
                    {
                        "question": "Which database?",
                        "selected": ["SQLite"],
                        "custom_feedback": None,
                    }
                ],
                global_note=None,
            )
        ],
    )

    successor_calls: list[Any] = []
    monkeypatch.setattr(
        questions_mod,
        "continue_as_successor",
        lambda *a, **k: successor_calls.append((a, k)),
    )

    never_called = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr("sase.axe.run_agent_exec_gate.handle_gate_marker", never_called)

    outcome = questions_mod.handle_questions_marker(
        {"questions": _questions()}, ctx, state
    )

    assert outcome is None
    assert len(successor_calls) == 1
    never_called.assert_not_called()
    (_args, kwargs) = successor_calls[0]
    successor_request = _args[2]
    assert "Which database?" in successor_request.prompt
