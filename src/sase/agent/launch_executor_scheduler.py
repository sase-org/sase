"""Daemon scheduler execution path for agent launch fan-out plans."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from sase.agent.launch_executor_types import (
    LaunchExecutionContext,
    LaunchExecutionRecord,
    LaunchExecutionResult,
    LaunchSpawnRequest,
    SlotContextCallback,
    SlotEnvCallback,
    SlotExecutedCallback,
    SlotLocalXpromptsCallback,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import LaunchFanoutPlanWire, LaunchFanoutSlotWire
from sase.daemon.errors import LocalDaemonError


def try_scheduler_launch_plan(
    plan: LaunchFanoutPlanWire,
    context: LaunchExecutionContext,
    *,
    timestamp_by_slot: dict[int, str],
    slot_context: SlotContextCallback | None,
    slot_extra_env: SlotEnvCallback | None,
    slot_local_xprompts_file: SlotLocalXpromptsCallback | None,
    extra_env: dict[str, str] | None,
    on_slot_executed: SlotExecutedCallback | None,
) -> LaunchExecutionResult | None:
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
) -> LaunchExecutionResult:
    handle = response.get("handle")
    handle_dict = handle if isinstance(handle, dict) else {}
    batch_id = _optional_str(handle_dict.get("batch_id")) or ""
    queue_id = _optional_str(handle_dict.get("queue_id")) or "agents"
    status = _optional_str(handle_dict.get("status")) or "queued"
    slot_status = response.get("status")
    raw_slots = slot_status.get("slots") if isinstance(slot_status, dict) else None
    slots_by_index = _scheduler_slots_by_index(raw_slots)

    records: list[LaunchExecutionRecord] = []
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
        record = LaunchExecutionRecord(slot=slot, request=request, result=result)
        records.append(record)
        if on_slot_executed is not None:
            on_slot_executed(record)

    return LaunchExecutionResult(records=records)


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


__all__ = ["try_scheduler_launch_plan"]
