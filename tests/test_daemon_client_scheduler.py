"""Tests for daemon scheduler helper request payloads."""

from __future__ import annotations

from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.scheduler import (
    SchedulerAxeTaskSpec,
    SchedulerAxeTaskSubmit,
    SchedulerBatchSubmit,
    SchedulerCancel,
    SchedulerLaunchSpec,
    cancel_scheduler_batch,
    read_scheduler_batch_status,
    submit_scheduler_axe_tasks,
    submit_scheduler_batch,
)
from tests._daemon_client_helpers import CaptureTransport


def test_scheduler_submit_helper_sends_batch_payload() -> None:
    response_data: dict[str, Any] = {
        "schema_version": 1,
        "handle": {
            "schema_version": 1,
            "batch_id": "batch-a",
            "idempotency_key": "idem-a",
            "queue_id": "agents",
            "project_id": "project-a",
            "slot_count": 1,
            "status": "queued",
            "created_at": "2026-05-14T06:00:00Z",
        },
        "duplicate": False,
        "status": {"schema_version": 1, "handle": {}, "slots": []},
    }
    transport = CaptureTransport("scheduler_submit", response_data)
    client = LocalDaemonClient(transport=transport)

    result = submit_scheduler_batch(
        client,
        SchedulerBatchSubmit(
            project_id="project-a",
            idempotency_key="idem-a",
            batch_id="batch-a",
            queue_id="agents",
            launch_specs=[
                SchedulerLaunchSpec(
                    project_id="project-a",
                    prompt="run this",
                    model="codex/gpt-5.5",
                )
            ],
        ),
    )

    assert result == response_data
    assert transport.envelope is not None
    assert transport.envelope["payload"] == {
        "type": "scheduler_submit",
        "data": {
            "schema_version": 1,
            "project_id": "project-a",
            "idempotency_key": "idem-a",
            "batch_id": "batch-a",
            "queue_id": "agents",
            "launch_specs": [
                {
                    "schema_version": 1,
                    "project_id": "project-a",
                    "prompt": "run this",
                    "cwd": None,
                    "model": "codex/gpt-5.5",
                    "parent_agent_id": None,
                    "workflow_id": None,
                    "metadata": {},
                }
            ],
            "metadata": {},
        },
    }


def test_scheduler_axe_task_submit_uses_axe_queue_and_metadata() -> None:
    response_data: dict[str, Any] = {
        "schema_version": 1,
        "handle": {
            "schema_version": 1,
            "batch_id": "batch-axe",
            "idempotency_key": "axe-idem",
            "queue_id": "axe",
            "project_id": "project-a",
            "slot_count": 1,
            "status": "queued",
            "created_at": "2026-05-14T06:00:00Z",
        },
        "duplicate": False,
        "status": {"schema_version": 1, "handle": {}, "slots": []},
    }
    transport = CaptureTransport("scheduler_submit", response_data)
    client = LocalDaemonClient(transport=transport)

    result = submit_scheduler_axe_tasks(
        client,
        SchedulerAxeTaskSubmit(
            project_id="project-a",
            idempotency_key="axe-idem",
            batch_id="batch-axe",
            tasks=[
                SchedulerAxeTaskSpec(
                    project_id="project-a",
                    task_kind="chop",
                    task_key="hooks:hook_checks",
                    metadata={
                        "lumberjack_name": "hooks",
                        "chop_name": "hook_checks",
                    },
                )
            ],
        ),
    )

    assert result == response_data
    assert transport.envelope is not None
    data = transport.envelope["payload"]["data"]
    assert data["queue_id"] == "axe"
    assert data["metadata"] == {"scheduler_task_kind": "axe"}
    assert data["launch_specs"][0]["prompt"] == "axe:chop:hooks:hook_checks"
    assert data["launch_specs"][0]["metadata"]["scheduler_task_kind"] == "axe"
    assert data["launch_specs"][0]["metadata"]["axe_task"] == {
        "schema_version": 1,
        "task_kind": "chop",
        "task_key": "hooks:hook_checks",
        "metadata": {
            "lumberjack_name": "hooks",
            "chop_name": "hook_checks",
        },
    }


def test_scheduler_status_and_cancel_helpers_send_recovery_payloads() -> None:
    status_data: dict[str, Any] = {
        "schema_version": 1,
        "handle": {"batch_id": "batch-a", "status": "queued"},
        "slots": [],
    }
    status_transport = CaptureTransport("scheduler_status", status_data)
    status_client = LocalDaemonClient(transport=status_transport)

    status = read_scheduler_batch_status(
        status_client,
        project_id="project-a",
        batch_id="batch-a",
    )

    assert status == status_data
    assert status_transport.envelope is not None
    assert status_transport.envelope["payload"] == {
        "type": "scheduler_status",
        "data": {
            "schema_version": 1,
            "project_id": "project-a",
            "batch_id": "batch-a",
        },
    }

    cancel_data: dict[str, Any] = {
        "schema_version": 1,
        "handle": {"batch_id": "batch-a", "status": "terminal"},
        "slots": [],
    }
    cancel_transport = CaptureTransport("scheduler_cancel", cancel_data)
    cancel_client = LocalDaemonClient(transport=cancel_transport)

    cancelled = cancel_scheduler_batch(
        cancel_client,
        SchedulerCancel(
            project_id="project-a",
            batch_id="batch-a",
            slot_id="slot-a",
            reason="operator_recovery",
            idempotency_key="recover-a",
        ),
    )

    assert cancelled == cancel_data
    assert cancel_transport.envelope is not None
    assert cancel_transport.envelope["payload"] == {
        "type": "scheduler_cancel",
        "data": {
            "schema_version": 1,
            "project_id": "project-a",
            "batch_id": "batch-a",
            "slot_id": "slot-a",
            "reason": "operator_recovery",
            "idempotency_key": "recover-a",
        },
    }
