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
class SchedulerAxeTaskSpec:
    project_id: str
    task_kind: str
    task_key: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_launch_spec(self) -> SchedulerLaunchSpec:
        metadata = dict(self.metadata)
        metadata["scheduler_task_kind"] = "axe"
        metadata["axe_task"] = {
            "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
            "task_kind": self.task_kind,
            "task_key": self.task_key,
            "metadata": self.metadata,
        }
        return SchedulerLaunchSpec(
            project_id=self.project_id,
            prompt=f"axe:{self.task_kind}:{self.task_key}",
            metadata=metadata,
        )


@dataclass(frozen=True)
class SchedulerAxeTaskSubmit:
    project_id: str
    idempotency_key: str
    tasks: list[SchedulerAxeTaskSpec]
    batch_id: str | None = None
    queue_id: str = "axe"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_batch_submit(self) -> SchedulerBatchSubmit:
        metadata = dict(self.metadata)
        metadata["scheduler_task_kind"] = "axe"
        return SchedulerBatchSubmit(
            project_id=self.project_id,
            idempotency_key=self.idempotency_key,
            batch_id=self.batch_id,
            queue_id=self.queue_id,
            launch_specs=[task.to_launch_spec() for task in self.tasks],
            metadata=metadata,
        )

    def to_wire(self) -> dict[str, Any]:
        return self.to_batch_submit().to_wire()


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


def submit_scheduler_axe_tasks(
    client: LocalDaemonClient,
    request: SchedulerAxeTaskSubmit,
) -> dict[str, Any]:
    return submit_scheduler_batch(client, request.to_batch_submit())


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
