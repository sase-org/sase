"""Approval-time archiving resolves a real project, and says so when it can't.

Regression coverage for the silent archive outage: ``project_dir`` in plan
action data is an agent *workspace* directory written with a trailing slash, so
``os.path.basename`` on it produced ``""`` and every approval-time archive
raised inside a swallowed warning.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.notifications import Notification
from tests.plan_validation_helpers import VALID_TALE_PLAN
from tests.sdd_policy_helpers import patched_sdd_policy
from tests.workspace_lease_helpers import patched_operational_lease

ArchiveCall = Callable[[Mapping[str, str], Path, str], str | None]


def _archive_via_gate(
    action_data: Mapping[str, str], plan: Path, tier: str
) -> str | None:
    from sase.plan_approval_actions import (
        PlanApprovalActionContext,
        _archive_plan_for_approval,
    )

    context = PlanApprovalActionContext(
        id="plan-approval",
        host_files=(str(plan),),
        host_action_data=dict(action_data),
    )
    return _archive_plan_for_approval(context, tier)


def _archive_via_tui(
    action_data: Mapping[str, str], plan: Path, tier: str
) -> str | None:
    from sase.ace.tui.actions.agents._notification_plan_background import (
        archive_plan_for_approval,
    )

    notification = Notification(
        id="plan-approval",
        timestamp="2026-08-06T12:00:00-04:00",
        sender="plan",
        action="PlanApproval",
        action_data=dict(action_data),
        files=[str(plan)],
    )
    return archive_plan_for_approval(notification, tier)


ARCHIVE_SURFACES: list[tuple[str, ArchiveCall]] = [
    ("gate", _archive_via_gate),
    ("tui", _archive_via_tui),
]


def _plan_file(tmp_path: Path) -> Path:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    return plan


@pytest.mark.parametrize(
    "archive",
    [surface for _, surface in ARCHIVE_SURFACES],
    ids=[name for name, _ in ARCHIVE_SURFACES],
)
def test_archive_resolves_project_from_agent_project_file(
    tmp_path: Path, archive: ArchiveCall
) -> None:
    """The ProjectSpec key, not the workspace basename, drives the lookup."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_file = (
        tmp_path / "projects" / "gh_sase-org__sase" / "gh_sase-org__sase.sase"
    )
    action_data = {
        "agent_project_file": str(project_file),
        # Plan gates write the agent workspace dir, with a trailing slash.
        "project_dir": "/home/agent/workspaces/sase-org/sase/sase_10/",
    }
    seen: list[tuple[str, str]] = []

    with (
        patched_operational_lease(workspace, seen=seen),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
    ):
        saved = archive(action_data, _plan_file(tmp_path), "tale")

    assert seen == [("gh_sase-org__sase", "plan-archive")]
    assert saved == str(workspace / "sdd" / "plans" / "202608" / "plan.md")


@pytest.mark.parametrize(
    "archive",
    [surface for _, surface in ARCHIVE_SURFACES],
    ids=[name for name, _ in ARCHIVE_SURFACES],
)
def test_archive_resolves_project_from_trailing_slash_workspace_dir(
    tmp_path: Path, archive: ArchiveCall
) -> None:
    """A trailing-slash workspace dir no longer resolves to an empty project."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    action_data = {"project_dir": f"{tmp_path / 'workspaces' / 'myproj_10'}/"}
    seen: list[tuple[str, str]] = []

    with (
        patched_operational_lease(workspace, seen=seen),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202608"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
    ):
        saved = archive(action_data, _plan_file(tmp_path), "tale")

    assert seen == [("myproj", "plan-archive")]
    assert saved == str(workspace / "sdd" / "plans" / "202608" / "plan.md")


@pytest.mark.parametrize(
    "archive",
    [surface for _, surface in ARCHIVE_SURFACES],
    ids=[name for name, _ in ARCHIVE_SURFACES],
)
def test_unresolvable_project_is_reported_instead_of_silent(
    tmp_path: Path, archive: ArchiveCall
) -> None:
    """Action data that names no project reports rather than returning quietly."""
    plan = _plan_file(tmp_path)

    with patch("sase._plan_archive_approval.report_plan_archive_failure") as report:
        saved = archive({"session_id": "abc"}, plan, "tale")

    assert saved is None
    report.assert_called_once()
    reported_plan, _action_data, error = report.call_args.args
    assert Path(str(reported_plan)) == plan
    assert "no project could be resolved" in str(error)


@pytest.mark.parametrize(
    "archive",
    [surface for _, surface in ARCHIVE_SURFACES],
    ids=[name for name, _ in ARCHIVE_SURFACES],
)
def test_workspace_lookup_failure_is_reported(
    tmp_path: Path, archive: ArchiveCall
) -> None:
    """Failures below the resolution step are reported too."""
    plan = _plan_file(tmp_path)
    action_data = {"project_dir": f"{tmp_path / 'workspaces' / 'myproj_10'}/"}

    with (
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            side_effect=RuntimeError("no workspace plugin"),
        ),
        patch("sase._plan_archive_approval.report_plan_archive_failure") as report,
    ):
        saved = archive(action_data, plan, "tale")

    assert saved is None
    report.assert_called_once()


def test_report_plan_archive_failure_notifies_the_inbox(tmp_path: Path) -> None:
    """Archive failures reach the notification inbox, not just the log."""
    from sase._plan_archive_approval import (
        PLAN_ARCHIVE_SENDER,
        report_plan_archive_failure,
    )

    plan = _plan_file(tmp_path)
    with patch("sase.notifications.notify_workflow_complete") as notify:
        report_plan_archive_failure(
            plan,
            {"agent_cl_name": "gh_sase-org__sase"},
            RuntimeError("boom"),
        )

    notify.assert_called_once()
    sender, cl_name, success, notes = notify.call_args.args
    assert sender == PLAN_ARCHIVE_SENDER
    assert cl_name == "gh_sase-org__sase"
    assert success is False
    assert any("Failed to archive approved plan" in note for note in notes)
    assert notify.call_args.kwargs["extra_files"] == [str(plan)]
