"""Both flag states of plan marker gate-shell handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.axe import run_agent_exec_plan as plan_mod
from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.transaction import GateShellCreation
from sase.llm_provider._plan_utils import PlanApprovalResult
from sase.notification_gates.model_results import GateCreationResult
from tests._axe_run_agent_exec_plan_followup_prompt_helpers import patch_plan_deps
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state

pytestmark = pytest.mark.usefixtures(patch_plan_deps.__name__)


def _fake_record(*, gate_state: str, artifacts_dir: str) -> GateShellRecord:
    return GateShellRecord(
        gate_id="plan-1",
        member_agent_name="test_agent--gate",
        lane="test_agent",
        project_name="test_proj",
        artifacts_dir=artifacts_dir,
        timestamp="20260827120000",
        kind="plan",
        gate_state=gate_state,  # type: ignore[arg-type]
        start_status="TALE",
        stop_status="TALE APPROVED",
        accent="#FFD75F",
        label="Plan",
        reason="wait for reviewer",
        creator_agent="test_agent--plan",
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
        request_id="plan-1",
        kind="plan",
        bundle_path=Path("/tmp/bundle"),
        request_path=Path("/tmp/bundle/request.json"),
        response_path=Path("/tmp/bundle/response.json"),
        preview_path=None,
        continuation_mode="plan_approval",
        auto_resolution={"state": "resolved"} if gate_state == "answered" else {},
        hashes={},
    )
    record = _fake_record(gate_state=gate_state, artifacts_dir=artifacts_dir)
    return GateShellCreation(
        gate=gate, record=record, project_file=None, claim_move=None, cl_name=None
    )


def test_flag_off_uses_existing_blocking_plan_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    plan_file = str(tmp_path / "plan.md")
    monkeypatch.setattr(
        "sase.gate_shell.flag.gate_shell_handoff_enabled", lambda: False
    )
    blocking_calls: list[Any] = []

    def fake_handle_plan_approval(*args: Any, **kwargs: Any) -> Any:
        blocking_calls.append((args, kwargs))
        return None

    monkeypatch.setattr(
        "sase.llm_provider._plan_utils.handle_plan_approval",
        fake_handle_plan_approval,
    )
    never_called = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr("sase.plan_shell.create_plan_gate_shell", never_called)

    outcome = plan_mod.handle_plan_marker({"plan_file": plan_file}, ctx, state)

    assert outcome == "plan_rejected"
    assert blocking_calls
    never_called.assert_not_called()


def test_flag_on_non_auto_creates_gate_shell_and_ends_gated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    plan_file = str(tmp_path / "plan.md")
    monkeypatch.setattr("sase.gate_shell.flag.gate_shell_handoff_enabled", lambda: True)
    creation = _fake_creation(
        gate_state="pending",
        artifacts_dir=str(tmp_path / "gate-member"),
    )
    Path(creation.record.artifacts_dir).mkdir()
    monkeypatch.setattr(
        "sase.plan_shell.create_plan_gate_shell", lambda *a, **k: creation
    )
    never_called = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(
        "sase.llm_provider._plan_utils.handle_plan_approval", never_called
    )
    monkeypatch.setattr("sase.notification_gates.poller.wait_for_gate", never_called)

    gate_marker_calls: list[dict[str, Any]] = []

    def fake_handle_gate_marker(
        gate_data: dict[str, Any], _ctx: Any, _state: Any
    ) -> str:
        gate_marker_calls.append(gate_data)
        return "gated"

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_gate.handle_gate_marker", fake_handle_gate_marker
    )

    outcome = plan_mod.handle_plan_marker({"plan_file": plan_file}, ctx, state)

    assert outcome == "gated"
    assert state.plan_gate_artifacts_dir == creation.record.artifacts_dir
    assert gate_marker_calls == [
        {
            "gate_id": "plan-1",
            "member_artifacts_dir": str(tmp_path / "gate-member"),
            "member_agent_name": "test_agent--gate",
            "kind": "plan",
        }
    ]
    never_called.assert_not_called()


def test_flag_on_auto_continues_in_process_without_gate_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    plan_file = str(tmp_path / "plan.md")
    monkeypatch.setattr("sase.gate_shell.flag.gate_shell_handoff_enabled", lambda: True)
    creation = _fake_creation(
        gate_state="answered",
        artifacts_dir=str(tmp_path / "gate-member"),
    )
    Path(creation.record.artifacts_dir).mkdir()
    monkeypatch.setattr(
        "sase.plan_shell.create_plan_gate_shell", lambda *a, **k: creation
    )
    monkeypatch.setattr(
        "sase.plan_shell.plan_result_from_gate_creation",
        lambda _creation: PlanApprovalResult(
            action="feedback",
            plan_file=plan_file,
            feedback="Please add tests.",
            auto_approved=True,
        ),
    )
    never_called = MagicMock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr("sase.axe.run_agent_exec_gate.handle_gate_marker", never_called)
    monkeypatch.setattr("sase.notification_gates.poller.wait_for_gate", never_called)

    successor_calls: list[Any] = []
    monkeypatch.setattr(
        plan_mod,
        "continue_as_successor",
        lambda *args, **kwargs: successor_calls.append((args, kwargs)),
    )

    outcome = plan_mod.handle_plan_marker({"plan_file": plan_file}, ctx, state)

    assert outcome is None
    assert state.plan_gate_artifacts_dir == creation.record.artifacts_dir
    assert len(successor_calls) == 1
    successor_request = successor_calls[0][0][2]
    assert "Please add tests." in successor_request.prompt
    never_called.assert_not_called()
