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
    "next_admission_actions",
    "plan_fake_fanout",
    "plan_agent_launch_fanout",
    "plan_typed_launch_units",
    "prepare_agent_launch",
    "reconcile_admission_journal",
    "reserve_launch_timestamp_batch",
    "safe_launch_name",
    "spawn_prepared_agent_process",
    "summarize_admission",
]
