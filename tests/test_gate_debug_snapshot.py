"""Unit coverage for bounded, best-effort gate debug assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.debug import (
    MAX_ARTIFACT_BYTES,
    build_gate_debug_snapshot,
)
from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.models import GateCreationResult
from sase.notification_gates.operations import execute_gate_operation
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.models import Notification
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
        tmp_path / "legacy-pending.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


def _spec(*, request_id: str = "debug-gate", timeout: float | None = None) -> dict:
    value: dict = {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "debug-producer", "machine": "test-host"},
        "continuation_mode": "resume_agent",
        "payload": {"title": "Inspect this gate"},
        "presentation": {
            "sender": "debug-sender",
            "icon": "🔍",
            "title": "Inspect this gate",
            "notes": ["Review requested"],
            "tags": ["debug"],
            "files": ["preview.md"],
        },
        "query": "approve",
        "primary_branch": ["approve"],
        "options": [
            {
                "id": "approve",
                "label": "Approve",
                "icon": "✅",
                "feedback": "optional",
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
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'status': 'ok'}))\n"
                ),
            },
            {
                "path": "preview.md",
                "role": "preview",
                "content": "# Reviewed preview\n",
            },
        ],
        "auto": False,
    }
    if timeout is not None:
        value["gate_timeout_seconds"] = timeout
    return value


def _created_notification() -> tuple[GateCreationResult, Notification]:
    created = create_gate(_spec())
    [notification] = load_notifications(include_dismissed=True)
    return created, notification


def _spec_with_inputs_and_action(*, request_id: str = "debug-inputs") -> dict:
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "debug-producer", "machine": "test-host"},
        "payload": {"title": "Inspect this gate"},
        "presentation": {
            "icon": "🔍",
            "title": "Inspect this gate",
            "notes": ["Review requested"],
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
                        "id": "ticket",
                        "label": "Ticket",
                        "type": "word",
                        "required": True,
                    },
                    {"id": "token", "label": "Token", "type": "word", "secret": True},
                ],
            }
        ],
        "operations": [
            {
                "id": "show_diff",
                "kind": "run_command",
                "command": {"argv": ["commands/show_diff"]},
                "result_schema": {"type": "object"},
            }
        ],
        "resources": [
            {
                "path": "commands/approve",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'status': 'ok'}))\n"
                ),
            },
            {
                "path": "commands/show_diff",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "json.load(sys.stdin)\n"
                    "print(json.dumps({'summary': 'diff'}))\n"
                ),
            },
        ],
        "auto": False,
    }


def test_pending_snapshot_includes_integrity_options_pending_and_raw_row(
    gate_home: Path,
) -> None:
    del gate_home
    created, notification = _created_notification()

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert snapshot.status == "PENDING"
    assert snapshot.bundle_path == created.bundle_path
    assert snapshot.request.status == "ok"
    assert snapshot.response.status == "missing"
    assert [resource.integrity for resource in snapshot.resources] == ["ok", "ok"]
    assert "✓" in snapshot.overview.body
    assert "approve: Approve" in snapshot.overview.body
    assert "Primary: approve" in snapshot.overview.body
    assert "available" in snapshot.overview.body
    assert f'"id": "{notification.id}"' in snapshot.row.body


def test_answered_snapshot_and_error_records_are_rendered_newest_first(
    gate_home: Path,
) -> None:
    del gate_home
    created, notification = _created_notification()
    execute_gate_selection(
        created.bundle_path,
        ["approve"],
        feedback="Reviewed",
    )
    errors = created.bundle_path / "errors"
    errors.mkdir(exist_ok=True)
    for name, code in (("1-old.json", "old"), ("2-new.json", "new")):
        (errors / name).write_text(
            json.dumps(
                {
                    "code": code,
                    "message": f"{code} failure",
                    "source": "test",
                    "returncode": 7,
                    "stdout": "out",
                    "stderr": "err",
                }
            ),
            encoding="utf-8",
        )

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert snapshot.status == "ANSWERED"
    assert '"selected_option_ids": [' in snapshot.response.body
    assert '"approve"' in snapshot.response.body
    assert [record.code for record in snapshot.errors] == ["new", "old"]
    assert "stderr:" in snapshot.errors_artifact.body
    assert "already_handled" in snapshot.overview.body


@pytest.mark.parametrize(
    ("reason", "expected"),
    [("requester_cancelled", "CANCELLED"), ("timeout", "TIMED OUT")],
)
def test_cancelled_and_timed_out_statuses(
    gate_home: Path, reason: str, expected: str
) -> None:
    del gate_home
    created, notification = _created_notification()
    cancel_gate(created.bundle_path, reason=reason, source="test")

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert snapshot.status == expected
    assert reason in snapshot.response.body


def test_elapsed_deadline_without_cancellation_is_overdue(gate_home: Path) -> None:
    del gate_home
    created = create_gate(_spec(timeout=10))
    [notification] = load_notifications(include_dismissed=True)
    envelope = json.loads(created.request_path.read_text(encoding="utf-8"))

    snapshot = build_gate_debug_snapshot(
        notification,
        notification.action_data,
        now=float(envelope["created_at_unix"]) + 11,
    )

    assert snapshot.status == "OVERDUE"
    assert "overdue" in snapshot.overview.body


def test_corrupt_request_and_oversized_artifact_degrade_without_raising(
    gate_home: Path,
) -> None:
    del gate_home
    created, notification = _created_notification()
    created.request_path.write_bytes(b'{"unterminated":')

    corrupt = build_gate_debug_snapshot(notification, notification.action_data)
    assert corrupt.status == "UNKNOWN"
    assert corrupt.request.status == "error"
    assert "unterminated" in corrupt.request.body

    created.request_path.write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 10))
    oversized = build_gate_debug_snapshot(notification, notification.action_data)
    assert oversized.request.truncated is True
    assert "truncated after" in oversized.request.body


def test_live_hash_mismatches_are_visible(gate_home: Path) -> None:
    del gate_home
    created, notification = _created_notification()
    envelope = json.loads(created.request_path.read_text(encoding="utf-8"))
    envelope["producer"]["agent"] = "tampered"
    created.request_path.write_text(json.dumps(envelope), encoding="utf-8")
    (created.bundle_path / "preview.md").write_text("changed", encoding="utf-8")

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert "Request integrity" in snapshot.overview.body
    assert "✗ MISMATCH" in snapshot.overview.body
    assert snapshot.resources[1].integrity == "mismatch"
    assert "expected" in snapshot.resources[1].detail


def test_missing_bundle_and_non_gate_notification_have_explicit_empty_states(
    gate_home: Path,
) -> None:
    missing_root = gate_home / "requests" / "custom" / "missing"
    gate = Notification(
        id="gate-row",
        timestamp="2026-07-17T10:00:00+00:00",
        sender="test",
        action="CustomGate",
        action_data={
            "request_id": "missing",
            "request_kind": "custom",
            "bundle_path": str(missing_root),
        },
    )
    ordinary = Notification(
        id="ordinary-row",
        timestamp="2026-07-17T10:00:00+00:00",
        sender="test",
        action="JumpToAgent",
    )

    missing = build_gate_debug_snapshot(gate, gate.action_data)
    non_gate = build_gate_debug_snapshot(ordinary, ordinary.action_data)

    assert missing.bundle_path == missing_root
    assert missing.request.status == "missing"
    assert missing.status == "UNKNOWN"
    assert non_gate.bundle_path is None
    assert "No gate bundle attached" in non_gate.overview.body
    assert '"id": "ordinary-row"' in non_gate.row.body


def test_flag_triage_snapshot_uses_the_flag_action_icon(gate_home: Path) -> None:
    from tests.test_bead.flag_gate_test_helpers import flag_triage_spec

    del gate_home
    created = create_gate(flag_triage_spec(request_id="debug-flag"))
    [notification] = load_notifications(include_dismissed=True)

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert notification.action == "FlagTriage"
    assert snapshot.kind == "flag_triage"
    assert snapshot.bundle_path == created.bundle_path
    assert snapshot.icon == "⚑"
    assert "Kind                flag_triage" in snapshot.overview.body
    assert "No gate bundle attached" not in snapshot.overview.body


def test_legacy_hitl_bundle_is_inspected_best_effort(gate_home: Path) -> None:
    legacy = gate_home / "legacy-hitl"
    legacy.mkdir()
    (legacy / "hitl_request.json").write_text(
        json.dumps({"step_name": "review", "output": {"ok": True}}),
        encoding="utf-8",
    )
    notification = Notification(
        id="legacy-hitl-row",
        timestamp="2026-07-17T10:00:00+00:00",
        sender="workflow",
        action="HITL",
        action_data={"artifacts_dir": str(legacy)},
    )

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert snapshot.bundle_path == legacy
    assert snapshot.kind == "hitl"
    assert snapshot.status == "PENDING"
    assert "legacy" in snapshot.overview.body


def test_raw_row_lookup_scans_past_large_jsonl_prefix(gate_home: Path) -> None:
    del gate_home
    _created, notification = _created_notification()
    from sase.notifications import store

    notifications_path = Path(store._notifications_file())
    target_line = notifications_path.read_text(encoding="utf-8").strip()
    padding = json.dumps(
        {
            "id": "padding",
            "timestamp": "2026-07-17T10:00:00+00:00",
            "sender": "padding",
            "notes": ["x" * 1000],
        }
    )
    notifications_path.write_text(
        "\n".join([padding] * (MAX_ARTIFACT_BYTES // len(padding) + 2))
        + "\n"
        + target_line
        + "\n",
        encoding="utf-8",
    )

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert f'"id": "{notification.id}"' in snapshot.row.body
    assert '"action": "CustomGate"' in snapshot.row.body


def test_malformed_in_memory_row_is_normalized_for_diagnostics(
    gate_home: Path,
) -> None:
    del gate_home
    snapshot = build_gate_debug_snapshot(
        {
            "id": "malformed",
            "timestamp": 42,
            "sender": None,
            "icon": ["not", "an", "icon"],
            "tags": "not-a-list",
            "action_data": ["not", "a", "mapping"],
        }
    )

    assert snapshot.status == "UNKNOWN"
    assert snapshot.notification_id == "malformed"
    assert "No gate bundle attached" in snapshot.overview.body


def test_overview_lists_declared_input_fields_per_option(gate_home: Path) -> None:
    del gate_home
    create_gate(_spec_with_inputs_and_action())
    [notification] = load_notifications(include_dismissed=True)

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert "ticket (word, required)" in snapshot.overview.body
    assert "token (word, optional) · secret" in snapshot.overview.body


def test_journal_tab_is_missing_before_any_execution(gate_home: Path) -> None:
    del gate_home
    create_gate(_spec_with_inputs_and_action(request_id="debug-journal-empty"))
    [notification] = load_notifications(include_dismissed=True)

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert snapshot.journal.status == "missing"
    assert "No execution journal" in snapshot.journal.body


def test_journal_tab_lists_attempts_and_executed_actions_newest_first(
    gate_home: Path,
) -> None:
    del gate_home
    created = create_gate(_spec_with_inputs_and_action(request_id="debug-journal"))
    [notification] = load_notifications(include_dismissed=True)
    execute_gate_operation(created.bundle_path, "show_diff")
    execute_gate_selection(
        created.bundle_path,
        ["approve"],
        option_inputs={"approve": {"ticket": "SASE-1"}},
    )

    snapshot = build_gate_debug_snapshot(notification, notification.action_data)

    assert snapshot.journal.status == "ok"
    body = snapshot.journal.body
    assert "attempt_completed" in body
    assert "operation_ran" in body
    assert "action: show_diff" in body
    # Newest first: attempt_completed (from the answer) precedes operation_ran
    # (from the action that ran before it).
    assert body.index("attempt_completed") < body.index("operation_ran")
