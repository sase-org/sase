"""Tests for axe_run_agent question helper utilities."""

import json
import os
import threading
import time

from sase.axe.run_agent_helpers import handle_questions_flow


def _run_questions_flow(
    artifacts_dir,
    questions,
    *,
    kill_after=None,
    send_response_after=None,
):
    """Run handle_questions_flow with stubs and return (result, marker_during_poll)."""
    marker_path = os.path.join(str(artifacts_dir), "pending_question.json")
    marker_seen: dict[str, dict] = {}

    def _respond_or_kill() -> None:
        time.sleep(0.05)
        # Snapshot marker existence and contents during the poll loop.
        if os.path.exists(marker_path):
            try:
                with open(marker_path, encoding="utf-8") as f:
                    marker_seen["payload"] = json.load(f)
            except (OSError, json.JSONDecodeError):
                marker_seen["payload"] = {}
        if send_response_after is not None:
            session_id = marker_seen.get("payload", {}).get("session_id")
            if session_id:
                response_dir = os.path.expanduser(f"~/.sase/user_question/{session_id}")
                with open(
                    os.path.join(response_dir, "question_response.json"),
                    "w",
                    encoding="utf-8",
                ) as f:
                    json.dump(send_response_after, f)
        if kill_after is not None:
            kill_after()

    helper_thread = threading.Thread(target=_respond_or_kill)
    helper_thread.start()
    try:
        result = handle_questions_flow(questions, str(artifacts_dir))
    finally:
        helper_thread.join()
    return result, marker_seen.get("payload")


def test_pending_question_marker_created_during_poll_and_deleted_on_response(
    tmp_path, monkeypatch
):
    """Marker is written before the poll loop and deleted after a response."""
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active",
        lambda: False,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.get_tmux_prefix",
        lambda: "",
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.ring_tmux_bell",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda title, body: None,
    )
    monkeypatch.setattr(
        "sase.notifications.senders.notify_user_question",
        lambda **kwargs: None,
    )

    questions = [{"question": "do thing?", "options": []}]
    result, marker_payload = _run_questions_flow(
        tmp_path,
        questions,
        send_response_after={"answers": [], "global_note": ""},
    )

    assert result is not None
    assert result["answers"] == []
    assert result["global_note"] == ""
    assert marker_payload is not None
    assert marker_payload["session_id"] == result["_question_session_id"]
    assert marker_payload["request_path"] == result["_question_request_path"]
    assert "submitted_at" in marker_payload
    # Marker is cleaned up after the poll loop exits.
    assert not (tmp_path / "pending_question.json").exists()


def test_pending_question_marker_updates_artifact_index_on_create_and_delete(
    tmp_path, monkeypatch
):
    """Question marker writes and cleanup both refresh the artifact index."""
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active",
        lambda: False,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.get_tmux_prefix",
        lambda: "",
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.ring_tmux_bell",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda title, body: None,
    )
    monkeypatch.setattr(
        "sase.notifications.senders.notify_user_question",
        lambda **kwargs: None,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.axe.run_agent_helpers.update_agent_artifact_index_for_marker_mutation",
        lambda path: calls.append(path),
    )

    result, _marker_payload = _run_questions_flow(
        tmp_path,
        [{"question": "do thing?", "options": []}],
        send_response_after={"answers": [], "global_note": ""},
    )

    assert result is not None
    assert calls == [str(tmp_path), str(tmp_path)]


def test_questions_flow_passes_agent_root_timestamp(tmp_path, monkeypatch):
    """Question notifications include both phase and root routing timestamps."""
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active",
        lambda: False,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.get_tmux_prefix",
        lambda: "",
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.ring_tmux_bell",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda title, body: None,
    )
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260512094333")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260512090000")
    captured_kwargs: dict[str, object] = {}

    def _capture_notify(**kwargs: object) -> None:
        captured_kwargs.update(kwargs)

    monkeypatch.setattr(
        "sase.notifications.senders.notify_user_question",
        _capture_notify,
    )

    questions = [{"question": "do thing?", "options": []}]
    result, _marker_payload = _run_questions_flow(
        tmp_path,
        questions,
        send_response_after={"answers": [], "global_note": ""},
    )

    assert result is not None
    assert captured_kwargs["agent_timestamp"] == "20260512094333"
    assert captured_kwargs["agent_root_timestamp"] == "20260512090000"


def test_pending_question_marker_deleted_on_kill(tmp_path, monkeypatch):
    """Marker is deleted via the finally block even when the agent is killed."""
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active",
        lambda: False,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.get_tmux_prefix",
        lambda: "",
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.ring_tmux_bell",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda title, body: None,
    )
    monkeypatch.setattr(
        "sase.notifications.senders.notify_user_question",
        lambda **kwargs: None,
    )

    kill_flag = {"killed": False}
    monkeypatch.setattr(
        "sase.axe.run_agent_helpers.was_killed",
        lambda: kill_flag["killed"],
    )

    def _trigger_kill():
        kill_flag["killed"] = True

    questions = [{"question": "do thing?", "options": []}]
    result, marker_payload = _run_questions_flow(
        tmp_path,
        questions,
        kill_after=_trigger_kill,
    )

    assert result is None
    assert marker_payload is not None  # Existed during the poll
    assert not (tmp_path / "pending_question.json").exists()


def test_pending_question_marker_not_written_for_auto_approve(tmp_path, monkeypatch):
    """Auto-approve short-circuit never reaches the marker-writing path."""
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active",
        lambda: True,
    )

    questions = [
        {
            "question": "ok?",
            "options": [{"label": "yes"}, {"label": "no"}],
        }
    ]
    result = handle_questions_flow(questions, str(tmp_path))

    assert result == {
        "answers": [
            {"question": "ok?", "selected": ["yes"], "custom_feedback": None},
        ],
        "global_note": "",
    }
    assert not (tmp_path / "pending_question.json").exists()
