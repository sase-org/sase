"""Agent-chop execution for the shared chop runner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sase.core.time import get_timezone

from .chop_agents import (
    build_chop_launch_env,
    get_live_chop_agent_records,
    prompt_hash,
    record_chop_agent_launch_result,
)
from .config import ChopConfig
from .state import (
    ChopRunEntry,
    ChopRunSource,
    generate_chop_run_id,
    write_chop_run,
)
from .chop_runner_trace import capture_traceback, compact_preview
from .chop_runner_types import ChopRunOutcome


def agent_launch_output(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    result: object,
    extra_env: dict[str, str],
    source: ChopRunSource,
    started_by: str | None,
) -> str:
    """Build the persisted log for a successful agent-chop launch."""
    pid = getattr(result, "pid", "")
    workspace_num = getattr(result, "workspace_num", "")
    workspace_dir = getattr(result, "workspace_dir", "")
    output_path = getattr(result, "output_path", "")
    project_name = getattr(result, "project_name", "")
    workflow_name = getattr(result, "workflow_name", "")
    cl_name = getattr(result, "cl_name", "")
    timestamp = getattr(result, "timestamp", "")
    prompt_hash_value = extra_env.get("SASE_CHOP_PROMPT_HASH", "-")
    prompt_preview = compact_preview(chop.agent or "")

    lines = [
        f"Launched agent chop '{chop.name}' (PID {pid})",
        (
            f"chop={chop.name} lumberjack={lumberjack_name} source={source} "
            f"started_by={started_by or '-'} prompt_hash={prompt_hash_value}"
        ),
        (
            f"agent_pid={pid} workspace={workspace_num or '-'} "
            f"workspace_dir={workspace_dir or '-'} output={output_path or '-'}"
        ),
    ]
    if project_name or workflow_name or cl_name or timestamp:
        lines.append(
            f"project={project_name or '-'} workflow={workflow_name or '-'} "
            f"cl={cl_name or '-'} timestamp={timestamp or '-'}"
        )
    if prompt_preview:
        lines.append(f"prompt_preview={prompt_preview!r}")
    return "\n".join(lines) + "\n"


def run_agent_chop_once(
    *,
    lumberjack_name: str,
    chop: ChopConfig,
    source: ChopRunSource,
    started_by: str | None,
    launch_agent_from_cwd_fn: Callable[..., Any] | None = None,
    record_chop_agent_launch_result_fn: Callable[
        ..., Any
    ] = record_chop_agent_launch_result,
) -> ChopRunOutcome:
    assert chop.agent is not None
    started_at = datetime.now(get_timezone())
    run_id = generate_chop_run_id(started_at)

    prompt_hash_value = prompt_hash(chop.agent)
    live = get_live_chop_agent_records(
        lumberjack_name,
        chop_name=chop.name,
        prompt_hash_value=prompt_hash_value,
    )
    if live:
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="already_running",
            agent_pid=next(iter(record.pid for record in live), None),
        )

    extra_env = build_chop_launch_env(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        prompt=chop.agent,
    )
    try:
        if launch_agent_from_cwd_fn is None:
            from sase.agent.launcher import launch_agent_from_cwd

            launch_agent_from_cwd_fn = launch_agent_from_cwd
        result = launch_agent_from_cwd_fn(chop.agent, extra_env=extra_env)
    except Exception as e:
        tb = capture_traceback()
        finished_at = datetime.now(get_timezone())
        duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
        try:
            write_chop_run(
                ChopRunEntry(
                    run_id=run_id,
                    lumberjack_name=lumberjack_name,
                    chop_name=chop.name,
                    started_at=started_at.isoformat(),
                    finished_at=finished_at.isoformat(),
                    duration_ms=duration_ms,
                    status="failure",
                    error=str(e),
                    traceback=tb,
                    source=source,
                    started_by=started_by,
                )
            )
        except OSError:
            pass
        return ChopRunOutcome(
            lumberjack_name=lumberjack_name,
            chop_name=chop.name,
            status="agent_failed",
            run_id=run_id,
            error=e,
            traceback=tb,
        )

    record_chop_agent_launch_result_fn(result=result, prompt=chop.agent, env=extra_env)

    finished_at = datetime.now(get_timezone())
    duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    launch_output = agent_launch_output(
        lumberjack_name=lumberjack_name,
        chop=chop,
        result=result,
        extra_env=extra_env,
        source=source,
        started_by=started_by,
    )
    try:
        write_chop_run(
            ChopRunEntry(
                run_id=run_id,
                lumberjack_name=lumberjack_name,
                chop_name=chop.name,
                started_at=started_at.isoformat(),
                finished_at=finished_at.isoformat(),
                duration_ms=duration_ms,
                status="agent_launched",
                agent_pid=result.pid,
                source=source,
                started_by=started_by,
            ),
            output=launch_output,
        )
    except OSError:
        pass

    return ChopRunOutcome(
        lumberjack_name=lumberjack_name,
        chop_name=chop.name,
        status="agent_launched",
        run_id=run_id,
        agent_pid=result.pid,
    )


_run_agent_chop_once = run_agent_chop_once
