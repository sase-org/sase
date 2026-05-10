"""Shared execution core for Rust-backed agent launch fan-out plans."""

from __future__ import annotations

import os
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.core.agent_launch_wire import LaunchFanoutPlanWire, LaunchFanoutSlotWire
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
