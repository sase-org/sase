"""Tests for axe_run_agent question helper utilities."""

import json
import os
import threading
import time

import pytest

from sase.axe import run_agent_wait
from sase.axe.run_agent_helpers import handle_questions_flow
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    WorkflowStateWire,
)


def _run_questions_flow(
    artifacts_dir,
    questions,
    *,
    kill_after=None,
    send_response_after=None,
    reacquire_runner_slot=None,
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
            request_path = marker_seen.get("payload", {}).get("request_path")
            if session_id and isinstance(request_path, str):
                response_dir = os.path.dirname(request_path)
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
        result = handle_questions_flow(
            questions,
            str(artifacts_dir),
            reacquire_runner_slot=reacquire_runner_slot,
            run_started_at="original-start",
        )
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


def test_answer_keeps_question_marker_until_runner_slot_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active", lambda: False
    )
    monkeypatch.setattr("sase.main.plan_approve_handler.get_tmux_prefix", lambda: "")
    monkeypatch.setattr("sase.main.plan_approve_handler.ring_tmux_bell", lambda: None)
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda title, body: None,
    )
    monkeypatch.setattr(
        "sase.notifications.senders.notify_user_question", lambda **kwargs: None
    )
    marker_path = tmp_path / "pending_question.json"
    observations: list[bool] = []

    def reacquire(claim):
        observations.append(marker_path.exists())
        assert claim() == "original-start"
        observations.append(marker_path.exists())
        return "original-start"

    result, _marker = _run_questions_flow(
        tmp_path,
        [{"question": "do thing?", "options": []}],
        send_response_after={"answers": [], "global_note": ""},
        reacquire_runner_slot=reacquire,
    )

    assert result is not None
    assert observations == [True, False]
    assert not marker_path.exists()


def test_kill_while_answered_question_is_queued_cleans_both_markers(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.is_auto_approve_active", lambda: False
    )
    monkeypatch.setattr("sase.main.plan_approve_handler.get_tmux_prefix", lambda: "")
    monkeypatch.setattr("sase.main.plan_approve_handler.ring_tmux_bell", lambda: None)
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda title, body: None,
    )
    monkeypatch.setattr(
        "sase.notifications.senders.notify_user_question", lambda **kwargs: None
    )
    running_record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(tmp_path / "project"),
        project_file=str(tmp_path / "project" / "proj.gp"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "running"),
        timestamp="20260712115959",
        agent_meta=AgentMetaWire(
            pid=200,
            run_started_at="2026-07-12T11:59:59Z",
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=True),
    )
    kill_checks = iter((False, True))
    monkeypatch.setattr(
        run_agent_wait,
        "_scan_runner_slot_records",
        lambda: [running_record],
    )
    monkeypatch.setattr(run_agent_wait, "is_process_alive", lambda *args: True)
    monkeypatch.setattr(run_agent_wait, "get_max_running_agents", lambda: 1)
    monkeypatch.setattr(
        run_agent_wait,
        "update_agent_artifact_index_for_marker_mutation",
        lambda path: None,
    )
    monkeypatch.setattr(
        run_agent_wait,
        "was_killed",
        lambda: next(kill_checks, True),
    )
    monkeypatch.setattr(run_agent_wait, "_RUNNER_SLOT_POLL_INTERVAL", 0)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))

    def reacquire(claim):
        return run_agent_wait.wait_for_runner_slot(
            str(tmp_path),
            "proj",
            "20260712120000",
            {"pid": 100, "run_started_at": "original-start"},
            wait_runners=None,
            claim=claim,
        )

    with pytest.raises(SystemExit, match="143"):
        _run_questions_flow(
            tmp_path,
            [{"question": "do thing?", "options": []}],
            send_response_after={"answers": [], "global_note": ""},
            reacquire_runner_slot=reacquire,
        )

    assert not (tmp_path / "pending_question.json").exists()
    assert not (tmp_path / "waiting.json").exists()


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
