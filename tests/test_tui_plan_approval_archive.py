"""Tests for archiving plans approved in the TUI."""

from pathlib import Path
from unittest.mock import patch

from sase.notifications import Notification
from tests.sdd_policy_helpers import patched_sdd_policy
from tests.workspace_lease_helpers import patched_operational_lease


def test_archive_plan_for_approval_uses_version_controlled_sdd_dir(
    tmp_path: Path,
) -> None:
    """Version-controlled approval archiving writes under sdd/plans/YYYYMM."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="test-notif",
        timestamp="2026-05-01T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"project_dir": str(workspace)},
        files=[str(plan_file)],
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        _archive_plan_for_approval,
    )

    with (
        patched_operational_lease(workspace),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.get_yyyymm", return_value="202605"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
    ):
        saved = _archive_plan_for_approval(notification, "epic")

    assert saved == str(workspace / "sdd" / "plans" / "202605" / "plan.md")
    assert Path(saved).read_text(encoding="utf-8").startswith("---\ncreate_time:")
    assert "tier: epic" in Path(saved).read_text(encoding="utf-8")
    assert not (workspace / ".sase" / "sdd" / "plans").exists()
    ensure_sdd.assert_called_once_with(
        str(workspace),
        commit=True,
        push=False,
    )


def test_archive_plan_for_approval_passes_expect_prompt_snapshot_for_epic(
    tmp_path: Path,
) -> None:
    """Epic approvals opt in to the guaranteed prompt snapshot mode."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="test-notif",
        timestamp="2026-05-01T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"project_dir": str(workspace)},
        files=[str(plan_file)],
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        _archive_plan_for_approval,
    )

    with (
        patched_operational_lease(workspace),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.sdd.plan_archive.archive_plan_file",
            side_effect=Exception("stop before write"),
        ) as archive_plan_file,
    ):
        _archive_plan_for_approval(notification, "epic")

    assert archive_plan_file.call_args.kwargs["expect_prompt_snapshot"] is True


def test_archive_plan_for_approval_passes_expect_prompt_snapshot_for_tale(
    tmp_path: Path,
) -> None:
    """Tale approvals keep the default probe-based prompt link resolution."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="test-notif",
        timestamp="2026-05-01T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"project_dir": str(workspace)},
        files=[str(plan_file)],
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        _archive_plan_for_approval,
    )

    with (
        patched_operational_lease(workspace),
        patched_sdd_policy("in_tree"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized"),
        patch(
            "sase.sdd.plan_archive.archive_plan_file",
            side_effect=Exception("stop before write"),
        ) as archive_plan_file,
    ):
        _archive_plan_for_approval(notification, "approve")

    assert archive_plan_file.call_args.kwargs["expect_prompt_snapshot"] is False


def test_archive_plan_for_approval_uses_local_sdd_dir(tmp_path: Path) -> None:
    """Local SDD approval archiving uses .sase/sdd/plans/YYYYMM."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    notification = Notification(
        id="test-notif",
        timestamp="2026-05-01T12:00:00-04:00",
        sender="test",
        action="PlanApproval",
        action_data={"project_dir": str(workspace)},
        files=[str(plan_file)],
    )

    from sase.ace.tui.actions.agents._notification_modals import (
        _archive_plan_for_approval,
    )

    with (
        patched_operational_lease(workspace),
        patched_sdd_policy("local"),
        patch("sase.sdd.files.get_yyyymm", return_value="202605"),
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
    ):
        saved = _archive_plan_for_approval(notification, "approve")

    assert saved == str(workspace / ".sase" / "sdd" / "plans" / "202605" / "plan.md")
    assert Path(saved).exists()
    assert "tier: tale" in Path(saved).read_text(encoding="utf-8")
    ensure_sdd.assert_not_called()
