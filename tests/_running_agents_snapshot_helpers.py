"""Shared helpers for snapshot-backed running-agent listing tests.

Not itself a test module (leading underscore keeps pytest from collecting
it). Process liveness still lives in Python, so the tests stub the
process-running probe, the Linux ``/proc/<pid>/cmdline`` PID-reuse guard,
and ``pid_is_thread`` rather than mocking the snapshot. Fixture PIDs such
as ``33333`` can collide with a live thread ID on a busy CI runner;
without the thread stub ``list_all_agents`` drops the retried child.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from sase.agent.running import RunningAgentInfo
from sase.core import process_identity
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)


def projects_root_for(home: Path) -> Path:
    return home / ".sase" / "projects"


def artifact_timestamp(info: RunningAgentInfo) -> str:
    """Return the artifact-dir basename for *info* (asserts non-None for typecheckers)."""
    assert info.artifacts_dir is not None
    return Path(info.artifacts_dir).name


def listing_projection(
    rows: list[RunningAgentInfo],
) -> list[tuple[str, str, str, str | None, bool | None]]:
    return [
        (
            artifact_timestamp(info),
            info.project,
            info.status,
            info.name,
            info.holds_runner_slot,
        )
        for info in rows
    ]


def _is_proc_cmdline(path: Path) -> bool:
    parts = path.parts
    return (
        len(parts) == 4
        and parts[0] == "/"
        and parts[1] == "proc"
        and parts[2].isdigit()
        and parts[3] == "cmdline"
    )


@contextmanager
def fixture_processes(home: Path, *, alive: bool) -> Iterator[None]:
    original_read_bytes = Path.read_bytes

    def is_process_running(_pid: int) -> bool:
        return alive

    def read_bytes(path: Path) -> bytes:
        if alive and _is_proc_cmdline(path):
            return b"python\x00-m\x00sase\x00"
        return original_read_bytes(path)

    with (
        patch("pathlib.Path.home", return_value=home),
        patch("sase.ace.hooks.processes.is_process_running", is_process_running),
        patch.object(process_identity, "current_boot_time_utc", return_value=None),
        # Fixture PIDs can collide with a live host TID; keep them as processes.
        patch.object(process_identity, "pid_is_thread", return_value=False),
        patch.object(Path, "read_bytes", read_bytes),
    ):
        yield


def synthetic_record(
    tmp_path: Path,
    timestamp: str,
    name: str,
    *,
    run_started: bool = False,
    parent_timestamp: str | None = None,
    agent_family: str | None = None,
    agent_family_parallel: bool = False,
    waiting_for: list[str] | None = None,
    slot_requested_at: str | None = None,
    pending_question: bool = False,
    done: bool = False,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir=str(tmp_path / "proj"),
        project_file=str(tmp_path / "proj" / "proj.sase"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "proj" / "artifacts" / "ace-run" / timestamp),
        timestamp=timestamp,
        agent_meta=AgentMetaWire(
            name=name,
            pid=100,
            parent_timestamp=parent_timestamp,
            agent_family=agent_family,
            agent_family_parallel=agent_family_parallel,
            run_started_at=("2026-07-17T12:00:00-04:00" if run_started else None),
        ),
        waiting=(
            WaitingMarkerWire(
                waiting_for=waiting_for or [],
                wait_runners=0 if slot_requested_at else None,
                slot_requested_at=slot_requested_at,
            )
            if waiting_for or slot_requested_at
            else None
        ),
        pending_question=(
            PendingQuestionMarkerWire(session_id="question")
            if pending_question
            else None
        ),
        has_done_marker=done,
    )


def synthetic_snapshot(
    tmp_path: Path, records: list[AgentArtifactRecordWire]
) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=1,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
    )
