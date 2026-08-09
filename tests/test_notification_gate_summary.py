"""Coverage for the frontend-free gate summary projection."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sase.notification_gates.executor import cancel_gate, execute_gate_selection
from sase.notification_gates.models import GateCreationResult
from sase.notification_gates.presentation import GATE_TITLE_ACTION_DATA_KEY
from sase.notification_gates.service import create_gate
from sase.notification_gates.summary import (
    GateSummary,
    GateSummaryOption,
    gate_summary_from_notification,
    load_gate_summary,
)
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications

from tests._notification_gates_fixtures import custom_gate_spec


def _created_notification() -> tuple[GateCreationResult, Notification]:
    created = create_gate(custom_gate_spec())
    [notification] = load_notifications(include_dismissed=True)
    return created, notification


def _echo_command() -> str:
    return (
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'status': 'ok'}))\n"
    )


def _inputs_gate_spec(*, request_id: str = "inputs-request") -> dict[str, object]:
    """A custom gate with one option that declares typed and secret inputs."""
    return {
        "schema_version": 3,
        "request_id": request_id,
        "kind": "custom",
        "producer": {"agent": "test"},
        "payload": {},
        "presentation": {
            "icon": "🧪",
            "title": "Deploy with inputs",
            "notes": ["Deploy"],
        },
        "query": "deploy OR skip",
        "primary_branch": ["deploy"],
        "options": [
            {
                "id": "deploy",
                "label": "Deploy",
                "command": {"argv": ["commands/deploy"]},
                "inputs": [
                    {
                        "id": "target_env",
                        "label": "Target env",
                        "type": "word",
                        "required": True,
                    },
                    {
                        "id": "token",
                        "label": "Token",
                        "type": "word",
                        "secret": True,
                    },
                ],
            },
            {
                "id": "skip",
                "label": "Skip",
                "command": {"argv": ["commands/skip"]},
            },
        ],
        "resources": [
            {"path": "commands/deploy", "role": "command", "content": _echo_command()},
            {"path": "commands/skip", "role": "command", "content": _echo_command()},
        ],
        "auto": False,
    }


def _deploy_option(summary: GateSummary) -> GateSummaryOption:
    return next(
        option
        for branch in summary.branches
        for option in branch.options
        if option.id == "deploy"
    )


def _skip_option(summary: GateSummary) -> GateSummaryOption:
    return next(
        option
        for branch in summary.branches
        for option in branch.options
        if option.id == "skip"
    )


def test_gate_summary_from_notification_none_for_non_gate_row() -> None:
    notification = Notification(
        id="n1", timestamp="2026-08-07T09:00:00-04:00", sender="test", action=None
    )
    assert gate_summary_from_notification(notification) is None


def test_gate_summary_from_notification_reads_title_from_action_data() -> None:
    notification = Notification(
        id="n1",
        timestamp="2026-08-07T09:00:00-04:00",
        sender="test",
        action="CustomGate",
        action_data={
            GATE_TITLE_ACTION_DATA_KEY: "Pin sase-core-rs to >=0.19.0",
            "request_id": "pin-core",
        },
    )
    summary = gate_summary_from_notification(notification)
    assert summary is not None
    assert summary.title == "Pin sase-core-rs to >=0.19.0"
    assert summary.request_id == "pin-core"
    assert summary.status == "pending"
    assert summary.branches == ()
    assert summary.bundle_path is None
    assert summary.unavailable_reason is None


def test_gate_summary_from_notification_falls_back_to_display_title() -> None:
    notification = Notification(
        id="n1",
        timestamp="2026-08-07T09:00:00-04:00",
        sender="test",
        action="CustomGate",
        action_data={"request_id": "no-title"},
    )
    summary = gate_summary_from_notification(notification)
    assert summary is not None
    assert summary.title == "Custom Gate"


def test_gate_summary_from_notification_performs_no_disk_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("gate_summary_from_notification must not touch disk")

    monkeypatch.setattr(
        "sase.notification_gates.summary.resolve_notification_bundle", _fail
    )
    notification = Notification(
        id="n1",
        timestamp="2026-08-07T09:00:00-04:00",
        sender="test",
        action="CustomGate",
        action_data={"request_id": "abc"},
        files=["a.diff", "b.diff"],
    )
    summary = gate_summary_from_notification(notification)
    assert summary is not None
    assert summary.attachments == ("a.diff", "b.diff")


def test_load_gate_summary_none_for_non_gate_row() -> None:
    notification = Notification(
        id="n1", timestamp="2026-08-07T09:00:00-04:00", sender="test", action=None
    )
    assert load_gate_summary(notification) is None


def test_load_gate_summary_pending(gate_home: Path) -> None:
    del gate_home
    _created, notification = _created_notification()

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.status == "pending"
    assert summary.unavailable_reason is None
    assert [branch.option_ids for branch in summary.branches]
    primary = next(branch for branch in summary.branches if branch.is_primary)
    assert primary.option_ids == ("proceed", "audit", "broken")


def test_load_gate_summary_overdue_past_its_deadline(gate_home: Path) -> None:
    import time

    del gate_home
    spec = custom_gate_spec()
    spec["gate_timeout_seconds"] = 0.01
    create_gate(spec)
    [notification] = load_notifications(include_dismissed=True)
    time.sleep(0.05)  # sase-test-wait: gate timeout expiry

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.status == "overdue"
    assert summary.deadline_at is not None


def test_load_gate_summary_answered_with_selection_and_feedback(
    gate_home: Path,
) -> None:
    del gate_home
    created, notification = _created_notification()
    execute_gate_selection(
        created.bundle_path, ["proceed", "audit"], feedback="Looks safe"
    )

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.status == "answered"
    assert summary.selected_option_ids == ("proceed", "audit")
    assert summary.feedback == "Looks safe"
    selected_ids = {
        option.id
        for branch in summary.branches
        for option in branch.options
        if option.selected
    }
    assert selected_ids == {"proceed", "audit"}


def test_load_gate_summary_cancelled(gate_home: Path) -> None:
    del gate_home
    created, notification = _created_notification()
    cancel_gate(created.bundle_path, reason="requester_cancelled")

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.status == "cancelled"


def test_load_gate_summary_cancelled_with_timeout_reason_is_timed_out(
    gate_home: Path,
) -> None:
    del gate_home
    created, notification = _created_notification()
    cancel_gate(created.bundle_path, reason="timeout")

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.status == "timed_out"


def test_load_gate_summary_deleted_bundle_directory_degrades(gate_home: Path) -> None:
    del gate_home
    created, notification = _created_notification()
    shutil.rmtree(created.bundle_path)

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.unavailable_reason is not None
    assert summary.title == "Confirm guarded work"


def test_load_gate_summary_truncated_request_degrades(gate_home: Path) -> None:
    del gate_home
    created, notification = _created_notification()
    (created.bundle_path / "request.json").write_bytes(b'{"unterminated":')

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.unavailable_reason is not None
    assert summary.branches == ()


def test_load_gate_summary_legacy_bundle_degrades(
    gate_home: Path, tmp_path: Path
) -> None:
    del gate_home
    notification = Notification(
        id="legacy-1",
        timestamp="2026-08-07T09:00:00-04:00",
        sender="test",
        action="HITL",
        action_data={"artifacts_dir": str(tmp_path / "legacy-hitl")},
    )

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.unavailable_reason == "this gate uses a legacy bundle layout"


def test_load_gate_summary_never_raises_for_malformed_action_data(
    gate_home: Path,
) -> None:
    del gate_home
    notification = Notification(
        id="n1",
        timestamp="2026-08-07T09:00:00-04:00",
        sender="test",
        action="CustomGate",
        action_data={"request_id": "does-not-exist"},
    )

    summary = load_gate_summary(notification)

    assert summary is not None
    assert summary.unavailable_reason is not None


def test_load_gate_summary_pending_lists_declared_input_fields(gate_home: Path) -> None:
    del gate_home
    create_gate(_inputs_gate_spec())
    [notification] = load_notifications(include_dismissed=True)

    summary = load_gate_summary(notification)

    assert summary is not None
    deploy = _deploy_option(summary)
    assert [field.id for field in deploy.input_fields] == ["target_env", "token"]
    assert deploy.submitted_input is None
    assert _skip_option(summary).input_fields == ()
    assert summary.option_inputs == {}


def test_load_gate_summary_answered_reports_submitted_input_with_secret_redacted(
    gate_home: Path,
) -> None:
    del gate_home
    created = create_gate(_inputs_gate_spec(request_id="inputs-answered"))
    [notification] = load_notifications(include_dismissed=True)
    execute_gate_selection(
        created.bundle_path,
        ["deploy"],
        option_inputs={"deploy": {"target_env": "staging", "token": "s3cr3t"}},
    )

    summary = load_gate_summary(notification)

    assert summary is not None
    deploy = _deploy_option(summary)
    assert deploy.selected is True
    assert deploy.submitted_input == {
        "target_env": "staging",
        "token": {"$redacted": True},
    }
    assert summary.option_inputs["deploy"] == deploy.submitted_input

    skip = _skip_option(summary)
    assert skip.selected is False
    assert skip.submitted_input is None
