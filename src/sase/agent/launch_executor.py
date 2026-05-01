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
        workspace_num, workspace_dir = _resolve_slot_workspace(slot_ctx)

        env = dict(extra_env or {})
        if slot_extra_env is not None:
            env.update(slot_extra_env(slot))
        local_xprompts_file = (
            None if slot_local_xprompts_file is None else slot_local_xprompts_file(slot)
        )

        request = LaunchSpawnRequest(
            cl_name=slot_ctx.cl_name,
            project_file=slot_ctx.project_file,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            workflow_name=workflow_name,
            prompt=slot.prompt,
            timestamp=timestamp,
            update_target=slot_ctx.update_target,
            project_name=slot_ctx.project_name,
            history_sort_key=slot_ctx.history_sort_key,
            is_home_mode=slot_ctx.is_home_mode,
            vcs_ref=slot_ctx.vcs_ref,
            deferred_workspace=slot_ctx.deferred_workspace,
            local_xprompts_file=local_xprompts_file,
            extra_env=env or None,
        )
        result = spawn_fn(request)
        record = _LaunchExecutionRecord(slot=slot, request=request, result=result)
        records.append(record)
        if on_slot_executed is not None:
            on_slot_executed(record)

    return _LaunchExecutionResult(records=records)


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
]
