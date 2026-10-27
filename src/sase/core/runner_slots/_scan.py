"""Shared capacity-scan collector and liveness probe.

Admission and the machine-capacity report both walk the same capacity-only
artifact scan and probe PIDs the same way. Keeping the implementations here
lets core compute a display report without importing axe.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_projects_dir

from ._admission_types import RecordLiveness

RUNNER_SLOT_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    only_workflow_dirs=("ace-run",),
    include_done_markers=False,
    capacity_only=True,
)

ProcessAlive = Callable[[dict[str, object], Path], bool]


def collect_runner_slot_records() -> list[AgentArtifactRecordWire]:
    """Scan ace-run artifacts with admission's capacity-only options."""
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(sase_projects_dir(), RUNNER_SLOT_SCAN_OPTIONS).records


def record_liveness_probe(
    *,
    is_alive: ProcessAlive | None = None,
) -> RecordLiveness:
    """Return a memoized liveness probe matching admission's PID order.

    ``agent_meta.pid`` wins, then ``running.pid``. Process identity and
    ``stopped_at`` are forwarded when present. *is_alive* is the process
    check; the default is :func:`sase.agent.names.is_process_alive`.
    """
    from sase.agent.names import is_process_alive as default_is_alive

    probe = default_is_alive if is_alive is None else is_alive
    cache: dict[str, bool] = {}

    def is_live(record: AgentArtifactRecordWire) -> bool:
        if record.artifact_dir in cache:
            return cache[record.artifact_dir]
        meta = record.agent_meta
        pid = None if meta is None else meta.pid
        if pid is None and record.running is not None:
            pid = record.running.pid
        liveness: dict[str, object] = {}
        if pid is not None:
            liveness["pid"] = pid
        if meta is not None:
            if meta.stopped_at is not None:
                liveness["stopped_at"] = meta.stopped_at
            process_identity = getattr(meta, "process_identity", None)
            if process_identity is not None:
                liveness["process_identity"] = process_identity
        if (
            "process_identity" not in liveness
            and record.running is not None
            and getattr(record.running, "process_identity", None) is not None
        ):
            liveness["process_identity"] = record.running.process_identity
        alive = probe(liveness, Path(record.artifact_dir))
        cache[record.artifact_dir] = alive
        return alive

    return is_live


__all__ = [
    "RUNNER_SLOT_SCAN_OPTIONS",
    "collect_runner_slot_records",
    "record_liveness_probe",
]
