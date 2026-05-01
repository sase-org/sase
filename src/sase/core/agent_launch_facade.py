"""Python-only helpers for the Phase 1 agent-launch wire contract."""

from __future__ import annotations

import os
from pathlib import Path

from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentLaunchPreparedWire,
    AgentLaunchRequestWire,
    LaunchFanoutPlanWire,
    LaunchFanoutSlotWire,
    WorkspaceClaimRequestWire,
    agent_launch_prepared_from_dict,
    agent_launch_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding


def safe_launch_name(cl_name: str) -> str:
    """Return the sanitized name currently used in launch output paths."""

    return "".join(c if c.isalnum() or c in "-_" else "_" for c in cl_name)


def prepare_agent_launch_python(
    request: AgentLaunchRequestWire,
    *,
    python_executable: str,
    runner_script: str,
    prompt_file: str,
    output_path: str,
) -> AgentLaunchPreparedWire:
    """Build the prepared wire record for one low-level launch.

    This mirrors the deterministic shape of ``spawn_agent_subprocess`` without
    writing files or spawning a child. It is intentionally Python-only in Phase
    1 so tests and benchmarks can pin the contract before Rust owns it.
    """

    argv = [
        python_executable,
        runner_script,
        request.cl_name,
        request.project_file,
        request.workspace_dir,
        output_path,
        str(request.workspace_num),
        request.workflow_name,
        prompt_file,
        request.timestamp,
        request.update_target,
        request.project_name,
        request.history_sort_key,
        "1" if request.is_home_mode else "",
    ]

    env_delta = dict(request.extra_env)
    env_delta["SASE_AGENT"] = "1"
    env_delta["SASE_AGENT_CL_NAME"] = request.cl_name
    env_delta["SASE_AGENT_PROJECT_FILE"] = request.project_file
    env_delta["SASE_AGENT_TIMESTAMP"] = request.timestamp
    if request.deferred_workspace:
        env_delta["SASE_AGENT_DEFERRED_WORKSPACE"] = "1"
        if request.vcs_workflow_type is not None:
            env_delta["SASE_AGENT_VCS_WORKFLOW_TYPE"] = request.vcs_workflow_type
    if request.local_xprompts_file:
        env_delta["SASE_AGENT_LOCAL_XPROMPTS"] = request.local_xprompts_file

    claim_request: WorkspaceClaimRequestWire | None = None
    if not request.is_home_mode:
        claim_request = WorkspaceClaimRequestWire(
            project_file=request.project_file,
            workspace_num=0 if request.deferred_workspace else request.workspace_num,
            workflow_name=request.workflow_name,
            pid=0,
            cl_name=request.cl_name,
            transfer_from_pid=request.retry_transfer_from_pid,
        )

    return AgentLaunchPreparedWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        prompt_file=prompt_file,
        output_path=output_path,
        safe_name=safe_launch_name(request.cl_name),
        argv=argv,
        cwd=request.workspace_dir,
        env_delta=env_delta,
        claim_request=claim_request,
    )


def prepare_agent_launch(
    request: AgentLaunchRequestWire,
    *,
    python_executable: str,
    runner_script: str,
    sase_tmpdir: str | None,
    output_root: str,
    preallocated_env: dict[str, str] | None = None,
) -> AgentLaunchPreparedWire:
    """Write prompt bytes and return Rust-prepared launch process data."""

    binding = require_rust_binding("prepare_agent_launch")
    payload = binding(
        agent_launch_wire_to_json_dict(request),
        python_executable,
        runner_script,
        output_root,
        sase_tmpdir,
        preallocated_env or {},
    )
    return agent_launch_prepared_from_dict(dict(payload))


def plan_fake_fanout(
    launch_kind: str,
    prompts: list[str],
    *,
    fanout_sleep_seconds: float = 0.0,
    requires_sequential_naming_wait: bool = False,
) -> LaunchFanoutPlanWire:
    """Return a simple fan-out wire plan for benchmark fixtures."""

    return LaunchFanoutPlanWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        launch_kind=launch_kind,
        slots=[
            LaunchFanoutSlotWire(
                prompt=prompt,
                launch_kind=launch_kind,
                slot_index=i,
            )
            for i, prompt in enumerate(prompts)
        ],
        fanout_sleep_seconds=fanout_sleep_seconds,
        requires_sequential_naming_wait=requires_sequential_naming_wait,
    )


def fake_output_path(root: Path, cl_name: str, timestamp: str) -> str:
    """Return the launch output path shape without touching global state."""

    return str(root / f"{safe_launch_name(cl_name)}_ace-run-{timestamp}.txt")


def fake_prompt_path(root: Path, timestamp: str) -> str:
    """Return a deterministic fake prompt file path for tests/benchmarks."""

    return os.fspath(root / f"sase_ace_prompt_{timestamp}.md")


__all__ = [
    "fake_output_path",
    "fake_prompt_path",
    "plan_fake_fanout",
    "prepare_agent_launch",
    "prepare_agent_launch_python",
    "safe_launch_name",
]
