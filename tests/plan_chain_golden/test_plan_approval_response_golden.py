"""Golden response-protocol tests for plan approval writers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.modals.plan_approval_modal import PlanApprovalResult
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    execute_plan_approval_response,
)


def _response_dir(root: Path) -> Path:
    response_dir = root / "agent" / "plan_approval"
    response_dir.mkdir(parents=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    (response_dir.parent / "agent_meta.json").write_text("{}", encoding="utf-8")
    return response_dir


def _context(
    tmp_path: Path, response_dir: Path, plan: Path
) -> PlanApprovalActionContext:
    return PlanApprovalActionContext(
        id="notif-abcdef12",
        host_files=(str(plan),),
        host_action_data={
            "response_dir": str(response_dir),
            "project_dir": str(tmp_path / "workspace"),
        },
    )


@pytest.mark.parametrize(
    ("choice", "kwargs", "expected_json", "expected_message"),
    [
        (
            "approve",
            {},
            {"action": "approve", "commit_plan": False, "run_coder": True},
            "Plan approved",
        ),
        (
            "run",
            {},
            {"action": "approve", "commit_plan": False, "run_coder": True},
            "Running coder",
        ),
        (
            "tale",
            {"coder_prompt": "#review+", "coder_model": "worker"},
            {
                "action": "approve",
                "commit_plan": True,
                "run_coder": True,
                "coder_prompt": "#review+",
                "coder_model": "worker",
            },
            "Tale approved",
        ),
        (
            "epic",
            {},
            {"action": "epic", "commit_plan": True, "run_coder": True},
            "Epic approved",
        ),
        (
            "commit",
            {},
            {"action": "approve", "commit_plan": True, "run_coder": False},
            "Plan committed",
        ),
        ("reject", {}, {"action": "reject"}, "Plan rejected"),
        (
            "feedback",
            {"feedback": "Tighten scope"},
            {"action": "reject", "feedback": "Tighten scope"},
            "Feedback received",
        ),
    ],
)
def test_shared_plan_response_writer_golden_json(
    tmp_path: Path,
    choice: str,
    kwargs: dict[str, object],
    expected_json: dict[str, object],
    expected_message: str,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = tmp_path / f"{choice}.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval", return_value=None
    ):
        result = execute_plan_approval_response(
            _context(tmp_path, response_dir, plan),
            choice,
            **kwargs,
        )

    assert result.message == expected_message
    assert result.response_json == expected_json
    assert (
        json.loads((response_dir / "plan_response.json").read_text()) == expected_json
    )


def test_run_choice_archives_plan_side_effect(tmp_path: Path) -> None:
    """Telegram/mobile run approvals participate in plan archive side effects."""
    response_dir = _response_dir(tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    saved_plan_path = str(tmp_path / "sdd" / "plans" / "202607" / "plan.md")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        return_value=saved_plan_path,
    ) as archive:
        result = execute_plan_approval_response(
            _context(tmp_path, response_dir, plan),
            "run",
        )

    assert result.response_json == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
        "saved_plan_path": saved_plan_path,
    }
    assert json.loads((response_dir / "plan_response.json").read_text()) == (
        result.response_json
    )
    archive.assert_called_once()
    assert archive.call_args.args[1] == "approve"
    meta = json.loads((response_dir.parent / "agent_meta.json").read_text())
    assert meta == {"plan_approved": True, "plan_action": "approve"}


def test_shared_plan_response_writer_includes_selected_members(
    tmp_path: Path,
) -> None:
    response_dir = _response_dir(tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval", return_value=None
    ):
        result = execute_plan_approval_response(
            _context(tmp_path, response_dir, plan),
            "approve",
            selected_member_ids=("tester",),
        )

    assert result.response_json == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
        "selected_member_ids": ["tester"],
    }


@pytest.mark.parametrize(
    ("result", "expected_json", "expected_status", "expected_persist_action"),
    [
        (
            PlanApprovalResult(
                action="approve",
                commit_plan=False,
                run_coder=True,
                choice=None,
            ),
            {"action": "approve", "commit_plan": False, "run_coder": True},
            "PLAN APPROVED",
            "approve",
        ),
        (
            PlanApprovalResult(
                action="approve",
                commit_plan=True,
                run_coder=True,
                choice=None,
            ),
            {"action": "approve", "commit_plan": True, "run_coder": True},
            "TALE APPROVED",
            "tale",
        ),
        (
            PlanApprovalResult(
                action="approve",
                commit_plan=True,
                run_coder=False,
                choice=None,
            ),
            {"action": "approve", "commit_plan": True, "run_coder": False},
            "PLAN COMMITTED",
            "commit",
        ),
        (
            PlanApprovalResult(action="epic", choice=None),
            {"action": "epic", "commit_plan": True, "run_coder": True},
            "EPIC APPROVED",
            "epic",
        ),
        (
            PlanApprovalResult(action="reject", feedback="Try again", choice=None),
            {
                "action": "reject",
                "feedback": "Try again",
                "commit_plan": True,
                "run_coder": True,
            },
            "RUNNING",
            None,
        ),
        (
            PlanApprovalResult(
                action="approve",
                commit_plan=False,
                run_coder=True,
                choice="approve",
                selected_member_ids=("tester",),
            ),
            {
                "action": "approve",
                "commit_plan": False,
                "run_coder": True,
                "selected_member_ids": ["tester"],
            },
            "PLAN APPROVED",
            "approve",
        ),
    ],
)
def test_modal_result_without_choice_fallback_golden_json_and_labels(
    result: PlanApprovalResult,
    expected_json: dict[str, object],
    expected_status: str,
    expected_persist_action: str | None,
) -> None:
    from sase.ace.tui.actions.agents._notification_modals import (
        _build_plan_approval_response,
        _plan_approval_persist_action,
        _plan_approval_status,
    )

    assert _build_plan_approval_response(result) == expected_json
    assert _plan_approval_status(result) == expected_status
    assert _plan_approval_persist_action(result) == expected_persist_action
