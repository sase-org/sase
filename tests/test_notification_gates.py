"""Creation and service-level coverage for notification gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.models import GateError
from sase.notification_gates.poller import poll_gate, wait_for_gate
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from tests._notification_gates_fixtures import custom_gate_spec, gate_spec


def test_create_gate_returns_stable_descriptor_and_is_idempotent(
    gate_home: Path,
) -> None:
    result = create_gate(gate_spec())
    repeated = create_gate(gate_spec())

    assert repeated.to_dict() == result.to_dict()
    assert result.schema_version == 2
    assert result.request_path.is_file()
    assert result.preview_path == result.bundle_path / "preview.md"
    assert result.response_path == result.bundle_path / "response.json"
    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert request["hashes"]["request"] == result.hashes["request"]
    rows = load_notifications(include_dismissed=True)
    assert [row.id for row in rows] == [result.notification_id]
    assert rows[0].action == "HITL"
    assert rows[0].tags == ["gate"]
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    assert entry["notification_id"] == result.notification_id
    assert entry["state"] == "available"


def test_custom_gate_projects_query_groups_and_privileged_pending_action(
    gate_home: Path,
) -> None:
    result = create_gate(custom_gate_spec())

    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    options = request["options"]
    [notification] = load_notifications(include_dismissed=True)
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))

    assert request["presentation"]["icon"] == "🛡️"
    assert request["query"] == "(proceed AND audit AND broken)"
    assert request["branches"] == [["proceed", "audit", "broken"]]
    assert request["groups"] == [
        {
            "options": ["proceed", "audit", "broken"],
            "label": "Proceed safely",
            "icon": "✅",
        }
    ]
    assert [option["id"] for option in options] == ["proceed", "audit", "broken"]
    assert all(option["feedback"] == "optional" for option in options)
    assert notification.icon == "🛡️"
    assert notification.action == "CustomGate"
    assert entry["action_kind"] == "custom_gate"


def test_custom_gate_auto_and_unsafe_display_shapes_are_rejected(
    gate_home: Path,
) -> None:
    with pytest.raises(GateError) as auto_error:
        create_gate(custom_gate_spec(request_id="custom-auto", auto=True))
    assert auto_error.value.code == "auto_not_supported"

    invalid_icon = custom_gate_spec(request_id="invalid-icon")
    presentation = invalid_icon["presentation"]
    assert isinstance(presentation, dict)
    presentation["icon"] = "✅🚀"
    with pytest.raises(GateError) as icon_error:
        create_gate(invalid_icon)
    assert icon_error.value.code == "invalid_icon"

    duplicate_option = custom_gate_spec(request_id="duplicate-option")
    options = duplicate_option["options"]
    assert isinstance(options, list)
    options[2]["id"] = "audit"
    with pytest.raises(GateError) as duplicate_error:
        create_gate(duplicate_option)
    assert duplicate_error.value.code == "duplicate_identifier"
    assert not (gate_home / "requests" / "custom" / "custom-auto").exists()


def test_automatic_resolution_uses_executor_without_pending_row(
    gate_home: Path,
) -> None:
    from sase.user_question_actions import (
        QUESTION_COMMAND_PATH,
        QUESTION_CONTINUATION_MODE,
        automatic_question_response,
        question_gate_command_script,
        question_response_schema,
        validate_user_questions,
    )

    questions = validate_user_questions(
        [
            {
                "question": "Choose one",
                "options": [{"label": "First"}, {"label": "Second"}],
            }
        ]
    )
    schema = question_response_schema(questions)
    result = create_gate(
        {
            "schema_version": 3,
            "kind": "question",
            "request_id": "automatic-question",
            "continuation_mode": QUESTION_CONTINUATION_MODE,
            "payload": {
                "questions": questions,
                "session_id": "automatic-question",
            },
            "query": "submit",
            "primary_branch": ["submit"],
            "options": [
                {
                    "id": "submit",
                    "label": "Submit answers",
                    "command": {"argv": [QUESTION_COMMAND_PATH]},
                    "input_schema": schema,
                    "result_schema": schema,
                    "feedback": "optional",
                }
            ],
            "resources": [
                {
                    "path": QUESTION_COMMAND_PATH,
                    "role": "command",
                    "content": question_gate_command_script(),
                }
            ],
            "auto": True,
        }
    )

    assert result.notification_id is None
    assert result.auto_resolution["state"] == "resolved"
    assert result.auto_resolution["selected_option_ids"] == ["submit"]
    assert result.response_path.is_file()
    response = json.loads(result.response_path.read_text(encoding="utf-8"))
    assert response["selected_option_ids"] == ["submit"]
    assert response["option_results"] == [
        {
            "id": "submit",
            "result": automatic_question_response({"questions": questions}),
        }
    ]
    assert load_notifications(include_dismissed=True) == []
    assert pending_actions.read_pending_action_store()["actions"] == {}


def test_launch_adapter_rejects_automatic_resolution() -> None:
    from sase.notification_gates.models import GateSpec
    from sase.notification_gates.registry import adapter_for_kind

    with pytest.raises(GateError) as exc_info:
        adapter_for_kind("launch").resolve_auto_selection(
            GateSpec.from_mapping(gate_spec(kind="launch")), None
        )

    assert exc_info.value.code == "auto_not_supported"


def test_request_timeout_caps_caller_override_but_transport_staleness_is_not_polled(
    gate_home: Path,
) -> None:
    result = create_gate(gate_spec(timeout=0.01))

    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    notification = load_notifications()[0]
    assert (
        pending_actions.action_state_for_notification(
            notification, now=float(entry["stale_deadline_unix"]) + 1
        )
        == "stale"
    )
    assert poll_gate(result.bundle_path) is None
    terminal = wait_for_gate(
        result.bundle_path,
        timeout_seconds=60,
        poll_interval=0.001,
    )
    assert terminal.status == "timed_out"
    assert terminal.payload["reason"] == "timeout"


def test_pending_registration_failure_compensates_published_row(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_registration(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("pending store unavailable")

    monkeypatch.setattr(pending_actions, "register_notification", fail_registration)
    with pytest.raises(OSError, match="pending store unavailable"):
        create_gate(gate_spec())

    rows = load_notifications(include_dismissed=True)
    assert len(rows) == 1
    assert rows[0].dismissed is True
    assert pending_actions.read_pending_action_store()["actions"] == {}


def test_rejects_path_traversal_symlink_sources_and_reserved_files(
    gate_home: Path,
) -> None:
    traversal = gate_spec()
    resources = traversal["resources"]
    assert isinstance(resources, list)
    resources[0]["path"] = "../approve"  # type: ignore[index]
    with pytest.raises(GateError, match="stay within"):
        create_gate(traversal)

    reserved = gate_spec(request_id="reserved")
    reserved_resources = reserved["resources"]
    assert isinstance(reserved_resources, list)
    reserved_resources[1]["path"] = "response.json"  # type: ignore[index]
    with pytest.raises(GateError) as excinfo:
        create_gate(reserved)
    assert excinfo.value.code == "reserved_resource_path"

    source = gate_home / "script"
    source.write_text("#!/bin/sh\nprintf '{}\\n'\n", encoding="utf-8")
    link = gate_home / "script-link"
    link.symlink_to(source)
    symlink_spec = gate_spec(request_id="symlink")
    symlink_resources = symlink_spec["resources"]
    assert isinstance(symlink_resources, list)
    symlink_resources[0].pop("content")  # type: ignore[union-attr]
    symlink_resources[0]["source"] = str(link)  # type: ignore[index]
    with pytest.raises(GateError) as excinfo:
        create_gate(symlink_spec)
    assert excinfo.value.code == "unsafe_file"


def test_launch_adapter_rejects_unregistered_command_shape(gate_home: Path) -> None:
    del gate_home
    with pytest.raises(GateError) as exc_info:
        create_gate(gate_spec(kind="launch"))
    assert exc_info.value.code == "invalid_launch_query"
