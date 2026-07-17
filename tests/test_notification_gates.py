"""Durability, trust, and execution coverage for notification gates."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

import pytest

from sase.main.notify_handler import handle_notify_command
from sase.notification_gates.executor import execute_gate_choice
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
        "schema_version": 1,
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
        "choices": [
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


def test_create_gate_returns_stable_descriptor_and_is_idempotent(
    gate_home: Path,
) -> None:
    result = create_gate(_gate_spec())
    repeated = create_gate(_gate_spec())

    assert repeated.to_dict() == result.to_dict()
    assert result.schema_version == 1
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


def test_execute_choice_validates_input_and_writes_response_once(
    gate_home: Path,
) -> None:
    result = create_gate(_gate_spec())

    first = execute_gate_choice(result.bundle_path, "approve", {"reviewed": True})
    second = execute_gate_choice(result.bundle_path, "approve", {"reviewed": False})

    assert first.already_completed is False
    assert first.response["result"] == {
        "status": "ok",
        "input": {"reviewed": True},
    }
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
        execute_gate_choice(malformed.bundle_path, "approve")
    assert not malformed.response_path.exists()
    assert list((malformed.bundle_path / "errors").glob("*.json"))

    changed = create_gate(_gate_spec(request_id="changed"))
    (changed.bundle_path / "preview.md").write_text("changed", encoding="utf-8")
    with pytest.raises(GateError) as excinfo:
        execute_gate_choice(changed.bundle_path, "approve")
    assert excinfo.value.code == "hash_mismatch"
    assert not changed.response_path.exists()


def test_automatic_resolution_uses_executor_without_pending_row(
    gate_home: Path,
) -> None:
    from sase.user_question_actions import create_user_question_gate

    result = create_user_question_gate(
        [
            {
                "question": "Choose one",
                "options": [{"label": "First"}, {"label": "Second"}],
            }
        ],
        session_id="automatic-question",
        auto=True,
    )

    assert result.notification_id is None
    assert result.auto_resolution["state"] == "resolved"
    assert result.response_path.is_file()
    assert load_notifications(include_dismissed=True) == []
    assert pending_actions.read_pending_action_store()["actions"] == {}


def test_launch_adapter_rejects_automatic_resolution() -> None:
    from sase.notification_gates.registry import adapter_for_kind

    with pytest.raises(GateError) as exc_info:
        adapter_for_kind("launch").resolve_auto_choice((), None)

    assert exc_info.value.code == "auto_not_supported"


def test_explicit_timeout_is_terminal_but_transport_staleness_is_not_polled(
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
    terminal = wait_for_gate(result.bundle_path, poll_interval=0.001)
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
    assert descriptor["schema_version"] == 1
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
