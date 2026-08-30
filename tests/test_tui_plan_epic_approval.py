"""Tests for epic approval handling in the TUI."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.modals.plan_approval_results import (
    plan_approval_result_for_choice,
)
from sase.plan_approval_actions import PlanApprovalActionError
from tests._plan_approval_tui_helpers import (
    make_approval_app_and_notification,
    run_tracked_procs_immediately,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def test_tui_failed_epic_gate_keeps_response_unconsumed_until_fixed(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
        tmp_path
    )
    plan = Path(notification.files[0])

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with patch(
        "sase.ace.tui.actions.agents._notification_navigation."
        "find_agent_for_notification",
        return_value=mock_agent,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]

        on_dismiss(plan_approval_result_for_choice("epic"))

        assert not (response_dir / "plan_response.json").exists()
        assert (response_dir / "plan_request.json").is_file()
        assert "approval blocked" in app.notify.call_args.kwargs["title"].lower()

        plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
        on_dismiss(plan_approval_result_for_choice("epic"))

    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["action"] == "epic"


def test_tui_epic_approval_uses_shared_detached_launch(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")
    plan_response_path = response_dir / "plan_response.json"
    order: list[str] = []
    tracked_procs = run_tracked_procs_immediately(app)

    def submit(*_args: object, **_kwargs: object) -> object:
        response = json.loads(plan_response_path.read_text(encoding="utf-8"))
        assert response["epic_launch_owner"] == "host"
        assert response["wait_agents"] == ["sase-s7.2"]
        assert response["wait_beads"] == ["sase-64.3"]
        wait_spec: Any = _kwargs["wait_spec"]
        assert wait_spec.agents == ("sase-s7.2",)
        assert wait_spec.beads == ("sase-64.3",)
        order.append("detached")
        return object()

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation."
            "find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            side_effect=submit,
        ),
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(
            plan_approval_result_for_choice(
                "epic",
                wait_spec="sase-s7.2,bead=sase-64.3",
            )
        )

    response = json.loads(plan_response_path.read_text(encoding="utf-8"))
    assert order == ["detached"]
    assert [task["proc_type"] for task in tracked_procs] == ["launch"]
    assert tracked_procs[0]["dedup_key"] == "legacy-epic-launch:test-notif"
    assert response["epic_launch_owner"] == "host"
    assert response["wait_agents"] == ["sase-s7.2"]
    assert response["wait_beads"] == ["sase-64.3"]


def test_tui_epic_launch_preflight_runs_only_inside_tracked_task(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")
    submitted: list[dict[str, Any]] = []

    def capture_task(
        proc_type: str,
        proc_callable: Any,
        **kwargs: Any,
    ) -> object:
        submitted.append(
            {
                "proc_type": proc_type,
                "cl_name": kwargs.get("cl_name"),
                "project_file": kwargs.get("project_file"),
                "proc_callable": proc_callable,
                "kwargs": kwargs,
            }
        )
        return object()

    app._submit_session_worker.side_effect = capture_task

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation."
            "find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch("sase.plan_approval_actions.prepare_epic_launch") as prepare_launch,
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(plan_approval_result_for_choice("epic"))

        prepare_launch.assert_not_called()

    response = json.loads((response_dir / "plan_response.json").read_text())
    assert response["epic_launch_owner"] == "host"
    assert submitted[0]["proc_type"] == "launch"
    assert submitted[0]["kwargs"]["dedup_key"] == "legacy-epic-launch:test-notif"


def test_tui_epic_submission_failure_is_loud_and_keeps_host_owner(
    tmp_path: Path,
) -> None:
    app, notification, response_dir, mock_agent = make_approval_app_and_notification(
        tmp_path
    )
    Path(notification.files[0]).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    notification.action_data["project_dir"] = str(tmp_path / "workspace")
    run_tracked_procs_immediately(app)

    from sase.ace.tui.actions.agents._notification_modals import (
        handle_plan_approval,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._notification_navigation."
            "find_agent_for_notification",
            return_value=mock_agent,
        ),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            side_effect=PlanApprovalActionError(
                "epic_launch_failed",
                str(notification.files[0]),
                "could not start; resume with `sase bead work plan.md --yes-to-all`",
            ),
        ),
    ):
        handle_plan_approval(app, notification)
        on_dismiss = app.push_screen.call_args.args[1]
        on_dismiss(plan_approval_result_for_choice("epic"))

    response = json.loads(
        (response_dir / "plan_response.json").read_text(encoding="utf-8")
    )
    assert response["epic_launch_owner"] == "host"
    app.notify.assert_any_call(
        "could not start; resume with `sase bead work plan.md --yes-to-all`",
        title="Epic launch failed",
        severity="error",
        timeout=15,
    )
