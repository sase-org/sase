"""Daemon scheduler helpers for agent lifecycle mutations."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from sase.config import load_merged_config
from sase.daemon.client import (
    LocalDaemonClient,
    LocalDaemonError,
)
from sase.daemon.constants import LOCAL_DAEMON_SCHEMA_VERSION
from sase.daemon.paths import daemon_disabled
from sase.daemon.scheduler import (
    SchedulerBatchSubmit,
    SchedulerLaunchSpec,
    submit_scheduler_batch,
)

LifecycleOperation = Literal["kill", "dismiss", "cleanup", "revive"]
LifecycleMode = Literal["direct", "shadow", "daemon"]

_ENV_MODE = "SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE"
_LEGACY_ENV_MODE = "SASE_SCHEDULER_LIFECYCLE_MODE"
_QUEUE_ID = "agent-lifecycle"
_TASK_KIND = "agent_lifecycle"
_MODE_ALIASES: dict[str, LifecycleMode] = {
    "off": "direct",
    "false": "direct",
    "0": "direct",
    "direct": "direct",
    "shadow": "shadow",
    "daemon": "daemon",
    "daemon_authoritative": "daemon",
    "authoritative": "daemon",
    "on": "daemon",
    "true": "daemon",
    "1": "daemon",
}


@dataclass(frozen=True)
class _LifecycleTarget:
    """One agent lifecycle scheduler target."""

    operation: LifecycleOperation
    project_id: str = "global"
    name: str | None = None
    agent_type: str | None = None
    cl_name: str | None = None
    raw_suffix: str | None = None
    pid: int | None = None
    artifacts_dir: str | None = None
    project_file: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def target_id(self) -> str:
        if self.name:
            return f"name:{self.name}"
        if self.raw_suffix:
            return f"suffix:{self.raw_suffix}"
        if self.artifacts_dir:
            return f"artifacts:{self.artifacts_dir}"
        identity = ":".join(
            value or "unknown"
            for value in (self.agent_type, self.cl_name, self.raw_suffix)
        )
        return f"identity:{identity}"

    def to_metadata(self) -> dict[str, Any]:
        return {
            "scheduler_task_kind": _TASK_KIND,
            "operation": self.operation,
            "target": {
                "target_id": self.target_id(),
                "name": self.name,
                "agent_type": self.agent_type,
                "cl_name": self.cl_name,
                "raw_suffix": self.raw_suffix,
                "pid": self.pid,
                "artifacts_dir": self.artifacts_dir,
                "project_file": self.project_file,
                "reason": self.reason,
                **self.metadata,
            },
        }


@dataclass(frozen=True)
class _LifecycleSubmitResult:
    """Outcome for a best-effort lifecycle scheduler submission."""

    submitted: bool
    mode: LifecycleMode
    response: dict[str, Any] | None = None
    fallback_reason: str | None = None
    fallback_message: str | None = None


def _scheduler_lifecycle_mode() -> LifecycleMode:
    """Return the configured lifecycle scheduler rollout mode."""

    env_value = os.environ.get(_ENV_MODE) or os.environ.get(_LEGACY_ENV_MODE)
    parsed = _parse_mode(env_value)
    if parsed is not None:
        return parsed

    daemon_config = load_merged_config().get("daemon")
    scheduler_config = (
        daemon_config.get("scheduler") if isinstance(daemon_config, dict) else None
    )
    if not isinstance(scheduler_config, dict):
        return "direct"
    parsed = _parse_mode(scheduler_config.get("lifecycle_mode"))
    return parsed or "direct"


def _submit_lifecycle_batch(
    targets: list[_LifecycleTarget],
    *,
    idempotency_key: str | None = None,
    batch_id: str | None = None,
    client: LocalDaemonClient | None = None,
) -> dict[str, Any]:
    """Submit lifecycle targets as one scheduler batch with one slot per target."""

    if not targets:
        raise ValueError("lifecycle scheduler batch requires at least one target")

    project_id = _batch_project_id(targets)
    key = idempotency_key or _stable_idempotency_key(targets)
    batch = SchedulerBatchSubmit(
        project_id=project_id,
        idempotency_key=key,
        batch_id=batch_id or f"lifecycle-{_short_hash(key)}",
        queue_id=_QUEUE_ID,
        launch_specs=[
            SchedulerLaunchSpec(
                project_id=target.project_id or project_id,
                prompt=_prompt_for_target(target),
                metadata=target.to_metadata(),
            )
            for target in targets
        ],
        metadata={
            "scheduler_task_kind": _TASK_KIND,
            "operation": _aggregate_operation(targets),
            "target_count": len(targets),
        },
    )
    return submit_scheduler_batch(client or LocalDaemonClient(), batch)


def submit_lifecycle_batch_if_enabled(
    targets: list[_LifecycleTarget],
    *,
    args: object | None = None,
    client: LocalDaemonClient | None = None,
) -> _LifecycleSubmitResult:
    """Submit lifecycle work in shadow/daemon mode and degrade to direct mode."""

    mode = _scheduler_lifecycle_mode()
    if mode == "direct":
        return _LifecycleSubmitResult(
            submitted=False,
            mode=mode,
            fallback_reason="direct_mode",
            fallback_message="daemon scheduler lifecycle routing disabled",
        )
    if os.environ.get("SASE_DAEMON_SCHEDULER_HOST_BRIDGE") == "1":
        return _LifecycleSubmitResult(
            submitted=False,
            mode=mode,
            fallback_reason="host_bridge",
            fallback_message="scheduler host bridge must execute lifecycle directly",
        )
    if daemon_disabled(args):
        return _LifecycleSubmitResult(
            submitted=False,
            mode=mode,
            fallback_reason="daemon_disabled",
            fallback_message="daemon scheduler lifecycle routing disabled by args/env",
        )
    daemon_client = client or LocalDaemonClient()
    try:
        capabilities = daemon_client.capabilities().get("capabilities", [])
        if "scheduler.submit" not in capabilities:
            return _LifecycleSubmitResult(
                submitted=False,
                mode=mode,
                fallback_reason="unsupported_capability",
                fallback_message="local daemon does not advertise scheduler.submit",
            )
        response = _submit_lifecycle_batch(targets, client=daemon_client)
        return _LifecycleSubmitResult(submitted=True, mode=mode, response=response)
    except LocalDaemonError as exc:
        return _LifecycleSubmitResult(
            submitted=False,
            mode=mode,
            fallback_reason=getattr(exc, "fallback_reason", None)
            or getattr(exc, "code", "daemon_error"),
            fallback_message=str(exc),
        )


def lifecycle_target_from_agent(
    operation: LifecycleOperation,
    agent: Any,
    *,
    reason: str | None = None,
) -> _LifecycleTarget:
    """Build a lifecycle target from a TUI Agent-like object."""

    project_id = _project_id_from_agent(agent)
    agent_type_value = getattr(agent, "agent_type", None)
    agent_type = getattr(agent_type_value, "value", None)
    if agent_type is None and agent_type_value is not None:
        agent_type = str(agent_type_value)
    return _LifecycleTarget(
        operation=operation,
        project_id=project_id,
        name=getattr(agent, "agent_name", None),
        agent_type=agent_type,
        cl_name=getattr(agent, "cl_name", None),
        raw_suffix=getattr(agent, "raw_suffix", None),
        pid=getattr(agent, "pid", None),
        artifacts_dir=getattr(agent, "artifacts_dir", None),
        project_file=getattr(agent, "project_file", None),
        reason=reason,
        metadata={
            "workflow": getattr(agent, "workflow", None),
            "status": getattr(agent, "status", None),
            "workspace_num": getattr(agent, "workspace_num", None),
        },
    )


def lifecycle_target_for_name(
    operation: LifecycleOperation,
    name: str,
    *,
    project_id: str = "global",
    reason: str | None = None,
    exact_name: bool = False,
) -> _LifecycleTarget:
    """Build a lifecycle target for a named-agent CLI/mobile operation."""

    return _LifecycleTarget(
        operation=operation,
        project_id=project_id,
        name=name,
        reason=reason,
        metadata={"exact_name": exact_name},
    )


def _batch_project_id(targets: list[_LifecycleTarget]) -> str:
    project_ids = {target.project_id for target in targets if target.project_id}
    if len(project_ids) == 1:
        return next(iter(project_ids))
    return "global"


def _stable_idempotency_key(targets: list[_LifecycleTarget]) -> str:
    wire = [target.to_metadata() for target in targets]
    raw = json.dumps(wire, sort_keys=True, separators=(",", ":"))
    return f"agent-lifecycle:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _prompt_for_target(target: _LifecycleTarget) -> str:
    return f"scheduler lifecycle {target.operation} {target.target_id()}"


def _aggregate_operation(targets: list[_LifecycleTarget]) -> str:
    operations = {target.operation for target in targets}
    if len(operations) == 1:
        operation = next(iter(operations))
        return f"bulk_{operation}" if len(targets) > 1 else operation
    return "bulk_lifecycle"


def _project_id_from_agent(agent: Any) -> str:
    project_file = getattr(agent, "project_file", None)
    if isinstance(project_file, str) and project_file:
        from pathlib import Path

        name = Path(project_file).parent.name
        if name:
            return name
    project = getattr(agent, "project", None)
    if isinstance(project, str) and project:
        return project
    return "global"


def _parse_mode(value: object) -> LifecycleMode | None:
    if not isinstance(value, str):
        return None
    return _MODE_ALIASES.get(value.strip().lower().replace("-", "_"))


__all__ = [
    "LifecycleMode",
    "LifecycleOperation",
    "lifecycle_target_for_name",
    "lifecycle_target_from_agent",
    "submit_lifecycle_batch_if_enabled",
]
