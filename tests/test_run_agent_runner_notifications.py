"""Tests for run-agent-runner completion-notification behavior and metadata."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_finalize import (
    classify_exec_success,
    send_completion_notification,
)

pytest_plugins = ("tests._run_agent_runner_notification_fixtures",)


def test_hidden_agent_forwards_silent_true(base_kwargs):
    base_kwargs["agent_hidden"] = True
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_count == 1
    assert mock_notify.call_args.kwargs["silent"] is True


def test_visible_agent_forwards_silent_false(base_kwargs):
    base_kwargs["agent_hidden"] = False
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_count == 1
    assert mock_notify.call_args.kwargs["silent"] is False


def test_failed_notification_includes_held_workspace_recovery(base_kwargs):
    base_kwargs.update(
        success=False,
        held_workspace_num=17,
        held_workspace_dir="/tmp/workspace-17",
    )
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    assert any("Workspace #17 is held at /tmp/workspace-17" in note for note in notes)
    assert any("dismiss this agent to release it" in note for note in notes)


def test_success_completion_notification_includes_runtime(base_kwargs):
    base_kwargs["runtime"] = "4m32s"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["runtime"] == "4m32s"


def test_success_completion_notification_includes_output_variables(base_kwargs):
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "output_variables": {
                    "report_path": "dist/report.md",
                    "results": {
                        "passed": True,
                        "scores": [98, 100],
                        "summary": None,
                    },
                    "status": "ok",
                    "STOP": {"reason": "reserved control value"},
                }
            }
        )
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["output_variables"] == (
        '{"report_path": "dist/report.md", "results": {"passed": true, '
        '"scores": [98, 100], "summary": null}, "status": "ok"}'
    )
    assert json.loads(action_data["output_variables"]) == {
        "report_path": "dist/report.md",
        "results": {
            "passed": True,
            "scores": [98, 100],
            "summary": None,
        },
        "status": "ok",
    }


def test_completion_notification_omits_empty_output_variables(base_kwargs):
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"STOP": "1"}})
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert "output_variables" not in action_data


def test_success_completion_notification_tags_done(base_kwargs):
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "JumpToAgent"
    assert mock_notify.call_args.kwargs["tags"] == ["done"]


def test_failure_completion_notification_is_not_tagged_done(base_kwargs, tmp_path):
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    base_kwargs["success"] = False
    base_kwargs["error_report_path"] = str(error_report)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    assert mock_notify.call_args.kwargs["tags"] is None


def test_completion_notification_uses_full_commit_result_message(base_kwargs):
    full_message = "feat: add report\n\nInclude full commit body."
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "commit_result.json").write_text(
        json.dumps({"message": full_message, "result": "abc123"})
    )
    base_kwargs["step_output"] = {"meta_commit_message": "feat: add report"}

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["commit_message"] == full_message


def test_completion_notification_reads_commit_result_without_step_output(base_kwargs):
    full_message = "fix: recover after failure\n\nCommit happened before failure."
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "commit_result.json").write_text(
        json.dumps({"message": full_message, "result": "abc123"})
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["commit_message"] == full_message


def test_hidden_agent_failure_still_silent(base_kwargs):
    """Hidden runs are silent for failures too — matches sibling runners."""
    base_kwargs["agent_hidden"] = True
    base_kwargs["success"] = False
    base_kwargs["error_summary"] = "boom"
    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["silent"] is True
    assert mock_notify.call_args.kwargs["success"] is False


def test_plan_rejected_suppresses_completion_notification(base_kwargs):
    base_kwargs["success"] = True
    base_kwargs["outcome"] = "plan_rejected"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    mock_notify.assert_not_called()


def test_plan_rejected_classifies_as_runner_success():
    assert classify_exec_success(success=False, outcome="plan_rejected") is True


def test_epic_approved_classifies_as_runner_success():
    assert classify_exec_success(success=False, outcome="epic_approved") is True


def _write_sdd_publication_error(base_kwargs, error: str) -> None:
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"sdd_publication_error": error})
    )


def test_sdd_publication_error_rides_deferred_epic_completion(base_kwargs):
    """A degraded planner publication is reported by the epic's notification."""
    base_kwargs["outcome"] = "epic_approved"
    _write_sdd_publication_error(base_kwargs, "plans store is mid-rebase")

    with (
        patch(
            "sase.bead.epic_launch_handoff.defer_epic_completion", return_value=True
        ) as mock_defer,
        patch("sase.notifications.senders.notify_workflow_complete") as mock_notify,
    ):
        send_completion_notification(**base_kwargs)

    mock_notify.assert_not_called()
    mock_defer.assert_called_once()
    payload = mock_defer.call_args.args[1]
    assert any(
        "plans store is mid-rebase" in note and "prompt archive entry" in note
        for note in payload.notes
    )
    assert any("epic launch is unaffected" in note for note in payload.notes)


def test_epic_approved_without_publication_error_has_no_degraded_note(base_kwargs):
    base_kwargs["outcome"] = "epic_approved"

    with (
        patch(
            "sase.bead.epic_launch_handoff.defer_epic_completion", return_value=True
        ) as mock_defer,
        patch("sase.notifications.senders.notify_workflow_complete"),
    ):
        send_completion_notification(**base_kwargs)

    mock_defer.assert_called_once()
    payload = mock_defer.call_args.args[1]
    assert not any("prompt archive entry" in note for note in payload.notes)


def test_real_failure_stays_runner_failure():
    assert classify_exec_success(success=False, outcome="killed") is False


def test_completion_notification_adds_bead_display_for_bead_agent(
    base_kwargs, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue", lambda _, **__: None
    )
    base_kwargs["agent_name"] = "sase-x.3"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["bead_display"] == "sase-x.3"


def test_completion_notification_omits_bead_display_for_ordinary_agent(base_kwargs):
    base_kwargs["agent_name"] = "reviewer"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert "bead_display" not in action_data


def test_failure_error_report_notification_adds_bead_display(
    base_kwargs, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue", lambda _, **__: None
    )
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    chat = tmp_path / "chat.md"
    diff = tmp_path / "diff.diff"
    base_kwargs["success"] = False
    base_kwargs["agent_name"] = "sase-x.3"
    base_kwargs["error_report_path"] = str(error_report)
    base_kwargs["saved_path"] = str(chat)
    base_kwargs["diff_path"] = str(diff)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    assert mock_notify.call_args.kwargs["extra_files"][:3] == [
        str(error_report),
        str(chat),
        str(diff),
    ]
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["bead_display"] == "sase-x.3"


def test_failure_error_report_notification_includes_runtime(base_kwargs, tmp_path):
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    base_kwargs["success"] = False
    base_kwargs["error_report_path"] = str(error_report)
    base_kwargs["runtime"] = "1m05s"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["runtime"] == "1m05s"


def test_failure_error_report_notification_includes_output_variables(
    base_kwargs, tmp_path
):
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"output_variables": {"summary_path": "reports/error.md"}})
    )
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    base_kwargs["success"] = False
    base_kwargs["error_report_path"] = str(error_report)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert json.loads(action_data["output_variables"]) == {
        "summary_path": "reports/error.md"
    }
