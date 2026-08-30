"""Golden response-protocol tests for plan approval writers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase._plan_archive_approval import _ApprovedPlanArchive
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalResult
from sase.plan_approval_actions import (
    PlanApprovalActionContext,
    execute_plan_approval_response,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


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
            "tale",
            {"wait": "sase-s7.2,bead=sase-64.3"},
            {
                "action": "approve",
                "commit_plan": True,
                "run_coder": True,
                "wait_agents": ["sase-s7.2"],
                "wait_beads": ["sase-64.3"],
            },
            "Tale approved",
        ),
        (
            "epic",
            {"epic_launch_mode": "skip"},
            {
                "action": "epic",
                "commit_plan": True,
                "run_coder": True,
                "epic_launch_owner": "host",
            },
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
    plan_content = {
        "epic": VALID_EPIC_PLAN,
        "tale": VALID_TALE_PLAN,
    }.get(choice, "# Plan\n")
    plan.write_text(plan_content, encoding="utf-8")
    saved_plan_path = str(tmp_path / "sdd" / "plans" / "202607" / f"{choice}.md")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        return_value=_ApprovedPlanArchive(
            saved_plan_path,
            f"plan:202607/{choice}.md",
        ),
    ):
        result = execute_plan_approval_response(
            _context(tmp_path, response_dir, plan),
            choice,
            **kwargs,
        )

    expected = dict(expected_json)
    if expected.get("action") == "approve" and expected.get("commit_plan") is True:
        expected.update(
            {
                "plan_archive_owner": "host",
                "plan_archive_state": "archived",
                "plan_archive_protocol": "host_v2",
                "plan_archive_ref": f"plan:202607/{choice}.md",
                "saved_plan_path": saved_plan_path,
            }
        )
    elif expected.get("action") in {"approve", "epic"}:
        expected.update(
            {
                "plan_archive_owner": "none",
                "plan_archive_state": "not_requested",
            }
        )
    assert result.message == expected_message
    assert result.response_json == expected
    assert json.loads((response_dir / "plan_response.json").read_text()) == expected


def test_run_choice_skips_plan_archive_side_effect(tmp_path: Path) -> None:
    """Run-only approvals do not publish a committed plan archive."""
    response_dir = _response_dir(tmp_path)
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
    ) as archive:
        result = execute_plan_approval_response(
            _context(tmp_path, response_dir, plan),
            "run",
        )

    assert result.response_json == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
        "plan_archive_owner": "none",
        "plan_archive_state": "not_requested",
    }
    assert json.loads((response_dir / "plan_response.json").read_text()) == (
        result.response_json
    )
    archive.assert_not_called()
    meta = json.loads((response_dir.parent / "agent_meta.json").read_text())
    assert meta == {"plan_approved": True, "plan_action": "approve"}


@pytest.mark.parametrize(
    ("result", "expected_json", "expected_persist_action"),
    [
        (
            PlanApprovalResult(
                action="approve",
                commit_plan=False,
                run_coder=True,
                choice=None,
            ),
            {"action": "approve", "commit_plan": False, "run_coder": True},
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
            "commit",
        ),
        (
            PlanApprovalResult(action="epic", choice=None),
            {"action": "epic", "commit_plan": True, "run_coder": True},
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
            None,
        ),
        (
            PlanApprovalResult(
                action="approve",
                commit_plan=False,
                run_coder=True,
                choice="approve",
            ),
            {
                "action": "approve",
                "commit_plan": False,
                "run_coder": True,
            },
            "approve",
        ),
    ],
)
def test_modal_result_without_choice_fallback_golden_json_and_persist_action(
    result: PlanApprovalResult,
    expected_json: dict[str, object],
    expected_persist_action: str | None,
) -> None:
    from sase.ace.tui.actions.agents._notification_modals import (
        _build_plan_approval_response,
        _plan_approval_persist_action,
    )

    assert _build_plan_approval_response(result) == expected_json
    assert _plan_approval_persist_action(result) == expected_persist_action
