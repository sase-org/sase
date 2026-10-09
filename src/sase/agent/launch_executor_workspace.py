"""Workspace resolution and retry helpers for launch execution."""

from __future__ import annotations

import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass

from sase.agent.launch_executor_types import (
    LaunchExecutionContext,
    LaunchNameReservationEvidence,
    LaunchSpawnRequest,
    SpawnCallback,
)
from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import LaunchFanoutSlotWire
from sase.running_field import WorkspaceClaimError

_WORKSPACE_ALLOCATION_MAX_RETRIES_ENV = "SASE_AGENT_WORKSPACE_ALLOCATION_MAX_RETRIES"
_DEFAULT_WORKSPACE_ALLOCATION_MAX_RETRIES = 5

SASE_AGENT_PINNED_WORKSPACE_FALLBACK = "SASE_AGENT_PINNED_WORKSPACE_FALLBACK"
PINNED_WORKSPACE_FALLBACK_POOL = "pool"


def is_pinned_workspace_fallback_requested(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether pinned-workspace pool relocation was requested."""
    try:
        if env is None:
            fallback_value = os.environ.get(SASE_AGENT_PINNED_WORKSPACE_FALLBACK)
        elif isinstance(env, Mapping):
            fallback_value = env.get(SASE_AGENT_PINNED_WORKSPACE_FALLBACK)
        else:
            return False
    except Exception:
        return False
    return fallback_value == PINNED_WORKSPACE_FALLBACK_POOL


def spawn_slot_with_workspace_retry(
    *,
    slot: LaunchFanoutSlotWire,
    context: LaunchExecutionContext,
    workflow_name: str,
    timestamp: str,
    extra_env: dict[str, str] | None,
    local_macros_file: str | None,
    name_reservation: LaunchNameReservationEvidence | None = None,
    spawn: SpawnCallback,
) -> tuple[LaunchSpawnRequest, AgentLaunchResult | None]:
    from sase.running_field import release_workspace

    max_attempts = workspace_allocation_attempt_limit()
    last_error: BaseException | None = None
    use_preclaim = _should_preclaim_workspace(context)
    is_pinned = bool(context.use_preallocated_workspace)
    pinned_num = context.workspace_num if is_pinned else None
    fallback_requested = is_pinned_workspace_fallback_requested(extra_env)
    relocated = False
    relocation_occupant: str | None = None
    current_extra_env = dict(extra_env) if extra_env else None

    for attempt in range(1, max_attempts + 1):
        preclaim: _WorkspacePreClaim | None = None
        try:
            if use_preclaim or relocated:
                preclaim = _preclaim_axe_workspace(context, workflow_name)
                workspace_num = preclaim.workspace_num
                workspace_dir = preclaim.workspace_dir
                transfer_from_pid: int | None = preclaim.parent_pid
                request_env = current_extra_env
                if relocated:
                    request_env = _relocated_session_attach_env(
                        current_extra_env, workspace_dir, workspace_num
                    )
            else:
                workspace_num, workspace_dir = _resolve_slot_workspace(context)
                transfer_from_pid = None
                request_env = current_extra_env

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
                local_macros_file=local_macros_file,
                extra_env=request_env,
                transfer_from_pid=transfer_from_pid,
                name_reservation=name_reservation,
            )
            result = spawn(request)
            # Successful spawn: the callback transferred the pre-claim to
            # the child PID, so the parent no longer owns the slot.
            preclaim = None
            if relocated and result is not None:
                note = _relocation_note(pinned_num, relocation_occupant, workspace_num)
                try:
                    result.workspace_relocation = note
                except Exception:
                    from dataclasses import replace as _replace

                    result = _replace(result, workspace_relocation=note)
            return request, result
        except WorkspaceClaimError as exc:
            last_error = exc
            if (
                is_pinned
                and not relocated
                and fallback_requested
                and (exc.workspace_num is None or exc.workspace_num == pinned_num)
            ):
                relocation_occupant = _pinned_occupant_description(context)
                relocated = True
                # Do not sleep and do not retry the pin.
                continue
        finally:
            if preclaim is not None:
                # Spawn raised before/during the claim_callback, so the
                # pre-claim is still owned by the parent PID. Release it
                # before retrying so we don't leak the workspace slot.
                release_workspace(
                    preclaim.project_file,
                    preclaim.workspace_num,
                    preclaim.workflow_name,
                    context.cl_name or None,
                )

        if attempt < max_attempts:
            time.sleep(_workspace_retry_backoff_seconds(attempt))

    if is_pinned and not fallback_requested:
        occupant = _pinned_occupant_description(context)
        if occupant:
            raise WorkspaceClaimError(
                f"Pinned workspace #{pinned_num} is already claimed by {occupant}",
                workspace_num=pinned_num,
            ) from last_error
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
    """Return a jittered backoff between workspace claim retries."""
    return min(1.0, random.uniform(0.05, 0.25) * attempt)


def _should_preclaim_workspace(context: LaunchExecutionContext) -> bool:
    """Return True iff the regular axe-workspace path should pre-claim."""
    return not (
        context.use_preallocated_workspace
        or context.is_home_mode
        or context.deferred_workspace
    )


@dataclass(frozen=True)
class _WorkspacePreClaim:
    """Workspace slot already claimed by the parent PID."""

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
        release_workspace,
    )

    parent_pid = os.getpid()
    workspace_num = claim_next_axe_workspace(
        context.project_file,
        workflow_name,
        parent_pid,
        cl_name=context.cl_name or None,
        caller_tag="launcher-preclaim",
    )
    try:
        workspace_dir, _ = get_workspace_directory_for_num(
            workspace_num, context.project_name
        )
    except Exception:
        release_workspace(
            context.project_file,
            workspace_num,
            workflow_name,
            context.cl_name or None,
        )
        raise
    return _WorkspacePreClaim(
        project_file=context.project_file,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow_name=workflow_name,
        parent_pid=parent_pid,
    )


def _relocation_note(
    pinned_num: int | None, occupant: str | None, pool_num: int | None
) -> str:
    """Return the workspace relocation summary for a moved pinned launch."""
    if occupant:
        base = f"pinned workspace #{pinned_num} is claimed by {occupant}"
    else:
        base = f"pinned workspace #{pinned_num} is claimed"
    if pool_num is not None:
        return f"{base}; launched in #{pool_num}"
    return f"{base}; launched in pool workspace"


def _pinned_occupant_description(context: LaunchExecutionContext) -> str | None:
    """Describe the occupant holding the pinned workspace, if any."""
    if context.workspace_num is None:
        return None
    try:
        from sase.running_field import describe_workspace_occupant

        return describe_workspace_occupant(
            context.project_file,
            context.workspace_num,
            checkout_dir=context.workspace_dir,
        )
    except Exception:
        return None


def _relocated_session_attach_env(
    extra_env: dict[str, str] | None,
    workspace_dir: str,
    workspace_num: int,
) -> dict[str, str] | None:
    """Rewrite the session-attach payload to name the relocated workspace."""
    if not extra_env:
        return extra_env
    try:
        from sase.agent._agent_session_attach_launch import (
            load_agent_session_attach_plan_from_env,
        )
        from sase.agent.detached_child import agent_session_attach_env
    except Exception:
        return extra_env
    try:
        plan = load_agent_session_attach_plan_from_env(extra_env)
    except Exception:
        return extra_env
    if plan is None:
        return extra_env
    if plan.parent_workspace_dir is None and plan.parent_workspace_num is None:
        return extra_env
    try:
        from dataclasses import replace as _replace

        relocated_plan = _replace(
            plan,
            parent_workspace_dir=workspace_dir,
            parent_workspace_num=workspace_num,
        )
        rewritten = dict(extra_env)
        rewritten.update(agent_session_attach_env(relocated_plan))
        return rewritten
    except Exception:
        return extra_env


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
        return 0, context.workspace_dir or get_workspace_directory(
            context.project_name, 1
        )

    # Regular axe path is handled by ``_preclaim_axe_workspace``.
    raise AssertionError(
        "regular axe-workspace path must go through _preclaim_axe_workspace"
    )


__all__ = [
    "PINNED_WORKSPACE_FALLBACK_POOL",
    "SASE_AGENT_PINNED_WORKSPACE_FALLBACK",
    "is_pinned_workspace_fallback_requested",
    "spawn_slot_with_workspace_retry",
    "workspace_allocation_attempt_limit",
]
