"""Execution and bundle-integrity coverage for notification gates."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest

from sase.notification_gates.durability import file_lock, request_sha256
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.failure_notifications import GATE_EXECUTION_FAILED_ACTION
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.models import GateError
from sase.notification_gates.poller import poll_gate
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from tests._notification_gates_fixtures import custom_gate_spec, gate_spec


def test_custom_gate_runs_selected_options_in_query_order_and_persists_feedback(
    gate_home: Path,
) -> None:
    result = create_gate(custom_gate_spec(feedback="required"))

    with pytest.raises(GateError) as missing_feedback:
        execute_gate_selection(result.bundle_path, ["proceed"])
    assert missing_feedback.value.code == "feedback_required"
    assert not result.response_path.exists()

    started: list[str] = []
    with pytest.raises(GateError) as failed_command:
        execute_gate_selection(
            result.bundle_path,
            ["broken", "audit", "proceed"],
            {"reviewed": True},
            feedback="Ship it carefully",
            on_command_start=lambda _kind, option_id, _label, _argv: started.append(
                option_id
            ),
        )
    assert failed_command.value.code == "command_failed"
    assert started == ["proceed", "audit", "broken"]
    assert not result.response_path.exists()
    recorded = [
        json.loads(path.read_text())
        for path in (result.bundle_path / "errors").glob("*.json")
    ]
    assert {(entry["code"], entry["option_id"]) for entry in recorded} == {
        ("feedback_required", "proceed"),
        ("command_failed", "broken"),
    }

    execution = execute_gate_selection(
        result.bundle_path,
        ["audit", "proceed"],
        {"reviewed": True},
        feedback="  Ship it carefully  ",
    )

    assert execution.response["selected_option_ids"] == ["proceed", "audit"]
    assert execution.response["feedback"] == "Ship it carefully"
    assert execution.response["option_results"] == [
        {"id": "proceed", "result": {"status": "ok"}},
        {"id": "audit", "result": {"audit": {"reviewed": True}}},
    ]
    assert result.response_path.is_file()

    terminal = poll_gate(result.bundle_path)
    assert terminal is not None
    assert terminal.selected_option_ids == ("proceed", "audit")
    assert terminal.feedback == "Ship it carefully"


def test_custom_gate_rejects_invalid_selections_and_disabled_feedback(
    gate_home: Path,
) -> None:
    result = create_gate(custom_gate_spec(feedback="disabled"))
    with pytest.raises(GateError) as unknown_option:
        execute_gate_selection(
            result.bundle_path,
            ["missing"],
        )
    assert unknown_option.value.code == "unknown_option"
    with pytest.raises(GateError) as cross_branch:
        cross_branch_spec = custom_gate_spec(request_id="cross-branch")
        cross_branch_spec["query"] = "proceed OR audit OR broken"
        cross_branch_spec["primary_branch"] = ["proceed"]
        cross_branch_spec["groups"] = []
        cross_branch_result = create_gate(cross_branch_spec)
        execute_gate_selection(cross_branch_result.bundle_path, ["proceed", "audit"])
    assert cross_branch.value.code == "selection_crosses_branches"
    with pytest.raises(GateError) as disabled_feedback:
        execute_gate_selection(
            result.bundle_path,
            ["proceed"],
            feedback="not allowed",
        )
    assert disabled_feedback.value.code == "feedback_not_allowed"
    assert not result.response_path.exists()


def test_execute_selection_validates_input_and_writes_response_once(
    gate_home: Path,
) -> None:
    result = create_gate(gate_spec())

    first = execute_gate_selection(result.bundle_path, ["accept"], {"reviewed": True})
    second = execute_gate_selection(result.bundle_path, ["accept"], {"reviewed": False})

    assert first.already_completed is False
    assert first.response["option_results"] == [
        {
            "id": "accept",
            "result": {"status": "ok", "input": {"reviewed": True}},
        }
    ]
    assert second.already_completed is True
    assert second.response == first.response
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    assert entry["state"] == "already_handled"


def test_custom_gate_answer_dismisses_notification_and_settles_pending_action(
    gate_home: Path,
) -> None:
    created = create_gate(custom_gate_spec(request_id="dismiss-custom"))

    execute_gate_selection(created.bundle_path, ["proceed", "audit"])

    [notification] = load_notifications(include_dismissed=True)
    assert notification.id == created.notification_id
    assert notification.dismissed is True
    assert load_notifications() == []
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    assert entry["state"] == "already_handled"


def test_neutral_hitl_answer_dismisses_notification(gate_home: Path) -> None:
    created = create_gate(gate_spec(request_id="dismiss-hitl"))

    execute_gate_selection(created.bundle_path, ["accept"])

    [notification] = load_notifications(include_dismissed=True)
    assert notification.id == created.notification_id
    assert notification.dismissed is True
    assert load_notifications() == []


def test_cancel_gate_dismisses_notification(gate_home: Path) -> None:
    created = create_gate(gate_spec(request_id="dismiss-cancelled"))

    cancellation = cancel_gate(created.bundle_path, source="test")

    assert cancellation["source"] == "test"
    [notification] = load_notifications(include_dismissed=True)
    assert notification.id == created.notification_id
    assert notification.dismissed is True
    assert load_notifications() == []


def test_execution_failure_polls_failed_and_dedupes_recovery_notification(
    gate_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail_sentinel = tmp_path / "fail"
    fail_sentinel.write_text("1", encoding="utf-8")
    monkeypatch.setenv("GATE_TEST_FAIL_SENTINEL", str(fail_sentinel))
    command = (
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "json.load(sys.stdin)\n"
        "if os.path.exists(os.environ['GATE_TEST_FAIL_SENTINEL']):\n"
        "    sys.stderr.write('nope')\n"
        "    raise SystemExit(7)\n"
        "print(json.dumps({'status': 'ok'}))\n"
    )
    created = create_gate(gate_spec(request_id="failure-notify", command=command))

    with pytest.raises(GateError) as failed:
        execute_gate_selection(created.bundle_path, ["accept"], {})
    assert failed.value.code == "command_failed"

    first = poll_gate(created.bundle_path)
    second = poll_gate(created.bundle_path)
    assert first is not None
    assert first.status == "failed"
    assert first.failure is not None
    assert first.failure["code"] == "command_failed"
    assert second is not None
    assert second.status == "failed"

    failures = [
        notification
        for notification in load_notifications()
        if notification.action == GATE_EXECUTION_FAILED_ACTION
    ]
    assert len(failures) == 1
    failure = failures[0]
    assert failure.tags == ["gate", "execution", "error"]
    assert failure.action_data["request_id"] == "failure-notify"
    assert failure.action_data["request_kind"] == "hitl"
    assert failure.action_data["gate_ref"] == "hitl/failure-notify"
    assert failure.action_data["stage"] == "command"
    assert failure.action_data["message"]
    assert "nope" not in failure.action_data["message"]
    assert failure.action_data["error_report_path"].endswith(
        failure.action_data["error_record"]
    )
    assert Path(failure.action_data["error_report_path"]).is_file()
    assert failure.action_data["recovery_actions"] == "resume,restart,cancel"
    assert (
        failure.action_data["resume_command"]
        == "sase gate answer --kind hitl --id failure-notify --option accept --resume"
    )
    assert (
        failure.action_data["restart_command"]
        == "sase gate answer --kind hitl --id failure-notify --option accept --restart"
    )
    assert (
        failure.action_data["cancel_command"]
        == "sase gate cancel --kind hitl --id failure-notify"
    )
    namespace = uuid5(
        NAMESPACE_URL, "https://sase.dev/notifications/gate-execution-failed"
    )
    assert failure.id == str(
        uuid5(
            namespace,
            f"hitl\x00failure-notify\x00{failure.action_data['acceptance_id']}",
        )
    )

    fail_sentinel.unlink()
    recovered = execute_gate_selection(
        created.bundle_path, ["accept"], {}, retry="restart"
    )
    assert recovered.response["selected_option_ids"] == ["accept"]

    rows = load_notifications(include_dismissed=True)
    [failure_after_success] = [
        notification
        for notification in rows
        if notification.action == GATE_EXECUTION_FAILED_ACTION
    ]
    assert failure_after_success.dismissed is True


def test_cancel_gate_does_not_block_behind_a_running_command_response_lock(
    gate_home: Path,
) -> None:
    created = create_gate(gate_spec(request_id="cancel-lock-timeout"))
    lock_path = created.bundle_path / ".response.lock"
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def _hold_lock_like_a_running_option_command() -> None:
        with file_lock(lock_path):
            holder_ready.set()
            release_holder.wait(timeout=5)

    holder = threading.Thread(target=_hold_lock_like_a_running_option_command)
    holder.start()
    try:
        assert holder_ready.wait(timeout=5)

        started = time.monotonic()
        cancellation = cancel_gate(
            created.bundle_path, source="test", lock_timeout_seconds=0.2
        )
        elapsed = time.monotonic() - started
    finally:
        release_holder.set()
        holder.join(timeout=5)

    assert cancellation["source"] == "test"
    assert elapsed < 2.0


def test_notification_dismissal_failure_does_not_break_persisted_answer(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = create_gate(gate_spec(request_id="dismissal-failure"))

    def fail_dismissal(_notification_id: str) -> bool:
        raise OSError("notification store unavailable")

    monkeypatch.setattr(
        "sase.notifications.store.mark_dismissed",
        fail_dismissal,
    )

    execution = execute_gate_selection(created.bundle_path, ["accept"])

    assert execution.response["selected_option_ids"] == ["accept"]
    assert created.response_path.is_file()
    [notification] = load_notifications(include_dismissed=True)
    assert notification.dismissed is False


def test_hash_mismatch_and_malformed_output_leave_gate_answerable(
    gate_home: Path,
) -> None:
    malformed = create_gate(
        gate_spec(request_id="malformed", command="#!/bin/sh\nprintf 'not json'\n")
    )
    with pytest.raises(GateError, match="stdout must contain"):
        execute_gate_selection(malformed.bundle_path, ["accept"])
    assert not malformed.response_path.exists()
    assert list((malformed.bundle_path / "errors").glob("*.json"))

    changed = create_gate(gate_spec(request_id="changed"))
    (changed.bundle_path / "preview.md").write_text("changed", encoding="utf-8")
    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(changed.bundle_path, ["accept"])
    assert excinfo.value.code == "hash_mismatch"
    assert not changed.response_path.exists()


def test_primary_branch_is_hashed_with_the_reviewed_request(gate_home: Path) -> None:
    gate = create_gate(custom_gate_spec(request_id="primary-hash"))
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    envelope["primary_branch"] = []
    gate.request_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(GateError) as exc_info:
        load_and_verify_bundle(gate.bundle_path)

    assert exc_info.value.code == "hash_mismatch"


def test_persisted_v2_bundle_projects_first_branch_and_remains_answerable(
    gate_home: Path,
) -> None:
    gate = create_gate(custom_gate_spec(request_id="legacy-v2"))
    envelope = json.loads(gate.request_path.read_text(encoding="utf-8"))
    envelope["schema_version"] = 2
    envelope.pop("primary_branch")
    envelope["hashes"]["request"] = request_sha256(envelope)
    gate.request_path.write_text(json.dumps(envelope), encoding="utf-8")

    projected, _adapter = load_and_verify_bundle(gate.bundle_path)

    assert projected["schema_version"] == 2
    assert projected["primary_branch"] == ["proceed", "audit", "broken"]
    response = execute_gate_selection(
        gate.bundle_path,
        ["proceed", "audit"],
    ).response
    assert response["selected_option_ids"] == ["proceed", "audit"]


class _ExitedPopen(subprocess.Popen):  # type: ignore[type-arg]
    """Popen that returns only once the command has exited."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Gate command output is a single short line, so this cannot deadlock.
        while self.poll() is None:
            pass


def test_gate_command_may_exit_without_reading_its_stdin_payload(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = create_gate(
        gate_spec(
            request_id="stdin-ignored",
            command='#!/bin/sh\nprintf \'{"status": "ok"}\\n\'\n',
        )
    )
    monkeypatch.setattr(
        "sase.notification_gates.executor.subprocess.Popen", _ExitedPopen
    )
    lines: list[tuple[str, str]] = []

    execution = execute_gate_selection(
        created.bundle_path,
        ["accept"],
        on_output_line=lambda _kind, _id, stream, line: lines.append((stream, line)),
    )

    assert execution.response["option_results"] == [
        {"id": "accept", "result": {"status": "ok"}}
    ]
    assert lines == [("stdout", '{"status": "ok"}')]
    assert created.response_path.is_file()
