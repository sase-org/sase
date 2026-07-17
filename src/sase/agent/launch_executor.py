"""Shared execution core for Rust-backed agent launch fan-out plans."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.agent.launch_executor_types import (
    LaunchExecutionContext,
    LaunchExecutionRecord,
    LaunchExecutionResult,
    LaunchSpawnRequest,
    SlotContextCallback,
    SlotEnvCallback,
    SlotExecutedCallback,
    SlotLocalXpromptsCallback,
    SpawnCallback,
)
from sase.agent.launch_executor_workspace import (
    spawn_slot_with_workspace_retry,
    workspace_allocation_attempt_limit,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_facade import LaunchTimestampBatchAllocator
from sase.core.agent_launch_wire import LaunchFanoutPlanWire

if TYPE_CHECKING:
    from sase.agent.family_attach import FamilyAttachSibling


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
    allow_reserved_family_separator_names: bool = False,
    allow_hyphenated_names: bool | None = None,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> LaunchExecutionResult:
    """Execute a normalized fan-out plan through a host-provided spawn hook."""
    if allow_hyphenated_names is not None:
        allow_reserved_family_separator_names = allow_hyphenated_names

    if not plan.slots:
        return LaunchExecutionResult(records=[])

    from sase.agent.names import ensure_historical_auto_name_migration

    ensure_historical_auto_name_migration()

    from sase.agent.launch_validation import validate_launch_name_requests

    validate_launch_name_requests(
        [slot.prompt for slot in plan.slots],
        allow_reserved_family_separator_names=allow_reserved_family_separator_names,
    )

    allocator = timestamp_allocator or LaunchTimestampBatchAllocator()
    missing_timestamp_count = sum(1 for slot in plan.slots if slot.timestamp is None)
    if base_timestamp is not None and missing_timestamp_count == 1:
        allocated = [base_timestamp]
    else:
        allocated = allocator.allocate(missing_timestamp_count)

    allocated_iter = iter(allocated)

    spawn_fn = spawn or _default_spawn
    records: list[LaunchExecutionRecord] = []
    pending_siblings: list[FamilyAttachSibling] = (
        [] if pending_family_parents is None else pending_family_parents
    )
    for slot in plan.slots:
        timestamp = slot.timestamp or next(allocated_iter)
        workflow_name = slot.workflow_name or f"ace(run)-{timestamp}"
        slot_ctx = slot_context(slot, context) if slot_context else context
        env = dict(extra_env or {})
        if slot_extra_env is not None:
            env.update(slot_extra_env(slot))
        from sase.agent.family_attach import (
            build_family_attach_sibling_from_spawn,
            load_family_attach_plan_from_env,
            prepare_family_attach_launch,
        )

        slot_ctx, prepared_env = prepare_family_attach_launch(
            slot.prompt,
            slot_ctx,
            env,
            pending_family_parents=pending_siblings,
        )
        env = dict(prepared_env or {})
        family_attach_plan = load_family_attach_plan_from_env(env)
        local_xprompts_file = (
            None if slot_local_xprompts_file is None else slot_local_xprompts_file(slot)
        )

        request, result = spawn_slot_with_workspace_retry(
            slot=slot,
            context=slot_ctx,
            workflow_name=workflow_name,
            timestamp=timestamp,
            extra_env=env or None,
            local_xprompts_file=local_xprompts_file,
            spawn=spawn_fn,
        )
        record = LaunchExecutionRecord(slot=slot, request=request, result=result)
        records.append(record)
        if family_attach_plan is not None:
            sibling = build_family_attach_sibling_from_spawn(
                request,
                family_attach_plan.agent_name,
                family_base=family_attach_plan.parent_base,
                can_attach_parent=True,
            )
            if sibling is not None:
                pending_siblings.append(sibling)
        else:
            explicit_name = _explicit_static_name_for_pending_family_parent(slot.prompt)
            if explicit_name is not None:
                sibling = build_family_attach_sibling_from_spawn(
                    request,
                    explicit_name,
                    can_attach_parent=True,
                )
                if sibling is not None:
                    pending_siblings.append(sibling)
        if on_slot_executed is not None:
            on_slot_executed(record)

    return LaunchExecutionResult(records=records)


def _explicit_static_name_for_pending_family_parent(prompt: str) -> str | None:
    from sase.agent.multi_prompt_references import extract_static_name_directive
    from sase.agent.names import is_agent_name_template

    explicit_name = extract_static_name_directive(prompt)
    if explicit_name is None or is_agent_name_template(explicit_name):
        return None
    return explicit_name


__all__ = [
    "LaunchExecutionContext",
    "LaunchExecutionRecord",
    "LaunchExecutionResult",
    "LaunchSpawnRequest",
    "execute_launch_plan",
    "workspace_allocation_attempt_limit",
]
