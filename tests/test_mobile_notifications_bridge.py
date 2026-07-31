"""Tests for the mobile notification host bridge."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.integrations.mobile_notifications import (
    MobileGateActionResult,
    MobileNotificationBridgeRow,
    build_mobile_attachment_manifests,
    execute_mobile_gate_action,
    execute_mobile_question_action,
    handle_mobile_notification_bridge,
    read_mobile_notification_snapshot,
    resolve_mobile_notification_detail,
)
from sase.notification_gates.service import create_gate
from sase.bead.task_gate import create_task_triage_gate
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications
from sase.user_question_actions import create_user_question_gate

_FRESH_FIXTURE_BASE = datetime.now(UTC).replace(microsecond=0)


def _snapshot(rows: list[Notification]) -> SimpleNamespace:
    return SimpleNamespace(
        notifications=rows,
        counts=SimpleNamespace(priority=1, errors=0, rest=1, muted=0),
        expired_ids=["expired-row"],
    )


def _notification(
    notification_id: str,
    timestamp: str,
    *,
    action: str | None = None,
    icon: str | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
    files: list[str] | None = None,
    action_data: dict[str, str] | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_fresh_fixture_timestamp(timestamp),
        sender="plan" if action == "PlanApproval" else "user-workflow",
        icon=icon,
        notes=[f"note {notification_id}"],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        silent=silent,
    )


def _fresh_fixture_timestamp(timestamp: str) -> str:
    if not timestamp.startswith("2026-05-06T"):
        return timestamp
    parsed = datetime.fromisoformat(timestamp)
    offset = timedelta(
        hours=parsed.hour,
        minutes=parsed.minute,
        seconds=parsed.second,
        microseconds=parsed.microsecond,
    )
    return (_FRESH_FIXTURE_BASE + offset).isoformat()


def test_mobile_bridge_filters_orders_and_preserves_counts() -> None:
    rows = [
        _notification("old", "2026-05-06T13:00:00+00:00"),
        _notification("read", "2026-05-06T14:00:00+00:00", read=True),
        _notification("silent", "2026-05-06T15:00:00+00:00", silent=True),
        _notification(
            "plan",
            "2026-05-06T16:00:00+00:00",
            action="PlanApproval",
            icon="📋",
        ),
    ]

    with patch(
        "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
        return_value=_snapshot(rows),
    ) as read_snapshot:
        snapshot = read_mobile_notification_snapshot(unread_only=True, limit=1)

    read_snapshot.assert_called_once_with(
        include_dismissed=False,
        expire_due_snoozes=True,
    )
    assert [row.id for row in snapshot.rows] == ["plan"]
    assert snapshot.rows[0].priority is True
    assert snapshot.rows[0].icon == "📋"
    assert snapshot.counts.priority == 1
    assert snapshot.expired_ids == ["expired-row"]


def test_mobile_bridge_keeps_raw_host_paths_and_safe_display_paths(
    tmp_path: Path,
) -> None:
    home_file = str(Path.home() / ".sase" / "digest.txt")
    rows = [
        _notification(
            "detail",
            "2026-05-06T13:00:00+00:00",
            action="PlanApproval",
            files=[home_file, str(tmp_path / "note.md")],
            action_data={"response_dir": home_file, "session_id": "s1"},
        )
    ]

    with patch(
        "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
        return_value=_snapshot(rows),
    ):
        detail = resolve_mobile_notification_detail("detail")

    assert detail is not None
    assert detail.display_files[0] == "~/.sase/digest.txt"
    assert detail.host_files[0] == home_file
    assert detail.display_action_data["response_dir"] == "~/.sase/digest.txt"
    assert detail.host_action_data["response_dir"] == home_file
    assert detail.host_action_data["session_id"] == "s1"
    assert detail.action_state == "available"


def test_mobile_bridge_builds_attachment_manifests(tmp_path: Path) -> None:
    markdown = tmp_path / "plan.md"
    pdf = tmp_path / "plan.pdf"
    missing = tmp_path / "missing.diff"
    markdown.write_text("# Plan\n", encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.7\n")
    row = _notification(
        "detail",
        "2026-05-06T13:00:00+00:00",
        action="PlanApproval",
        files=[str(markdown), str(missing)],
        action_data={"pdf_path": str(pdf)},
    )

    detail = _snapshot([row]).notifications[0]
    # Build directly from the projected row shape so this helper can be used by
    # host bridges that already resolved notifications.
    projected = MobileNotificationBridgeRow(
        id=detail.id,
        timestamp=detail.timestamp,
        sender=detail.sender,
        priority=False,
        host_files=list(detail.files),
        action=detail.action,
        host_action_data=dict(detail.action_data),
    )

    manifests = build_mobile_attachment_manifests(projected)

    assert [manifest.id for manifest in manifests] == [
        "att_000",
        "att_001",
        "att_002",
    ]
    assert manifests[0].kind == "markdown"
    assert manifests[0].content_type == "text/markdown"
    assert manifests[0].byte_size == len("# Plan\n")
    assert manifests[0].downloadable is True
    assert manifests[1].path_available is False
    assert manifests[1].downloadable is False
    assert manifests[2].kind == "pdf"
    assert manifests[2].content_type == "application/pdf"


def test_mobile_bridge_rejects_symlink_traversal_and_large_attachments(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe.txt"
    link = tmp_path / "safe-link.txt"
    large = tmp_path / "large.log"
    safe.write_text("ok", encoding="utf-8")
    large.write_text("too large", encoding="utf-8")
    link_is_symlink = False
    try:
        link.symlink_to(safe)
        link_is_symlink = True
    except OSError:
        link.write_text("ok", encoding="utf-8")
    row = _notification(
        "detail",
        "2026-05-06T13:00:00+00:00",
        files=[
            str(link),
            str(large),
            str(tmp_path / "child" / ".." / "safe.txt"),
        ],
    )
    projected = MobileNotificationBridgeRow(
        id=row.id,
        timestamp=row.timestamp,
        sender=row.sender,
        priority=False,
        host_files=list(row.files),
    )

    manifests = build_mobile_attachment_manifests(projected, max_attachment_bytes=3)

    assert manifests[0].path_available is True
    assert manifests[0].downloadable is (not link_is_symlink)
    assert manifests[1].downloadable is False
    assert manifests[2].downloadable is False


def test_mobile_bridge_includes_hitl_path_typed_outputs(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    output = tmp_path / "output.log"
    output.write_text("hello", encoding="utf-8")
    (artifacts_dir / "hitl_request.json").write_text(
        (
            "{\n"
            '  "output": {"log_path": "' + str(output) + '"},\n'
            '  "output_types": {"log_path": "path"}\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    projected = MobileNotificationBridgeRow(
        id="hitl",
        timestamp="2026-05-06T13:00:00+00:00",
        sender="hitl",
        priority=False,
        action="HITL",
        host_action_data={"artifacts_dir": str(artifacts_dir)},
    )

    manifests = build_mobile_attachment_manifests(projected)

    assert [Path(manifest.display_name).name for manifest in manifests] == [
        "hitl_request.json",
        "output.log",
    ]


def test_execute_mobile_question_action_uses_neutral_gate_executor() -> None:
    gate = create_user_question_gate(
        [
            {
                "question": "Which path?",
                "options": [{"id": "fast", "label": "Fast"}],
            }
        ],
        session_id="mobile-question",
    )
    notification = load_notifications()[0]

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([notification]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id=notification.id,
            prefix="mobile-q",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_question_action(
            "mobile-q", "answer", selected_option_id="fast"
        )

    assert result.response_file == "response.json"
    assert result.action_kind == "user_question"
    assert result.response_json["selected_option_ids"] == ["submit"]
    assert result.response_json["option_results"][0]["result"]["answers"][0][
        "selected"
    ] == ["Fast"]
    assert result.response_json["feedback"] is None
    assert gate.response_path.is_file()


def test_execute_mobile_gate_action_uses_selected_options_unchanged() -> None:
    command = (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "value = json.load(sys.stdin)\n"
        "print(json.dumps({'value': value}))\n"
    )
    gate = create_gate(
        {
            "schema_version": 3,
            "kind": "custom",
            "request_id": "mobile-custom",
            "producer": {"agent": "test"},
            "payload": {},
            "presentation": {"icon": "📱", "notes": ["Confirm mobile action"]},
            "query": "(approve AND audit)",
            "primary_branch": ["approve", "audit"],
            "options": [
                {
                    "id": "approve",
                    "label": "Approve",
                    "feedback": "required",
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
                {
                    "path": "commands/approve",
                    "role": "command",
                    "content": command,
                },
                {
                    "path": "commands/audit",
                    "role": "command",
                    "content": command,
                },
            ],
        }
    )
    notification = load_notifications()[0]

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([notification]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id=notification.id,
            prefix="mobile-c",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_gate_action(
            "mobile-c",
            ["approve", "audit"],
            feedback="Approved from mobile",
        )

    assert result.response_file == "response.json"
    assert result.action_kind == "custom_gate"
    assert result.response_json["selected_option_ids"] == ["approve", "audit"]
    assert result.response_json["feedback"] == "Approved from mobile"
    assert result.response_json["option_results"] == [
        {"id": "approve", "result": {"value": {}}},
        {"id": "audit", "result": {"value": {}}},
    ]
    assert gate.response_path.is_file()
    assert load_notifications(include_dismissed=True)[0].dismissed is True


def test_execute_mobile_task_triage_reports_registered_action_kind(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_task_triage_gate(
        request_id="mobile-task-triage",
        bead_id="sase-task.1",
        project="sase",
        title="Review mobile follow-up",
    )
    notification = load_notifications()[0]
    task = SimpleNamespace(task_id="mobile-task-123")

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([notification]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
        patch(
            "sase.bead.task_gate._resolve_task_triage_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch(
            "sase.bead.task_launch.submit_task_launch_task",
            return_value=task,
        ) as submit,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id=notification.id,
            prefix="mobile-t",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_gate_action(
            "mobile-t",
            ["launch"],
            feedback="Keep the shim.",
        )

    assert result.action_kind == "task_triage"
    assert result.response_json["selected_option_ids"] == ["launch"]
    assert result.response_json["task_launch_task_id"] == "mobile-task-123"
    submit.assert_called_once_with(
        "sase-task.1",
        cwd=Path("/canonical/sase"),
        feedback="Keep the shim.",
        origin="api",
    )
    assert (
        json.loads(gate.response_path.read_text(encoding="utf-8"))[
            "task_launch_task_id"
        ]
        == "mobile-task-123"
    )


def test_mobile_notification_bridge_forwards_gate_selection_unchanged() -> None:
    stdin = StringIO(
        '{"schema_version":4,"prefix":"mobile-c",'
        '"selected_option_ids":["approve","audit"],'
        '"feedback":"Approved from mobile"}'
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
        feedback="Approved from mobile",
    )
    assert json.loads(stdout.getvalue())["response_json"] == {
        "selected_option_ids": ["approve", "audit"]
    }
    assert stderr.getvalue() == ""
