"""Shared execution core for Rust-backed agent launch fan-out plans."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from sase.agent.launcher import AgentLaunchResult
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.core.agent_launch_wire import LaunchFanoutPlanWire, LaunchFanoutSlotWire


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
    max_attempts = workspace_allocation_attempt_limit()
    last_request: LaunchSpawnRequest | None = None
    last_error: RuntimeError | None = None

    for attempt in range(1, max_attempts + 1):
        workspace_num, workspace_dir = _resolve_slot_workspace(context)
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
        )
        last_request = request
        try:
            return request, spawn(request)
        except RuntimeError as exc:
            if not _should_retry_workspace_claim(context, exc):
                raise
            last_error = exc
            if attempt == max_attempts:
                break

    assert last_request is not None
    raise RuntimeError(
        "Failed to claim an available workspace for "
        f"{_workspace_target_label(context)} after {max_attempts} attempts; "
        "axe workspaces may all be claimed or racing with other launches."
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


def _should_retry_workspace_claim(
    context: LaunchExecutionContext, exc: RuntimeError
) -> bool:
    if (
        context.use_preallocated_workspace
        or context.is_home_mode
        or context.deferred_workspace
    ):
        return False
    return str(exc).startswith("Failed to claim workspace #")


def _workspace_target_label(context: LaunchExecutionContext) -> str:
    project = context.project_name or context.project_file
    if context.cl_name and context.cl_name != project:
        return f"{project}/{context.cl_name}"
    return project


def _resolve_slot_workspace(context: LaunchExecutionContext) -> tuple[int, str]:
    from sase.running_field import (
        get_first_available_axe_workspace,
        get_workspace_directory,
        get_workspace_directory_for_num,
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

    workspace_num = get_first_available_axe_workspace(context.project_file)
    workspace_dir, _ = get_workspace_directory_for_num(
        workspace_num, context.project_name
    )
    return workspace_num, workspace_dir


__all__ = [
    "LaunchExecutionContext",
    "LaunchSpawnRequest",
    "execute_launch_plan",
    "workspace_allocation_attempt_limit",
]
