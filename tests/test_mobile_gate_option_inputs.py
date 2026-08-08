"""Tests for per-option declared inputs on the mobile gate bridge."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.integrations.mobile_notifications import (
    MobileGateActionResult,
    execute_mobile_gate_action,
    handle_mobile_notification_bridge,
)
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications


def _snapshot(rows: list) -> SimpleNamespace:
    return SimpleNamespace(
        notifications=rows,
        counts=SimpleNamespace(priority=1, errors=0, rest=1, muted=0),
        expired_ids=["expired-row"],
    )


def _echo_command() -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "value = json.load(sys.stdin)\n"
        "print(json.dumps({'value': value}))\n"
    )


def test_execute_mobile_gate_action_delivers_option_inputs_to_each_option() -> None:
    command = _echo_command()
    gate = create_gate(
        {
            "schema_version": 3,
            "kind": "custom",
            "request_id": "mobile-option-inputs",
            "producer": {"agent": "test"},
            "payload": {},
            "presentation": {
                "icon": "📱",
                "title": "Confirm mobile action",
                "notes": ["Confirm mobile action"],
            },
            "query": "(approve AND audit)",
            "primary_branch": ["approve", "audit"],
            "options": [
                {
                    "id": "approve",
                    "label": "Approve",
                    "command": {"argv": ["commands/approve"]},
                    "inputs": [
                        {
                            "id": "reason",
                            "label": "Reason",
                            "type": "line",
                            "required": True,
                        }
                    ],
                },
                {
                    "id": "audit",
                    "label": "Audit",
                    "command": {"argv": ["commands/audit"]},
                    "inputs": [
                        {
                            "id": "detail",
                            "label": "Detail",
                            "type": "line",
                            "required": True,
                        }
                    ],
                },
            ],
            "groups": [
                {
                    "options": ["approve", "audit"],
                    "label": "Approve and audit",
                }
            ],
            "resources": [
                {"path": "commands/approve", "role": "command", "content": command},
                {"path": "commands/audit", "role": "command", "content": command},
            ],
        }
    )
    notification = load_notifications()[0]

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_current_notification_snapshot",
            return_value=_snapshot([notification]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id=notification.id,
            prefix="mobile-o",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_gate_action(
            "mobile-o",
            ["approve", "audit"],
            option_inputs={
                "approve": {"reason": "looks good"},
                "audit": {"detail": "checked twice"},
            },
        )

    assert result.response_json["option_results"] == [
        {"id": "approve", "result": {"value": {"reason": "looks good"}}},
        {"id": "audit", "result": {"value": {"detail": "checked twice"}}},
    ]
    assert gate.response_path.is_file()


def test_execute_mobile_gate_action_option_inputs_omitted_matches_shared_value() -> (
    None
):
    command = _echo_command()
    gate = create_gate(
        {
            "schema_version": 3,
            "kind": "custom",
            "request_id": "mobile-no-option-inputs",
            "producer": {"agent": "test"},
            "payload": {},
            "presentation": {
                "icon": "📱",
                "title": "Confirm mobile action",
                "notes": ["Confirm mobile action"],
            },
            "query": "(approve AND audit)",
            "primary_branch": ["approve", "audit"],
            "options": [
                {
                    "id": "approve",
                    "label": "Approve",
                    "command": {"argv": ["commands/approve"]},
                },
                {
                    "id": "audit",
                    "label": "Audit",
                    "command": {"argv": ["commands/audit"]},
                },
            ],
            "groups": [
                {
                    "options": ["approve", "audit"],
                    "label": "Approve and audit",
                }
            ],
            "resources": [
                {"path": "commands/approve", "role": "command", "content": command},
                {"path": "commands/audit", "role": "command", "content": command},
            ],
        }
    )
    del gate
    notification = load_notifications()[0]

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_current_notification_snapshot",
            return_value=_snapshot([notification]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id=notification.id,
            prefix="mobile-s",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_gate_action("mobile-s", ["approve", "audit"])

    assert result.response_json["option_results"] == [
        {"id": "approve", "result": {"value": {}}},
        {"id": "audit", "result": {"value": {}}},
    ]


def test_execute_mobile_gate_action_secret_field_is_redacted_in_response() -> None:
    command = _echo_command()
    gate = create_gate(
        {
            "schema_version": 3,
            "kind": "custom",
            "request_id": "mobile-secret",
            "producer": {"agent": "test"},
            "payload": {},
            "presentation": {
                "icon": "📱",
                "title": "Confirm mobile action",
                "notes": ["Confirm mobile action"],
            },
            "query": "approve",
            "primary_branch": ["approve"],
            "options": [
                {
                    "id": "approve",
                    "label": "Approve",
                    "command": {"argv": ["commands/approve"]},
                    "inputs": [
                        {
                            "id": "token",
                            "label": "Token",
                            "type": "line",
                            "required": True,
                            "secret": True,
                        }
                    ],
                },
            ],
            "resources": [
                {"path": "commands/approve", "role": "command", "content": command},
            ],
        }
    )
    notification = load_notifications()[0]

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_current_notification_snapshot",
            return_value=_snapshot([notification]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id=notification.id,
            prefix="mobile-t",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_gate_action(
            "mobile-t",
            ["approve"],
            option_inputs={"approve": {"token": "hunter2"}},
        )

    assert result.response_json["option_inputs"] == {
        "approve": {"token": {"$redacted": True}}
    }
    # The command echoes its stdin, so the result is the other place the same
    # secret would land in the same durable file.
    assert result.response_json["option_results"] == [
        {"id": "approve", "result": {"value": {"token": {"$redacted": True}}}}
    ]
    assert "hunter2" not in gate.response_path.read_text(encoding="utf-8")
    assert gate.response_path.is_file()


def test_mobile_notification_bridge_forwards_option_inputs() -> None:
    stdin = StringIO(
        '{"schema_version":5,"prefix":"mobile-c",'
        '"selected_option_ids":["approve","audit"],'
        '"option_inputs":{"approve":{"reason":"looks good"}}}'
    )
    stdout = StringIO()
    stderr = StringIO()
    args = SimpleNamespace(mobile_notification_bridge_subcommand="gate-action")
    expected = MobileGateActionResult(
        prefix="mobile-c",
        notification_id="mobile-custom-row",
        action_kind="custom_gate",
        response_file="response.json",
        response_json={"selected_option_ids": ["approve", "audit"]},
        message="Gate resolved",
    )

    with patch(
        "sase.integrations.mobile_notifications.execute_mobile_gate_action",
        return_value=expected,
    ) as execute:
        exit_code = handle_mobile_notification_bridge(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

    assert exit_code == 0
    execute.assert_called_once_with(
        "mobile-c",
        ["approve", "audit"],
        feedback=None,
        option_inputs={"approve": {"reason": "looks good"}},
    )


@pytest.mark.parametrize("schema_version", [4, 5])
def test_mobile_notification_bridge_accepts_schema_versions_4_and_5(
    schema_version: int,
) -> None:
    stdin = StringIO(
        f'{{"schema_version":{schema_version},"prefix":"mobile-c",'
        '"selected_option_ids":["approve"]}'
    )
    stdout = StringIO()
    stderr = StringIO()
    args = SimpleNamespace(mobile_notification_bridge_subcommand="gate-action")
    expected = MobileGateActionResult(
        prefix="mobile-c",
        notification_id="mobile-custom-row",
        action_kind="custom_gate",
        response_file="response.json",
        response_json={"selected_option_ids": ["approve"]},
        message="Gate resolved",
    )

    with patch(
        "sase.integrations.mobile_notifications.execute_mobile_gate_action",
        return_value=expected,
    ):
        exit_code = handle_mobile_notification_bridge(
            args,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
        )

    assert exit_code == 0
    assert stderr.getvalue() == ""


@pytest.mark.parametrize("schema_version", [0, 6])
def test_mobile_notification_bridge_rejects_schema_versions_outside_range(
    schema_version: int,
) -> None:
    stdin = StringIO(
        f'{{"schema_version":{schema_version},"prefix":"mobile-c",'
        '"selected_option_ids":["approve"]}'
    )
    stdout = StringIO()
    stderr = StringIO()
    args = SimpleNamespace(mobile_notification_bridge_subcommand="gate-action")

    exit_code = handle_mobile_notification_bridge(
        args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["target"] == "schema_version"


def test_mobile_notification_bridge_rejects_option_inputs_below_schema_version_5() -> (
    None
):
    stdin = StringIO(
        '{"schema_version":4,"prefix":"mobile-c",'
        '"selected_option_ids":["approve"],'
        '"option_inputs":{"approve":{"reason":"looks good"}}}'
    )
    stdout = StringIO()
    stderr = StringIO()
    args = SimpleNamespace(mobile_notification_bridge_subcommand="gate-action")

    exit_code = handle_mobile_notification_bridge(
        args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["target"] == "option_inputs"


def test_mobile_notification_bridge_rejects_non_object_option_inputs() -> None:
    stdin = StringIO(
        '{"schema_version":5,"prefix":"mobile-c",'
        '"selected_option_ids":["approve"],'
        '"option_inputs":["not","an","object"]}'
    )
    stdout = StringIO()
    stderr = StringIO()
    args = SimpleNamespace(mobile_notification_bridge_subcommand="gate-action")

    exit_code = handle_mobile_notification_bridge(
        args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 2
    assert json.loads(stderr.getvalue())["target"] == "option_inputs"
