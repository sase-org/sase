"""Python facade helpers for Rust-backed agent launch operations."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path

from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    AgentLaunchPreparedWire,
    AgentLaunchRequestWire,
    LaunchFanoutPlanWire,
    LaunchFanoutSlotWire,
    agent_launch_prepared_from_dict,
    agent_launch_wire_to_json_dict,
    launch_fanout_plan_from_dict,
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


def allocate_launch_timestamp_batch(
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


def plan_agent_launch_fanout(
    prompt: str,
    *,
    launch_kind: str | None = None,
) -> LaunchFanoutPlanWire:
    """Return the Rust-backed deterministic launch fan-out plan for *prompt*."""

    binding = require_rust_binding("plan_agent_launch_fanout")
    payload = binding(prompt, launch_kind)
    return launch_fanout_plan_from_dict(dict(payload))


class LaunchTimestampBatchAllocator:
    """Allocate monotonically unique launch timestamps for one fan-out."""

    def __init__(self) -> None:
        self._last_timestamp: str | None = None

    def allocate(self, count: int) -> list[str]:
        timestamps = allocate_launch_timestamp_batch(
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


def fake_output_path(root: Path, cl_name: str, timestamp: str) -> str:
    """Return the launch output path shape without touching global state."""

    return str(root / f"{safe_launch_name(cl_name)}_ace-run-{timestamp}.txt")


def fake_prompt_path(root: Path, timestamp: str) -> str:
    """Return a deterministic fake prompt file path for tests/benchmarks."""

    return os.fspath(root / f"sase_ace_prompt_{timestamp}.md")


__all__ = [
    "LaunchTimestampBatchAllocator",
    "allocate_launch_timestamp_batch",
    "fake_output_path",
    "fake_prompt_path",
    "plan_fake_fanout",
    "plan_agent_launch_fanout",
    "prepare_agent_launch",
    "safe_launch_name",
    "spawn_prepared_agent_process",
]
