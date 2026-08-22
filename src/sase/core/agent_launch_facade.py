"""Python facade helpers for Rust-backed agent launch operations."""

from __future__ import annotations

from collections.abc import Callable
import fcntl
from pathlib import Path
from typing import Any

from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentLaunchPreparedWire,
    AgentLaunchRequestWire,
    AgentUnitWire,
    LaunchAdmissionSummaryWire,
    LaunchFanoutPlanWire,
    LaunchFanoutSlotWire,
    LaunchPlanWire,
    LaunchUnitResultWire,
    LaunchUnitWire,
    agent_launch_prepared_from_dict,
    agent_launch_wire_to_json_dict,
    launch_admission_summary_from_dict,
    launch_fanout_plan_from_dict,
    launch_plan_from_dict,
    launch_unit_result_from_dict,
)
from sase.core.rust import require_rust_binding


def safe_launch_name(cl_name: str) -> str:
    """Return the sanitized name currently used in launch output paths."""

    return "".join(c if c.isalnum() or c in "-_" else "_" for c in cl_name)


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


def spawn_prepared_agent_process(
    prepared: AgentLaunchPreparedWire,
    *,
    env: dict[str, str],
    claim_callback: Callable[[int], bool] | None = None,
) -> int:
    """Spawn a Rust-backed detached process from prepared launch data."""

    binding = require_rust_binding("spawn_prepared_agent_process")
    return int(
        binding(
            agent_launch_wire_to_json_dict(prepared),
            {str(key): str(value) for key, value in env.items()},
            claim_callback,
        )
    )


def _allocate_launch_timestamp_batch(
    count: int,
    *,
    base_timestamp: str | None = None,
    after_timestamp: str | None = None,
) -> list[str]:
    """Return unique launch timestamps preserving ``YYmmdd_HHMMSS`` format."""

    if count <= 0:
        return []
    if base_timestamp is None:
        from sase.core.time import generate_timestamp

        base_timestamp = generate_timestamp()

    binding = require_rust_binding("allocate_launch_timestamp_batch")
    return [
        str(timestamp) for timestamp in binding(count, base_timestamp, after_timestamp)
    ]


def _latest_timestamp(*timestamps: str | None) -> str | None:
    values = [timestamp for timestamp in timestamps if timestamp]
    return max(values) if values else None


def reserve_launch_timestamp_batch(
    count: int,
    *,
    base_timestamp: str | None = None,
    after_timestamp: str | None = None,
) -> list[str]:
    """Reserve globally unique launch timestamps across concurrent processes."""

    if count <= 0:
        return []
    if base_timestamp is None:
        from sase.core.time import generate_timestamp

        base_timestamp = generate_timestamp()

    from sase.core.paths import ensure_sase_directory

    reservation_dir = Path(ensure_sase_directory("agent_launch_timestamps"))
    lock_path = reservation_dir / "lock"
    state_path = reservation_dir / "last_reserved_timestamp"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            persisted_timestamp = (
                state_path.read_text(encoding="utf-8").strip()
                if state_path.exists()
                else None
            )
            reserved_after = _latest_timestamp(after_timestamp, persisted_timestamp)
            timestamps = _allocate_launch_timestamp_batch(
                count,
                base_timestamp=base_timestamp,
                after_timestamp=reserved_after,
            )
            state_path.write_text(f"{timestamps[-1]}\n", encoding="utf-8")
            return timestamps
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def plan_agent_launch_fanout(
    prompt: str,
    *,
    launch_kind: str | None = None,
) -> LaunchFanoutPlanWire:
    """Return the Rust-backed deterministic launch fan-out plan for *prompt*."""

    binding = require_rust_binding("plan_agent_launch_fanout")
    payload = binding(prompt, launch_kind)
    return launch_fanout_plan_from_dict(dict(payload))


def plan_typed_launch_units(
    prompt: str,
    *,
    launch_kind: str | None = None,
    selected_project: str | None = None,
) -> LaunchPlanWire:
    """Return a pure typed Agent/Proc launch graph for *prompt*."""

    from sase.xprompt.code_value import reject_disabled_code_directives

    reject_disabled_code_directives(prompt)
    binding = require_rust_binding("plan_typed_launch_units")
    payload = binding(prompt, launch_kind, selected_project)
    return launch_plan_from_dict(dict(payload))


def reconcile_admission_journal(
    entries: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Replay journal entries into the latest per-unit admission state."""

    binding = require_rust_binding("reconcile_admission_journal")
    payload = binding(entries)
    return {str(key): dict(value) for key, value in dict(payload).items()}


def next_admission_actions(
    plan: LaunchPlanWire,
    states: dict[str, dict[str, Any]],
    wait_facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the next durable admission actions for *plan*."""

    binding = require_rust_binding("next_admission_actions")
    payload = binding(agent_launch_wire_to_json_dict(plan), states, wait_facts)
    return [dict(item) for item in payload]


def summarize_admission(
    plan: LaunchPlanWire,
    states: dict[str, dict[str, Any]],
) -> LaunchAdmissionSummaryWire:
    """Count terminal admission outcomes without collapsing error classes."""

    binding = require_rust_binding("summarize_admission")
    payload = binding(agent_launch_wire_to_json_dict(plan), states)
    return launch_admission_summary_from_dict(dict(payload))


def admission_unit_results(
    plan: LaunchPlanWire,
    states: dict[str, dict[str, Any]],
) -> list[LaunchUnitResultWire]:
    """Return terminal per-unit results currently recorded in *states*."""

    binding = require_rust_binding("admission_unit_results")
    payload = binding(agent_launch_wire_to_json_dict(plan), states)
    return [launch_unit_result_from_dict(dict(item)) for item in payload]


def agent_unit_dispatch_prompt(agent: AgentUnitWire) -> str:
    """Rebuild an agent launch prompt from a typed unit without waits or %if."""

    binding = require_rust_binding("agent_unit_dispatch_prompt")
    return str(binding(agent_launch_wire_to_json_dict(agent)))


def classify_condition_status(
    *,
    exit_code: int | None = None,
    signal: int | None = None,
    timed_out: bool = False,
    exec_error: bool = False,
    cancelled: bool = False,
) -> str:
    """Return ``eligible`` / ``skipped`` / ``condition_error`` for a predicate."""

    binding = require_rust_binding("classify_condition_status")
    return str(
        binding(
            exit_code,
            signal,
            timed_out,
            exec_error,
            cancelled,
        )
    )


def sanitize_condition_inputs(value: Any) -> dict[str, Any]:
    """Drop secret-like keys and non-scalar values from condition inputs."""

    binding = require_rust_binding("sanitize_condition_inputs")
    payload = binding(value)
    return dict(payload) if isinstance(payload, dict) else {}


def build_condition_context(
    unit: LaunchUnitWire,
    waited: list[dict[str, Any]],
    *,
    selected_project: str | None = None,
    safe_inputs: dict[str, Any] | None = None,
    share_workspace: bool = False,
) -> dict[str, Any]:
    """Build the versioned ``SASE_CONDITION_CONTEXT`` payload."""

    binding = require_rust_binding("build_condition_context")
    payload = binding(
        agent_launch_wire_to_json_dict(unit),
        waited,
        selected_project,
        safe_inputs or {},
        share_workspace,
    )
    return dict(payload)


def evaluate_launch_condition(request: dict[str, Any]) -> dict[str, Any]:
    """Run the sandboxed `%if` evaluator and return its durable result."""

    binding = require_rust_binding("evaluate_launch_condition")
    payload = binding(request)
    return dict(payload)


def xprompt_proc_origin() -> str:
    """Return the native stand-alone `%proc` origin string."""

    return str(require_rust_binding("xprompt_proc_origin")())


def proc_dispatch_wire_schema_version() -> int:
    """Return the `%proc` dispatch request schema version."""

    return int(require_rust_binding("proc_dispatch_wire_schema_version")())


def parse_proc_duration_seconds(raw: str) -> int:
    """Parse a SASE duration such as ``20m`` into seconds."""

    return int(require_rust_binding("parse_proc_duration_seconds")(raw))


def validate_standalone_proc_shell_name(name: str | None) -> None:
    """Reject family-qualified or malformed stand-alone proc names."""

    require_rust_binding("validate_standalone_proc_shell_name")(name)


def validate_proc_workspace_intent(
    workspace: bool,
    selected_project: str | None,
    declared_cwd: str | None,
) -> None:
    """Reject workspace/cwd combinations that cannot launch."""

    require_rust_binding("validate_proc_workspace_intent")(
        workspace, selected_project, declared_cwd
    )


def resolve_proc_execution_cwd(
    workspace: bool,
    *,
    declared_cwd: str | None = None,
    source_cwd: str | None = None,
    lease_root: str | None = None,
) -> str:
    """Resolve and contain a `%proc` execution cwd."""

    return str(
        require_rust_binding("resolve_proc_execution_cwd")(
            workspace, declared_cwd, source_cwd, lease_root
        )
    )


def proc_script_argv(language: str, work_dir: str, python_executable: str) -> list[str]:
    """Return the interpreter argv for a `%proc` script in *work_dir*."""

    return [
        str(part)
        for part in require_rust_binding("proc_script_argv")(
            language, work_dir, python_executable
        )
    ]


def prepare_proc_script(request: dict[str, Any]) -> dict[str, Any]:
    """Materialize a private `%proc` script and return argv/cwd/env."""

    payload = require_rust_binding("prepare_proc_script")(request)
    return dict(payload)


def sanitized_proc_env(
    proc_id: str,
    cwd: str,
    work_dir: str,
    python_executable: str,
    *,
    selected_project: str | None = None,
    project_file: str | None = None,
    workspace_num: int | None = None,
) -> dict[str, str]:
    """Return the documented sanitized `%proc` child environment."""

    payload = require_rust_binding("sanitized_proc_env")(
        proc_id,
        cwd,
        work_dir,
        python_executable,
        selected_project,
        project_file,
        workspace_num,
    )
    return {str(key): str(value) for key, value in dict(payload).items()}


def cleanup_proc_private_inputs(work_dir: str) -> None:
    """Remove private `%proc` scripts after settlement."""

    require_rust_binding("cleanup_proc_private_inputs")(work_dir)


class LaunchTimestampBatchAllocator:
    """Allocate monotonically unique launch timestamps for one fan-out."""

    def __init__(self) -> None:
        self._last_timestamp: str | None = None

    def allocate(self, count: int) -> list[str]:
        timestamps = reserve_launch_timestamp_batch(
            count,
            after_timestamp=self._last_timestamp,
        )
        if timestamps:
            self._last_timestamp = timestamps[-1]
        return timestamps

    def next(self) -> str:
        return self.allocate(1)[0]


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


__all__ = [
    "LaunchTimestampBatchAllocator",
    "_allocate_launch_timestamp_batch",
    "admission_unit_results",
    "agent_unit_dispatch_prompt",
    "build_condition_context",
    "classify_condition_status",
    "cleanup_proc_private_inputs",
    "evaluate_launch_condition",
    "next_admission_actions",
    "parse_proc_duration_seconds",
    "plan_fake_fanout",
    "plan_agent_launch_fanout",
    "plan_typed_launch_units",
    "prepare_agent_launch",
    "prepare_proc_script",
    "proc_dispatch_wire_schema_version",
    "proc_script_argv",
    "reconcile_admission_journal",
    "reserve_launch_timestamp_batch",
    "resolve_proc_execution_cwd",
    "safe_launch_name",
    "sanitize_condition_inputs",
    "sanitized_proc_env",
    "spawn_prepared_agent_process",
    "summarize_admission",
    "validate_proc_workspace_intent",
    "validate_standalone_proc_shell_name",
    "xprompt_proc_origin",
]
