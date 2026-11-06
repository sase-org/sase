"""Tests for completion-notification agent identity and bead display."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_finalize import send_completion_notification

pytest_plugins = ("tests._run_agent_runner_notification_fixtures",)


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


def _write_agent_meta(base_kwargs, payload: object) -> None:
    artifacts_dir = Path(base_kwargs["current_artifacts_dir"])
    artifacts_dir.mkdir(exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload)
    (artifacts_dir / "agent_meta.json").write_text(text)


def _assert_agent_session_facing_identity(
    mock_notify, base_kwargs, *, agent_session: str, shell: str
) -> None:
    notes = mock_notify.call_args.kwargs["notes"]
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert any(f" @{agent_session} " in note for note in notes)
    assert not any(f"@{shell}" in note for note in notes)
    assert action_data["agent_name"] == agent_session
    assert action_data["cl_name"] == base_kwargs["cl_name"]
    assert action_data["raw_suffix"] == base_kwargs["artifacts_timestamp"]


def test_success_completion_notification_names_owning_agent_session(base_kwargs):
    base_kwargs["agent_name"] = "0bw--1"
    _write_agent_meta(
        base_kwargs,
        {"name": "0bw--1", "agent_session": "0bw", "agent_session_role": "1"},
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "JumpToAgent"
    _assert_agent_session_facing_identity(
        mock_notify, base_kwargs, agent_session="0bw", shell="0bw--1"
    )


def test_failure_error_report_notification_names_owning_agent_session(
    base_kwargs, tmp_path
):
    error_report = tmp_path / "error.md"
    error_report.write_text("boom\n")
    base_kwargs["success"] = False
    base_kwargs["error_report_path"] = str(error_report)
    base_kwargs["agent_name"] = "0bw--1"
    _write_agent_meta(
        base_kwargs,
        {"name": "0bw--1", "agent_session": "0bw", "agent_session_role": "1"},
    )

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    assert mock_notify.call_args.kwargs["action"] == "ViewErrorReport"
    _assert_agent_session_facing_identity(
        mock_notify, base_kwargs, agent_session="0bw", shell="0bw--1"
    )


def test_deferred_epic_completion_names_owning_agent_session(base_kwargs):
    base_kwargs["outcome"] = "epic_approved"
    base_kwargs["agent_name"] = "0bw--1"
    _write_agent_meta(
        base_kwargs,
        {"name": "0bw--1", "agent_session": "0bw", "agent_session_role": "1"},
    )

    with (
        patch(
            "sase.bead.epic_launch_handoff.defer_epic_completion", return_value=True
        ) as mock_defer,
        patch("sase.notifications.senders.notify_workflow_complete") as mock_notify,
    ):
        send_completion_notification(**base_kwargs)

    mock_notify.assert_not_called()
    payload = mock_defer.call_args.args[1]
    assert any(" @0bw " in note for note in payload.notes)
    assert not any("@0bw--1" in note for note in payload.notes)
    assert payload.action_data["agent_name"] == "0bw"
    assert payload.action_data["cl_name"] == base_kwargs["cl_name"]
    assert payload.action_data["raw_suffix"] == base_kwargs["artifacts_timestamp"]


def test_completion_notification_bead_display_uses_agent_session_name(
    base_kwargs, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue", lambda _, **__: None
    )
    base_kwargs["agent_name"] = "sase-x.3--1"
    _write_agent_meta(base_kwargs, {"name": "sase-x.3--1", "agent_session": "sase-x.3"})

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    action_data = mock_notify.call_args.kwargs["action_data"]
    assert action_data["agent_name"] == "sase-x.3"
    assert action_data["bead_display"] == "sase-x.3"
    assert action_data["raw_suffix"] == base_kwargs["artifacts_timestamp"]


@pytest.mark.parametrize(
    "meta_payload",
    [
        None,
        "not-json",
        "[]",
        {"agent_session": ""},
        {"agent_session": "   "},
        {"agent_session": None},
        {"agent_session": 0},
    ],
)
def test_completion_notification_keeps_shell_name_without_agent_session_metadata(
    base_kwargs, meta_payload
):
    base_kwargs["agent_name"] = "0bw--1"
    if meta_payload is not None:
        _write_agent_meta(base_kwargs, meta_payload)

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert any(" @0bw--1 " in note for note in notes)
    assert action_data["agent_name"] == "0bw--1"
    assert action_data["raw_suffix"] == base_kwargs["artifacts_timestamp"]


def test_completion_notification_does_not_truncate_dotted_standalone_name(
    base_kwargs, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "sase.agent.bead_display.lookup_bead_issue", lambda _, **__: None
    )
    base_kwargs["agent_name"] = "sase-x.3"

    with patch("sase.notifications.senders.notify_workflow_complete") as mock_notify:
        send_completion_notification(**base_kwargs)

    notes = mock_notify.call_args.kwargs["notes"]
    action_data = mock_notify.call_args.kwargs["action_data"]
    assert any(" @sase-x.3 " in note for note in notes)
    assert not any("@sase-x " in note for note in notes)
    assert action_data["agent_name"] == "sase-x.3"
    assert action_data["raw_suffix"] == base_kwargs["artifacts_timestamp"]
