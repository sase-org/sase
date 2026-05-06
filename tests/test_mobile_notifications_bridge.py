"""Tests for the mobile notification host bridge."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.integrations.mobile_notifications import (
    MobileNotificationBridgeRow,
    MobilePlanActionError,
    build_mobile_attachment_manifests,
    execute_mobile_hitl_action,
    execute_mobile_plan_action,
    execute_mobile_question_action,
    read_mobile_notification_snapshot,
    resolve_mobile_notification_detail,
)
from sase.notifications.models import Notification


def _snapshot(rows: list[Notification]) -> SimpleNamespace:
    return SimpleNamespace(
        notifications=rows,
        counts=SimpleNamespace(priority=1, rest=1, muted=0),
        expired_ids=["expired-row"],
    )


def _notification(
    notification_id: str,
    timestamp: str,
    *,
    action: str | None = None,
    read: bool = False,
    dismissed: bool = False,
    silent: bool = False,
    files: list[str] | None = None,
    action_data: dict[str, str] | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=timestamp,
        sender="plan" if action == "PlanApproval" else "user-workflow",
        notes=[f"note {notification_id}"],
        files=files or [],
        action=action,
        action_data=action_data or {},
        read=read,
        dismissed=dismissed,
        silent=silent,
    )


def test_mobile_bridge_filters_orders_and_preserves_counts() -> None:
    rows = [
        _notification("old", "2026-05-06T13:00:00+00:00"),
        _notification("read", "2026-05-06T14:00:00+00:00", read=True),
        _notification("silent", "2026-05-06T15:00:00+00:00", silent=True),
        _notification(
            "plan",
            "2026-05-06T16:00:00+00:00",
            action="PlanApproval",
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


def test_execute_mobile_plan_action_writes_response_and_side_effects(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "agent" / "plan_approval"
    response_dir.mkdir(parents=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    row = _notification(
        "abcdef12-plan",
        "2026-05-06T13:00:00+00:00",
        action="PlanApproval",
        files=[str(plan_file)],
        action_data={"response_dir": str(response_dir)},
    )

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([row]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
        patch("sase.notifications.mark_dismissed") as mark_dismissed,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id="abcdef12-plan",
            prefix="abcdef12",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_plan_action(
            "abcdef12",
            "run",
            coder_prompt="Focus tests",
        )

    assert result.notification_id == "abcdef12-plan"
    assert result.response_json == {
        "action": "approve",
        "commit_plan": False,
        "run_coder": True,
        "coder_prompt": "Focus tests",
    }
    assert (response_dir / "plan_response.json").read_text(encoding="utf-8") == (
        "{\n"
        '  "action": "approve",\n'
        '  "commit_plan": false,\n'
        '  "run_coder": true,\n'
        '  "coder_prompt": "Focus tests"\n'
        "}\n"
    )
    mark_dismissed.assert_called_once_with("abcdef12-plan")


def test_execute_mobile_plan_action_rejects_duplicate_response(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "agent" / "plan_approval"
    response_dir.mkdir(parents=True)
    (response_dir / "plan_request.json").write_text("{}", encoding="utf-8")
    (response_dir / "plan_response.json").write_text(
        '{"action":"approve"}', encoding="utf-8"
    )
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")
    row = _notification(
        "abcdef12-plan",
        "2026-05-06T13:00:00+00:00",
        action="PlanApproval",
        files=[str(plan_file)],
        action_data={"response_dir": str(response_dir)},
    )

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([row]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id="abcdef12-plan",
            prefix="abcdef12",
            prefix_len=8,
            resolution="unique_prefix",
        )
        try:
            execute_mobile_plan_action("abcdef12", "approve")
        except MobilePlanActionError as exc:
            assert exc.code == "conflict_already_handled"
        else:
            raise AssertionError("expected duplicate response conflict")


def test_execute_mobile_hitl_action_writes_response_and_dismisses(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "agent" / "artifacts"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "hitl_request.json").write_text("{}", encoding="utf-8")
    row = _notification(
        "hitl0001-row",
        "2026-05-06T13:00:00+00:00",
        action="HITL",
        action_data={"artifacts_dir": str(artifacts_dir)},
    )

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([row]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
        patch("sase.notifications.mark_dismissed") as mark_dismissed,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id="hitl0001-row",
            prefix="hitl0001",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_hitl_action(
            "hitl0001", "feedback", feedback="Try again"
        )

    assert result.response_file == "hitl_response.json"
    assert result.response_json == {
        "action": "feedback",
        "approved": False,
        "feedback": "Try again",
    }
    assert (artifacts_dir / "hitl_response.json").read_text(encoding="utf-8") == (
        "{\n"
        '  "action": "feedback",\n'
        '  "approved": false,\n'
        '  "feedback": "Try again"\n'
        "}\n"
    )
    mark_dismissed.assert_called_once_with("hitl0001-row")


def test_execute_mobile_question_action_writes_option_response(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "agent" / "question"
    response_dir.mkdir(parents=True)
    (response_dir / "question_request.json").write_text(
        (
            "{\n"
            '  "questions": [{\n'
            '    "question": "Which path?",\n'
            '    "options": [{"id": "fast", "label": "Fast"}, {"id": "safe", "label": "Safe"}]\n'
            "  }]\n"
            "}\n"
        ),
        encoding="utf-8",
    )
    row = _notification(
        "quest001-row",
        "2026-05-06T13:00:00+00:00",
        action="UserQuestion",
        action_data={"response_dir": str(response_dir)},
    )

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([row]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
        patch("sase.notifications.mark_dismissed") as mark_dismissed,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id="quest001-row",
            prefix="quest001",
            prefix_len=8,
            resolution="unique_prefix",
        )
        result = execute_mobile_question_action(
            "quest001",
            "answer",
            selected_option_id="safe",
            global_note="Use durable path",
        )

    assert result.response_file == "question_response.json"
    assert result.response_json == {
        "answers": [
            {
                "question": "Which path?",
                "selected": ["Safe"],
                "custom_feedback": None,
            }
        ],
        "global_note": "Use durable path",
    }
    mark_dismissed.assert_called_once_with("quest001-row")


def test_execute_mobile_question_action_rejects_invalid_option_without_write(
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "agent" / "question"
    response_dir.mkdir(parents=True)
    (response_dir / "question_request.json").write_text(
        '{"questions":[{"question":"Q?","options":[]}]}',
        encoding="utf-8",
    )
    row = _notification(
        "quest002-row",
        "2026-05-06T13:00:00+00:00",
        action="UserQuestion",
        action_data={"response_dir": str(response_dir)},
    )

    with (
        patch(
            "sase.integrations._mobile_notification_snapshot.read_notification_snapshot",
            return_value=_snapshot([row]),
        ),
        patch("sase.notifications.pending_actions.resolve_prefix") as resolve,
    ):
        resolve.return_value = SimpleNamespace(
            notification_id="quest002-row",
            prefix="quest002",
            prefix_len=8,
            resolution="unique_prefix",
        )
        try:
            execute_mobile_question_action(
                "quest002", "answer", selected_option_index=0
            )
        except MobilePlanActionError as exc:
            assert exc.code == "invalid_request"
        else:
            raise AssertionError("expected invalid option error")

    assert not (response_dir / "question_response.json").exists()
