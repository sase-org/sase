"""Durability, trust, and execution coverage for notification gates."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import pytest

from sase.main.notify_handler import handle_notify_command
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import resolve_action_bundle
from sase.notification_gates.poller import poll_gate, wait_for_gate
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sase.notification_gates import paths
    from sase.notifications import store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


def _gate_spec(
    *,
    request_id: str = "request-1",
    kind: str = "hitl",
    command: str | None = None,
    auto: object = False,
    timeout: float | None = None,
) -> dict[str, object]:
    script = command or (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "value = json.load(sys.stdin)\n"
        "print(json.dumps({'status': 'ok', 'input': value}))\n"
    )
    spec: dict[str, object] = {
        "schema_version": 2,
        "request_id": request_id,
        "kind": kind,
        "producer": {"agent": "test"},
        "continuation_mode": "resume_agent",
        "payload": {"title": "Review this"},
        "presentation": {
            "notes": ["Review requested"],
            "tags": ["Gate"],
            "files": ["preview.md"],
            "preview": "preview.md",
        },
        "query": "approve",
        "options": [
            {
                "id": "approve",
                "label": "Approve",
                "command": {"argv": ["commands/approve"]},
                "input_schema": {"type": "object"},
                "result_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "ok"}},
                },
            }
        ],
        "resources": [
            {
                "path": "commands/approve",
                "role": "command",
                "content": script,
            },
            {"path": "preview.md", "role": "preview", "content": "# Preview\n"},
        ],
        "auto": auto,
    }
    if timeout is not None:
        spec["gate_timeout_seconds"] = timeout
    return spec


def _custom_gate_spec(
    *,
    request_id: str = "custom-request",
    auto: object = False,
    feedback: str | None = None,
) -> dict[str, object]:
    proceed: dict[str, object] = {
        "id": "proceed",
        "label": "Proceed safely",
        "icon": "✅",
        "command": {"argv": ["commands/proceed"]},
        "input_schema": {"type": "object"},
        "result_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"const": "ok"}},
        },
    }
    if feedback is not None:
        proceed["feedback"] = feedback
    return {
        "schema_version": 2,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {"open": {"shape": True}},
        "presentation": {
            "icon": "🛡️",
            "sender": "safety-check",
            "notes": ["Confirm guarded work"],
        },
        "query": "(proceed AND audit AND broken)",
        "options": [
            proceed,
            {
                "id": "audit",
                "label": "Write audit record",
                "icon": "📝",
                "command": {"argv": ["commands/audit"]},
            },
            {
                "id": "broken",
                "label": "Try fallible follow-up",
                "default_selected": False,
                "command": {"argv": ["commands/broken"]},
            },
        ],
        "groups": [
            {
                "options": ["broken", "proceed", "audit"],
                "label": "Proceed safely",
                "icon": "✅",
            }
        ],
        "resources": [
            {
                "path": "commands/proceed",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'status': 'ok'}))\n"
                ),
            },
            {
                "path": "commands/audit",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "value = json.load(sys.stdin)\n"
                    "print(json.dumps({'audit': value}))\n"
                ),
            },
            {
                "path": "commands/broken",
                "role": "command",
                "content": "#!/bin/sh\nprintf 'follow-up failed' >&2\nexit 7\n",
            },
        ],
        "auto": auto,
    }


def test_create_gate_returns_stable_descriptor_and_is_idempotent(
    gate_home: Path,
) -> None:
    result = create_gate(_gate_spec())
    repeated = create_gate(_gate_spec())

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
    result = create_gate(_custom_gate_spec())

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
        create_gate(_custom_gate_spec(request_id="custom-auto", auto=True))
    assert auto_error.value.code == "auto_not_supported"

    invalid_icon = _custom_gate_spec(request_id="invalid-icon")
    presentation = invalid_icon["presentation"]
    assert isinstance(presentation, dict)
    presentation["icon"] = "✅🚀"
    with pytest.raises(GateError) as icon_error:
        create_gate(invalid_icon)
    assert icon_error.value.code == "invalid_icon"

    duplicate_option = _custom_gate_spec(request_id="duplicate-option")
    options = duplicate_option["options"]
    assert isinstance(options, list)
    options[2]["id"] = "audit"
    with pytest.raises(GateError) as duplicate_error:
        create_gate(duplicate_option)
    assert duplicate_error.value.code == "duplicate_identifier"
    assert not (gate_home / "requests" / "custom" / "custom-auto").exists()


def test_custom_gate_runs_selected_options_in_query_order_and_persists_feedback(
    gate_home: Path,
) -> None:
    result = create_gate(_custom_gate_spec(feedback="required"))

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
    [error_log] = list((result.bundle_path / "errors").glob("*.json"))
    assert json.loads(error_log.read_text())["option_id"] == "broken"

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


def test_notify_wait_prints_stable_answered_json_and_human_summary(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    result = create_gate(_custom_gate_spec(request_id="wait-answered"))
    execute_gate_selection(
        result.bundle_path,
        ["proceed", "audit"],
        feedback="Looks good",
    )
    args = argparse.Namespace(
        notify_subcommand="wait",
        id="wait-answered",
        kind="custom",
        json=True,
        timeout=None,
    )

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(args)

    assert excinfo.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "answered",
        "selected_option_ids": ["proceed", "audit"],
        "feedback": "Looks good",
        "response_path": str(result.response_path),
    }

    args.json = False
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(args)

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "Gate custom/wait-answered answered" in out
    assert "options proceed, audit" in out
    assert f"Response path: {result.response_path}" in out


def test_notify_wait_reports_cancelled_gate_with_distinct_exit_code(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    result = create_gate(_gate_spec(request_id="wait-cancelled"))
    cancel_gate(result.bundle_path, source="test")

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="wait",
                id="wait-cancelled",
                kind="hitl",
                json=True,
                timeout=None,
            )
        )

    assert excinfo.value.code == 3
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "cancelled"
    assert payload["selected_option_ids"] == []
    assert payload["feedback"] is None
    assert payload["response_path"] == str(result.response_path)


def test_notify_wait_reports_cli_timeout_with_distinct_exit_code(
    gate_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    result = create_gate(_gate_spec(request_id="wait-timeout"))

    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="wait",
                id="wait-timeout",
                kind="hitl",
                json=True,
                timeout=0.0,
            )
        )

    assert excinfo.value.code == 4
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "timeout"
    assert payload["response_path"] == str(result.response_path)
    cancellation = json.loads(
        (result.bundle_path / "cancellation.json").read_text(encoding="utf-8")
    )
    assert cancellation["reason"] == "timeout"


def test_custom_gate_rejects_invalid_selections_and_disabled_feedback(
    gate_home: Path,
) -> None:
    result = create_gate(_custom_gate_spec(feedback="disabled"))
    with pytest.raises(GateError) as unknown_option:
        execute_gate_selection(
            result.bundle_path,
            ["missing"],
        )
    assert unknown_option.value.code == "unknown_option"
    with pytest.raises(GateError) as cross_branch:
        cross_branch_spec = _custom_gate_spec(request_id="cross-branch")
        cross_branch_spec["query"] = "proceed OR audit OR broken"
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
    result = create_gate(_gate_spec())

    first = execute_gate_selection(result.bundle_path, ["approve"], {"reviewed": True})
    second = execute_gate_selection(
        result.bundle_path, ["approve"], {"reviewed": False}
    )

    assert first.already_completed is False
    assert first.response["option_results"] == [
        {
            "id": "approve",
            "result": {"status": "ok", "input": {"reviewed": True}},
        }
    ]
    assert second.already_completed is True
    assert second.response == first.response
    entry = next(iter(pending_actions.read_pending_action_store()["actions"].values()))
    assert entry["state"] == "already_handled"


def test_hash_mismatch_and_malformed_output_leave_gate_answerable(
    gate_home: Path,
) -> None:
    malformed = create_gate(
        _gate_spec(request_id="malformed", command="#!/bin/sh\nprintf 'not json'\n")
    )
    with pytest.raises(GateError, match="stdout must contain"):
        execute_gate_selection(malformed.bundle_path, ["approve"])
    assert not malformed.response_path.exists()
    assert list((malformed.bundle_path / "errors").glob("*.json"))

    changed = create_gate(_gate_spec(request_id="changed"))
    (changed.bundle_path / "preview.md").write_text("changed", encoding="utf-8")
    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(changed.bundle_path, ["approve"])
    assert excinfo.value.code == "hash_mismatch"
    assert not changed.response_path.exists()


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
            "schema_version": 2,
            "kind": "question",
            "request_id": "automatic-question",
            "continuation_mode": QUESTION_CONTINUATION_MODE,
            "payload": {
                "questions": questions,
                "session_id": "automatic-question",
            },
            "query": "submit",
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
    from sase.notification_gates.registry import adapter_for_kind
    from sase.notification_gates.models import GateSpec

    with pytest.raises(GateError) as exc_info:
        adapter_for_kind("launch").resolve_auto_selection(
            GateSpec.from_mapping(_gate_spec(kind="launch")), None
        )

    assert exc_info.value.code == "auto_not_supported"


def test_request_timeout_caps_caller_override_but_transport_staleness_is_not_polled(
    gate_home: Path,
) -> None:
    result = create_gate(_gate_spec(timeout=0.01))

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
        create_gate(_gate_spec())

    rows = load_notifications(include_dismissed=True)
    assert len(rows) == 1
    assert rows[0].dismissed is True
    assert pending_actions.read_pending_action_store()["actions"] == {}


def test_rejects_path_traversal_symlink_sources_and_reserved_files(
    gate_home: Path,
) -> None:
    traversal = _gate_spec()
    resources = traversal["resources"]
    assert isinstance(resources, list)
    resources[0]["path"] = "../approve"  # type: ignore[index]
    with pytest.raises(GateError, match="stay within"):
        create_gate(traversal)

    reserved = _gate_spec(request_id="reserved")
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
    symlink_spec = _gate_spec(request_id="symlink")
    symlink_resources = symlink_spec["resources"]
    assert isinstance(symlink_resources, list)
    symlink_resources[0].pop("content")  # type: ignore[union-attr]
    symlink_resources[0]["source"] = str(link)  # type: ignore[index]
    with pytest.raises(GateError) as excinfo:
        create_gate(symlink_spec)
    assert excinfo.value.code == "unsafe_file"


def test_notify_create_gate_json_and_raw_privileged_rejection(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del gate_home
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(_gate_spec())))
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                gate=True,
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 0
    descriptor = json.loads(capsys.readouterr().out)
    assert descriptor["schema_version"] == 2
    assert descriptor["kind"] == "hitl"

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "raw", "action": "PlanApproval"})),
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                gate=False,
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 1
    assert "privileged" in capsys.readouterr().err


def test_raw_notify_creation_preserves_silent(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del gate_home
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "raw", "silent": True})),
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                gate=False,
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 0
    assert load_notifications(include_dismissed=True)[0].silent is True


def test_raw_notify_cannot_spoof_custom_gate_and_custom_has_no_legacy_fallback(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sender": "raw", "action": "CustomGate"})),
    )
    with pytest.raises(SystemExit) as excinfo:
        handle_notify_command(
            argparse.Namespace(
                notify_subcommand="create",
                gate=False,
                sender=None,
                tag=None,
            )
        )
    assert excinfo.value.code == 1
    assert "privileged" in capsys.readouterr().err

    legacy = gate_home / "legacy-custom"
    legacy.mkdir()
    (legacy / "request.json").write_text("{}\n", encoding="utf-8")
    assert resolve_action_bundle("CustomGate", {"bundle_path": str(legacy)}) is None


def test_launch_adapter_rejects_unregistered_command_shape(gate_home: Path) -> None:
    del gate_home
    with pytest.raises(GateError) as exc_info:
        create_gate(_gate_spec(kind="launch"))
    assert exc_info.value.code == "invalid_launch_choices"


@pytest.mark.parametrize(
    (
        "action",
        "kind",
        "legacy_key",
        "legacy_request",
        "legacy_response",
    ),
    [
        (
            "PlanApproval",
            "plan",
            "response_dir",
            "plan_request.json",
            "plan_response.json",
        ),
        (
            "EpicApproval",
            "epic_plan",
            "response_dir",
            "plan_request.json",
            "plan_response.json",
        ),
        (
            "UserQuestion",
            "question",
            "response_dir",
            "question_request.json",
            "question_response.json",
        ),
        (
            "LaunchApproval",
            "launch",
            "response_dir",
            "launch_request.json",
            "launch_response.json",
        ),
        (
            "HITL",
            "hitl",
            "artifacts_dir",
            "hitl_request.json",
            "hitl_response.json",
        ),
    ],
)
def test_typed_gate_resolver_keeps_neutral_first_legacy_fallback_contract(
    gate_home: Path,
    action: str,
    kind: str,
    legacy_key: str,
    legacy_request: str,
    legacy_response: str,
) -> None:
    """Keep legacy readers until the documented post-release removal window."""
    request_id = f"{kind}-compatibility"
    neutral_root = gate_home / "requests" / kind / request_id
    neutral_root.mkdir(parents=True)
    neutral_request = neutral_root / "request.json"
    neutral_request.write_text("{}\n", encoding="utf-8")

    legacy_root = gate_home / f"legacy-{kind}"
    legacy_root.mkdir()
    (legacy_root / legacy_request).write_text("{}\n", encoding="utf-8")
    action_data = {
        "request_id": request_id,
        "request_kind": kind,
        legacy_key: str(legacy_root),
    }

    neutral = resolve_action_bundle(action, action_data)
    assert neutral is not None
    assert neutral.root == neutral_root
    assert neutral.request == neutral_request
    assert neutral.response == neutral_root / "response.json"
    assert neutral.legacy is False

    neutral_request.unlink()
    legacy = resolve_action_bundle(action, action_data)
    assert legacy is not None
    assert legacy.root == legacy_root
    assert legacy.request == legacy_root / legacy_request
    assert legacy.response == legacy_root / legacy_response
    assert legacy.legacy is True
