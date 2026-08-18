"""Apply a planned ``sase agent restart``.

Execution is the mutating half: it snapshots a recovery bundle, stops the old
row, releases the reserved name, then relaunches the rewritten prompt from the
home directory so an untagged prompt cannot inherit the operator's current
workspace. Each step after the kill reports a status instead of raising, so a
partial restart still hands back a recovery command.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from sase.agent._restart_recovery import prepare_recovery
from sase.agent._restart_types import (
    AgentRestartOutcome,
    AgentRestartPlan,
    ProgressFn,
)
from sase.agent.running import KillResult


def execute_agent_restart(
    plan: AgentRestartPlan,
    *,
    progress: ProgressFn | None = None,
) -> AgentRestartOutcome:
    """Stop the old agent, wipe its name, and relaunch the rewritten prompt."""
    from sase.agent.force_reuse_launch import apply_force_reuse_launch
    from sase.agent.launch_cwd import launch_agents_from_cwd
    from sase.agent.running import dismiss_named_agent, kill_named_agent

    emit = progress or (lambda _step, _status, _detail: None)
    recovery_dir, recovery_command, recovery_prompt = prepare_recovery(plan, emit)

    if not plan.agent.is_done:
        stop = kill_named_agent(plan.name, exact_name=True)
        stop_action = "killed"
        killed = True
    else:
        stop = dismiss_named_agent(plan.name, exact_name=True)
        stop_action = "dismissed"
        killed = False
    if not stop.success:
        emit("stopped", "fail", stop.message)
        return AgentRestartOutcome(
            status="kill_failed",
            name=plan.name,
            stop_action=stop_action,
            stop_result=stop,
            error=stop.message,
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )
    emit("stopped", "ok", _stopped_detail(stop, plan, killed=killed))

    try:
        apply_force_reuse_launch(plan.force_reuse_plan)
    except Exception as exc:
        emit("name", "fail", str(exc))
        return AgentRestartOutcome(
            status="wipe_failed",
            name=plan.name,
            stop_action=stop_action,
            stop_result=stop,
            error=str(exc),
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )
    emit("name", "ok", f"released '{plan.presented_name}' for reuse")

    try:
        with contextlib.chdir(Path.home()):
            results = launch_agents_from_cwd(
                plan.rewritten_prompt,
                segment_extra_env=plan.force_reuse_plan.segment_envs,
            )
    except Exception as exc:
        emit("launched", "fail", str(exc))
        return _partial_outcome(
            plan,
            stop_action=stop_action,
            stop=stop,
            error=str(exc),
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )
    if not results:
        emit("launched", "fail", "agent launch produced no results")
        return _partial_outcome(
            plan,
            stop_action=stop_action,
            stop=stop,
            error="agent launch produced no results",
            recovery_command=recovery_command,
            recovery_dir=recovery_dir,
            recovery_prompt=recovery_prompt,
        )

    launched = results[0]
    emit("launched", "ok", _launched_detail(launched.pid, launched.workspace_num))
    renamed_to = _renamed_to(plan.name, getattr(launched, "agent_name", None))
    if renamed_to is not None:
        emit("name", "warn", f"launched as '{renamed_to}', not '{plan.name}'")
    return AgentRestartOutcome(
        status="ok",
        name=plan.name,
        stop_action=stop_action,
        stop_result=stop,
        launched_pid=launched.pid,
        launched_workspace_num=launched.workspace_num,
        launched_artifacts_dir=launched.artifacts_dir or None,
        recovery_command=recovery_command,
        recovery_dir=recovery_dir,
        recovery_prompt=recovery_prompt,
        renamed_to=renamed_to,
    )


def _partial_outcome(
    plan: AgentRestartPlan,
    *,
    stop_action: str,
    stop: KillResult,
    error: str,
    recovery_command: str | None,
    recovery_dir: str | None,
    recovery_prompt: str | None,
) -> AgentRestartOutcome:
    return AgentRestartOutcome(
        status="partial",
        name=plan.name,
        stop_action=stop_action,
        stop_result=stop,
        error=error,
        recovery_command=recovery_command,
        recovery_dir=recovery_dir,
        recovery_prompt=recovery_prompt,
    )


def _renamed_to(expected: str, launched_name: object) -> str | None:
    if not isinstance(launched_name, str) or not launched_name:
        return None
    return launched_name if launched_name != expected else None


def _stopped_detail(stop: KillResult, plan: AgentRestartPlan, *, killed: bool) -> str:
    bits: list[str] = []
    if killed and stop.pid is not None:
        bits.append(f"killed PID {stop.pid}")
    elif killed:
        bits.append(stop.message)
    else:
        bits.append("dismissed completed row")
    if plan.preview.workspace_num is not None:
        bits.append(f"workspace #{plan.preview.workspace_num} released")
    return " · ".join(bits)


def _launched_detail(pid: int, workspace_num: int) -> str:
    if workspace_num:
        return f"PID {pid} · workspace #{workspace_num}"
    return f"PID {pid}"
