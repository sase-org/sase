"""Shared execution core for Rust-backed agent launch fan-out plans."""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.core.agent_launch_wire import LaunchFanoutPlanWire, LaunchFanoutSlotWire
from sase.daemon.errors import LocalDaemonError
from sase.running_field import WorkspaceClaimError


@dataclass(frozen=True)
class LaunchExecutionContext:
    """Host-resolved context used to execute one or more launch slots."""

    cl_name: str
    project_file: str
    project_name: str
    update_target: str = ""
    history_sort_key: str = ""
    is_home_mode: bool = False
    vcs_ref: tuple[str, str] | None = None
    deferred_workspace: bool = False
    workspace_num: int | None = None
    workspace_dir: str | None = None
    use_preallocated_workspace: bool = False


@dataclass(frozen=True)
class LaunchSpawnRequest:
    """Resolved low-level spawn request for one launch slot."""

    cl_name: str
    project_file: str
    workspace_dir: str
    workspace_num: int
    workflow_name: str
    prompt: str
    timestamp: str
    update_target: str = ""
    project_name: str = ""
    history_sort_key: str = ""
    is_home_mode: bool = False
    vcs_ref: tuple[str, str] | None = None
    deferred_workspace: bool = False
    local_xprompts_file: str | None = None
    extra_env: dict[str, str] | None = None
    transfer_from_pid: int | None = None

    def as_spawn_kwargs(self) -> dict[str, object]:
        """Return keyword arguments accepted by low-level launch spawners."""
        return {
            "cl_name": self.cl_name,
            "project_file": self.project_file,
            "workspace_dir": self.workspace_dir,
            "workspace_num": self.workspace_num,
            "workflow_name": self.workflow_name,
            "prompt": self.prompt,
            "timestamp": self.timestamp,
            "update_target": self.update_target,
            "project_name": self.project_name,
            "history_sort_key": self.history_sort_key,
            "is_home_mode": self.is_home_mode,
            "vcs_ref": self.vcs_ref,
            "deferred_workspace": self.deferred_workspace,
            "local_xprompts_file": self.local_xprompts_file,
            "extra_env": self.extra_env,
            "retry_transfer_from_pid": self.transfer_from_pid,
        }


@dataclass(frozen=True)
class _LaunchExecutionRecord:
    """One executed launch slot plus the spawn result, when available."""

    slot: LaunchFanoutSlotWire
    request: LaunchSpawnRequest
    result: AgentLaunchResult | None


@dataclass(frozen=True)
class _LaunchExecutionResult:
    """Summary returned after executing a launch fan-out plan."""

    records: list[_LaunchExecutionRecord]

    @property
    def results(self) -> list[AgentLaunchResult]:
        return [record.result for record in self.records if record.result is not None]

    @property
    def launched_count(self) -> int:
        return len(self.records)


SpawnCallback = Callable[[LaunchSpawnRequest], AgentLaunchResult | None]
SlotContextCallback = Callable[
    [LaunchFanoutSlotWire, LaunchExecutionContext], LaunchExecutionContext
]
SlotEnvCallback = Callable[[LaunchFanoutSlotWire], dict[str, str]]
SlotLocalXpromptsCallback = Callable[[LaunchFanoutSlotWire], str | None]
SlotExecutedCallback = Callable[[_LaunchExecutionRecord], None]

_WORKSPACE_ALLOCATION_MAX_RETRIES_ENV = "SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES"
_DEFAULT_WORKSPACE_ALLOCATION_MAX_RETRIES = 5


def _default_spawn(request: LaunchSpawnRequest) -> AgentLaunchResult:
    from sase.agent import launcher as launcher_mod

    return launcher_mod.spawn_agent_subprocess(
        cl_name=request.cl_name,
        project_file=request.project_file,
        workspace_dir=request.workspace_dir,
        workspace_num=request.workspace_num,
        workflow_name=request.workflow_name,
        prompt=request.prompt,
        timestamp=request.timestamp,
        update_target=request.update_target,
        project_name=request.project_name,
        history_sort_key=request.history_sort_key,
        is_home_mode=request.is_home_mode,
        vcs_ref=request.vcs_ref,
        deferred_workspace=request.deferred_workspace,
        local_xprompts_file=request.local_xprompts_file,
        extra_env=request.extra_env,
        retry_transfer_from_pid=request.transfer_from_pid,
    )


def execute_launch_plan(
    plan: LaunchFanoutPlanWire,
    context: LaunchExecutionContext,
    *,
    spawn: SpawnCallback | None = None,
    on_slot_executed: SlotExecutedCallback | None = None,
    slot_context: SlotContextCallback | None = None,
    slot_extra_env: SlotEnvCallback | None = None,
    slot_local_xprompts_file: SlotLocalXpromptsCallback | None = None,
    extra_env: dict[str, str] | None = None,
    timestamp_allocator: LaunchTimestampBatchAllocator | None = None,
    base_timestamp: str | None = None,
) -> _LaunchExecutionResult:
    """Execute a normalized fan-out plan through a host-provided spawn hook."""
    if not plan.slots:
        return _LaunchExecutionResult(records=[])

    from sase.agent.names import ensure_historical_auto_name_migration

    ensure_historical_auto_name_migration()

    from sase.agent.launch_validation import validate_launch_name_requests

    validate_launch_name_requests([slot.prompt for slot in plan.slots])

    allocator = timestamp_allocator or LaunchTimestampBatchAllocator()
    missing_timestamp_count = sum(1 for slot in plan.slots if slot.timestamp is None)
    if base_timestamp is not None and missing_timestamp_count == 1:
        allocated = [base_timestamp]
    else:
        allocated = allocator.allocate(missing_timestamp_count)
    timestamp_by_slot = _timestamps_by_slot(plan, allocated)

    scheduler_execution = _try_scheduler_launch_plan(
        plan,
        context,
        timestamp_by_slot=timestamp_by_slot,
        slot_context=slot_context,
        slot_extra_env=slot_extra_env,
        slot_local_xprompts_file=slot_local_xprompts_file,
        extra_env=extra_env,
        on_slot_executed=on_slot_executed,
    )
    if scheduler_execution is not None:
        return scheduler_execution

    allocated_iter = iter(allocated)

    spawn_fn = spawn or _default_spawn
    records: list[_LaunchExecutionRecord] = []
    for slot in plan.slots:
        timestamp = slot.timestamp or next(allocated_iter)
        workflow_name = slot.workflow_name or f"ace(run)-{timestamp}"
        slot_ctx = slot_context(slot, context) if slot_context else context
        env = dict(extra_env or {})
        if slot_extra_env is not None:
            env.update(slot_extra_env(slot))
        local_xprompts_file = (
            None if slot_local_xprompts_file is None else slot_local_xprompts_file(slot)
        )

        request, result = _spawn_slot_with_workspace_retry(
            slot=slot,
            context=slot_ctx,
            workflow_name=workflow_name,
            timestamp=timestamp,
            extra_env=env or None,
            local_xprompts_file=local_xprompts_file,
            spawn=spawn_fn,
        )
        record = _LaunchExecutionRecord(slot=slot, request=request, result=result)
        records.append(record)
        if on_slot_executed is not None:
            on_slot_executed(record)

    return _LaunchExecutionResult(records=records)


def _timestamps_by_slot(
    plan: LaunchFanoutPlanWire,
    allocated: list[str],
) -> dict[int, str]:
    allocated_iter = iter(allocated)
    timestamps: dict[int, str] = {}
    for slot in plan.slots:
        timestamps[slot.slot_index] = slot.timestamp or next(allocated_iter)
    return timestamps


def _try_scheduler_launch_plan(
    plan: LaunchFanoutPlanWire,
    context: LaunchExecutionContext,
    *,
    timestamp_by_slot: dict[int, str],
    slot_context: SlotContextCallback | None,
    slot_extra_env: SlotEnvCallback | None,
    slot_local_xprompts_file: SlotLocalXpromptsCallback | None,
    extra_env: dict[str, str] | None,
    on_slot_executed: SlotExecutedCallback | None,
) -> _LaunchExecutionResult | None:
    from sase.daemon.scheduler_config import (
        scheduler_launch_disable_reason,
        scheduler_launch_mode,
    )

    if scheduler_launch_disable_reason() is not None:
        return None

    mode = scheduler_launch_mode()
    request = _scheduler_batch_request_for_plan(
        plan,
        context,
        timestamp_by_slot=timestamp_by_slot,
        slot_context=slot_context,
        slot_extra_env=slot_extra_env,
        slot_local_xprompts_file=slot_local_xprompts_file,
        extra_env=extra_env,
        mode=mode,
    )
    if request is None:
        return None

    from sase.daemon.client import LocalDaemonClient
    from sase.daemon.scheduler import submit_scheduler_batch

    try:
        response = submit_scheduler_batch(LocalDaemonClient(), request)
    except LocalDaemonError:
        return None

    if mode == "shadow":
        return None

    return _scheduler_execution_result(
        plan,
        context,
        timestamp_by_slot=timestamp_by_slot,
        response=response,
        on_slot_executed=on_slot_executed,
    )


def _scheduler_batch_request_for_plan(
    plan: LaunchFanoutPlanWire,
    context: LaunchExecutionContext,
    *,
    timestamp_by_slot: dict[int, str],
    slot_context: SlotContextCallback | None,
    slot_extra_env: SlotEnvCallback | None,
    slot_local_xprompts_file: SlotLocalXpromptsCallback | None,
    extra_env: dict[str, str] | None,
    mode: str,
) -> Any | None:
    from sase.daemon.scheduler import SchedulerBatchSubmit, SchedulerLaunchSpec

    specs: list[SchedulerLaunchSpec] = []
    for slot in plan.slots:
        slot_ctx = slot_context(slot, context) if slot_context else context
        slot_env = _scheduler_slot_env(slot, extra_env, slot_extra_env)
        local_xprompts_file = (
            None if slot_local_xprompts_file is None else slot_local_xprompts_file(slot)
        )
        if (
            _unsupported_scheduler_slot_reason(
                slot_ctx,
                slot_env=slot_env,
                local_xprompts_file=local_xprompts_file,
            )
            is not None
        ):
            return None

        timestamp = timestamp_by_slot[slot.slot_index]
        workflow_name = slot.workflow_name or f"ace(run)-{timestamp}"
        specs.append(
            SchedulerLaunchSpec(
                project_id=_scheduler_project_id(slot_ctx),
                prompt=slot.prompt,
                cwd=_scheduler_launch_cwd(slot_ctx),
                model=slot.model,
                metadata={
                    "source": "agent_launch_executor",
                    "launch_kind": plan.launch_kind,
                    "slot_index": slot.slot_index,
                    "timestamp": timestamp,
                    "workflow_name": workflow_name,
                    "cl_name": slot_ctx.cl_name,
                    "project_file": slot_ctx.project_file,
                    "project_name": slot_ctx.project_name,
                    "update_target": slot_ctx.update_target,
                    "history_sort_key": slot_ctx.history_sort_key,
                    "is_home_mode": slot_ctx.is_home_mode,
                    "vcs_ref": slot_ctx.vcs_ref,
                    "deferred_workspace": slot_ctx.deferred_workspace,
                    "workspace_num": slot_ctx.workspace_num,
                    "workspace_dir": slot_ctx.workspace_dir,
                    "scheduler_launch_mode": mode,
                },
            )
        )

    if not specs:
        return None

    idempotency_key = _scheduler_launch_idempotency_key(
        plan=plan,
        context=context,
        specs=specs,
    )
    batch_id = f"launch_{_short_hash(idempotency_key)}"
    return SchedulerBatchSubmit(
        project_id=_scheduler_project_id(context),
        idempotency_key=idempotency_key,
        batch_id=batch_id,
        queue_id="agents",
        launch_specs=specs,
        metadata={
            "source": "agent_launch_executor",
            "launch_kind": plan.launch_kind,
            "slot_count": len(specs),
            "scheduler_launch_mode": mode,
        },
    )


def _scheduler_launch_idempotency_key(
    *,
    plan: LaunchFanoutPlanWire,
    context: LaunchExecutionContext,
    specs: list[Any],
) -> str:
    stable = {
        "launch_kind": plan.launch_kind,
        "context": {
            "cl_name": context.cl_name,
            "project_file": context.project_file,
            "project_name": context.project_name,
            "update_target": context.update_target,
            "history_sort_key": context.history_sort_key,
            "is_home_mode": context.is_home_mode,
            "vcs_ref": context.vcs_ref,
            "deferred_workspace": context.deferred_workspace,
        },
        "slots": [spec.to_wire() for spec in specs],
    }
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"scheduler.launch:{hashlib.sha256(encoded).hexdigest()}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _scheduler_slot_env(
    slot: LaunchFanoutSlotWire,
    extra_env: dict[str, str] | None,
    slot_extra_env: SlotEnvCallback | None,
) -> dict[str, str]:
    env = dict(extra_env or {})
    if slot_extra_env is not None:
        env.update(slot_extra_env(slot))
    return env


def _unsupported_scheduler_slot_reason(
    context: LaunchExecutionContext,
    *,
    slot_env: dict[str, str],
    local_xprompts_file: str | None,
) -> str | None:
    if slot_env:
        return "extra_env"
    if local_xprompts_file is not None:
        return "local_xprompts"
    if context.deferred_workspace and not context.is_home_mode:
        return "deferred_workspace"
    return None


def _scheduler_project_id(context: LaunchExecutionContext) -> str:
    return context.project_name or context.project_file or "home"


def _scheduler_launch_cwd(context: LaunchExecutionContext) -> str:
    if context.workspace_dir:
        return context.workspace_dir
    if context.is_home_mode:
        return os.path.expanduser("~")
    return os.getcwd()


def _scheduler_execution_result(
    plan: LaunchFanoutPlanWire,
    context: LaunchExecutionContext,
    *,
    timestamp_by_slot: dict[int, str],
    response: dict[str, Any],
    on_slot_executed: SlotExecutedCallback | None,
) -> _LaunchExecutionResult:
    handle = response.get("handle")
    handle_dict = handle if isinstance(handle, dict) else {}
    batch_id = _optional_str(handle_dict.get("batch_id")) or ""
    queue_id = _optional_str(handle_dict.get("queue_id")) or "agents"
    status = _optional_str(handle_dict.get("status")) or "queued"
    slot_status = response.get("status")
    raw_slots = slot_status.get("slots") if isinstance(slot_status, dict) else None
    slots_by_index = _scheduler_slots_by_index(raw_slots)

    records: list[_LaunchExecutionRecord] = []
    for slot in plan.slots:
        timestamp = timestamp_by_slot[slot.slot_index]
        workflow_name = slot.workflow_name or f"ace(run)-{timestamp}"
        request = LaunchSpawnRequest(
            cl_name=context.cl_name,
            project_file=context.project_file,
            workspace_dir=_scheduler_launch_cwd(context),
            workspace_num=context.workspace_num or 0,
            workflow_name=workflow_name,
            prompt=slot.prompt,
            timestamp=timestamp,
            update_target=context.update_target,
            project_name=context.project_name,
            history_sort_key=context.history_sort_key,
            is_home_mode=context.is_home_mode,
            vcs_ref=context.vcs_ref,
            deferred_workspace=context.deferred_workspace,
        )
        raw_slot = slots_by_index.get(slot.slot_index, {})
        result = AgentLaunchResult(
            pid=0,
            workspace_num=request.workspace_num,
            workspace_dir=request.workspace_dir,
            output_path="",
            project_file=request.project_file,
            project_name=request.project_name,
            workflow_name=request.workflow_name,
            cl_name=request.cl_name,
            timestamp=request.timestamp,
            scheduler_batch_id=batch_id,
            scheduler_queue_id=queue_id,
            scheduler_slot_id=(
                _optional_str(raw_slot.get("slot_id")) or str(slot.slot_index)
            ),
            scheduler_status=_optional_str(raw_slot.get("status")) or status,
            scheduler_handle=handle_dict or None,
        )
        record = _LaunchExecutionRecord(slot=slot, request=request, result=result)
        records.append(record)
        if on_slot_executed is not None:
            on_slot_executed(record)

    return _LaunchExecutionResult(records=records)


def _scheduler_slots_by_index(raw_slots: object) -> dict[int, dict[str, Any]]:
    if not isinstance(raw_slots, list):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for fallback_index, item in enumerate(raw_slots):
        if not isinstance(item, dict):
            continue
        raw_index = item.get("slot_index")
        try:
            index = fallback_index if raw_index is None else int(raw_index)
        except (TypeError, ValueError):
            index = fallback_index
        out[index] = item
    return out


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _spawn_slot_with_workspace_retry(
    *,
    slot: LaunchFanoutSlotWire,
    context: LaunchExecutionContext,
    workflow_name: str,
    timestamp: str,
    extra_env: dict[str, str] | None,
    local_xprompts_file: str | None,
    spawn: SpawnCallback,
) -> tuple[LaunchSpawnRequest, AgentLaunchResult | None]:
    from sase.running_field import release_workspace

    max_attempts = workspace_allocation_attempt_limit()
    last_error: BaseException | None = None
    use_preclaim = _should_preclaim_workspace(context)

    for attempt in range(1, max_attempts + 1):
        preclaim: _WorkspacePreClaim | None = None
        try:
            if use_preclaim:
                preclaim = _preclaim_axe_workspace(context, workflow_name)
                workspace_num = preclaim.workspace_num
                workspace_dir = preclaim.workspace_dir
                transfer_from_pid: int | None = preclaim.parent_pid
            else:
                workspace_num, workspace_dir = _resolve_slot_workspace(context)
                transfer_from_pid = None

            request = LaunchSpawnRequest(
                cl_name=context.cl_name,
                project_file=context.project_file,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                workflow_name=workflow_name,
                prompt=slot.prompt,
                timestamp=timestamp,
                update_target=context.update_target,
                project_name=context.project_name,
                history_sort_key=context.history_sort_key,
                is_home_mode=context.is_home_mode,
                vcs_ref=context.vcs_ref,
                deferred_workspace=context.deferred_workspace,
                local_xprompts_file=local_xprompts_file,
                extra_env=extra_env,
                transfer_from_pid=transfer_from_pid,
            )
            result = spawn(request)
            # Successful spawn — the spawn callback transferred the pre-claim
            # to the child PID, so the parent no longer owns the slot.
            preclaim = None
            return request, result
        except WorkspaceClaimError as exc:
            last_error = exc
        finally:
            if preclaim is not None:
                # Spawn raised before/during the claim_callback, so the
                # pre-claim is still owned by the parent PID — release it
                # before retrying so we don't leak the workspace slot.
                release_workspace(
                    preclaim.project_file,
                    preclaim.workspace_num,
                    preclaim.workflow_name,
                    context.cl_name or None,
                )

        if attempt < max_attempts:
            time.sleep(_workspace_retry_backoff_seconds(attempt))

    raise WorkspaceClaimError(
        "Failed to claim an available workspace for "
        f"{_workspace_target_label(context)} after {max_attempts} attempts: "
        f"{last_error if last_error is not None else 'unknown reason'}"
    ) from last_error


def workspace_allocation_attempt_limit() -> int:
    """Return total workspace allocation attempts for launch retry loops."""
    try:
        max_retries = int(os.environ.get(_WORKSPACE_ALLOCATION_MAX_RETRIES_ENV, ""))
    except ValueError:
        max_retries = _DEFAULT_WORKSPACE_ALLOCATION_MAX_RETRIES
    if max_retries < 0:
        max_retries = 0
    return 1 + max_retries


def _workspace_retry_backoff_seconds(attempt: int) -> float:
    """Jittered backoff between workspace claim retries.

    Two same-tick contenders without jitter would keep retrying in lockstep
    and keep losing to each other.  Per-attempt jitter breaks the symmetry
    so they desynchronize after the first collision.
    """
    return min(1.0, random.uniform(0.05, 0.25) * attempt)


def _should_preclaim_workspace(context: LaunchExecutionContext) -> bool:
    """Return True iff the regular axe-workspace path should pre-claim.

    Pre-claim eliminates the TOCTOU race window between picking a free
    workspace number and the spawned child claiming it (see
    ``_claim_spawned_child``).  Pre-allocated, home-mode, and
    deferred-workspace paths each have their own workspace_num resolution
    and shouldn't be pre-claimed.
    """
    return not (
        context.use_preallocated_workspace
        or context.is_home_mode
        or context.deferred_workspace
    )


@dataclass(frozen=True)
class _WorkspacePreClaim:
    """Workspace slot already claimed by the parent PID.

    The spawn callback transfers this claim to the child PID atomically; on
    spawn failure the caller releases it via ``release_workspace`` so the
    slot doesn't leak across retries.
    """

    project_file: str
    workspace_num: int
    workspace_dir: str
    workflow_name: str
    parent_pid: int


def _preclaim_axe_workspace(
    context: LaunchExecutionContext, workflow_name: str
) -> _WorkspacePreClaim:
    from sase.running_field import (
        claim_next_axe_workspace,
        get_workspace_directory_for_num,
    )

    parent_pid = os.getpid()
    workspace_num = claim_next_axe_workspace(
        context.project_file,
        workflow_name,
        parent_pid,
        cl_name=context.cl_name or None,
    )
    workspace_dir, _ = get_workspace_directory_for_num(
        workspace_num, context.project_name
    )
    return _WorkspacePreClaim(
        project_file=context.project_file,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow_name=workflow_name,
        parent_pid=parent_pid,
    )


def _workspace_target_label(context: LaunchExecutionContext) -> str:
    project = context.project_name or context.project_file
    if context.cl_name and context.cl_name != project:
        return f"{project}/{context.cl_name}"
    return project


def _resolve_slot_workspace(context: LaunchExecutionContext) -> tuple[int, str]:
    from sase.running_field import (
        get_workspace_directory,
    )

    if context.use_preallocated_workspace:
        assert context.workspace_num is not None
        assert context.workspace_dir is not None
        return context.workspace_num, context.workspace_dir
    if context.is_home_mode:
        return (
            0 if context.workspace_num is None else context.workspace_num,
            context.workspace_dir or os.path.expanduser("~"),
        )
    if context.deferred_workspace:
        return 0, get_workspace_directory(context.project_name, 1)

    # Regular axe path is now handled by ``_preclaim_axe_workspace``.
    raise AssertionError(
        "regular axe-workspace path must go through _preclaim_axe_workspace"
    )


__all__ = [
    "LaunchExecutionContext",
    "LaunchSpawnRequest",
    "execute_launch_plan",
    "workspace_allocation_attempt_limit",
]
