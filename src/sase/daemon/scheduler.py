"""Typed client helpers for the daemon scheduler queue skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.constants import LOCAL_DAEMON_SCHEMA_VERSION


@dataclass(frozen=True)
class SchedulerLaunchSpec:
    project_id: str
    prompt: str
    cwd: str | None = None
    model: str | None = None
    parent_agent_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
            "project_id": self.project_id,
            "prompt": self.prompt,
            "cwd": self.cwd,
            "model": self.model,
            "parent_agent_id": self.parent_agent_id,
            "workflow_id": self.workflow_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SchedulerBatchSubmit:
    project_id: str
    idempotency_key: str
    launch_specs: list[SchedulerLaunchSpec]
    batch_id: str | None = None
    queue_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
            "project_id": self.project_id,
            "idempotency_key": self.idempotency_key,
            "batch_id": self.batch_id,
            "queue_id": self.queue_id,
            "launch_specs": [spec.to_wire() for spec in self.launch_specs],
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class SchedulerCancel:
    project_id: str
    batch_id: str
    idempotency_key: str
    slot_id: str | None = None
    reason: str | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
            "project_id": self.project_id,
            "batch_id": self.batch_id,
            "slot_id": self.slot_id,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
        }


def submit_scheduler_batch(
    client: LocalDaemonClient,
    request: SchedulerBatchSubmit,
) -> dict[str, Any]:
    return client.scheduler_submit(request.to_wire())


def read_scheduler_batch_status(
    client: LocalDaemonClient,
    *,
    project_id: str,
    batch_id: str,
) -> dict[str, Any]:
    return client.scheduler_status(project_id=project_id, batch_id=batch_id)


def cancel_scheduler_batch(
    client: LocalDaemonClient,
    request: SchedulerCancel,
) -> dict[str, Any]:
    return client.scheduler_cancel(request.to_wire())
