"""Parity: Python snapshot occupancy vs Rust historical runner stats."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sase.core.agent_scan_facade import rebuild_agent_artifact_index
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
    WorkflowStateWire,
)
from sase.core.runner_slots import running_agent_slot_count
from sase.stats.query import query_run_stats

_BASE = datetime(2026, 7, 10, tzinfo=UTC)
_BASE_TS = int(_BASE.timestamp())
_WINDOW = 100


def _compact(offset: int) -> str:
    return (_BASE + timedelta(seconds=offset)).strftime("%Y%m%d%H%M%S")


def _iso(offset: int) -> str:
    return (_BASE + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class _Shell:
    name: str
    created: int
    start: int | None
    end: int
    family: str | None = None
    parent: str | None = None
    parallel: bool = False
    monitor_id: str | None = None
    pid: int = 100
    appears_as_agent: bool = True
    project: str = "proj"
    question_start: int | None = None
    question_end: int | None = None


def _write_shell(projects: Path, shell: _Shell) -> None:
    artifact = (
        projects / shell.project / "artifacts" / "ace-run" / _compact(shell.created)
    )
    artifact.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {
        "name": shell.name,
        "pid": shell.pid,
        "agent_family": shell.family,
        "agent_family_parallel": shell.parallel,
        "parent_timestamp": shell.parent,
        "monitor_id": shell.monitor_id,
    }
    if shell.start is not None:
        meta["run_started_at"] = _iso(shell.start)
    (artifact / "agent_meta.json").write_text(
        json.dumps(meta),
        encoding="utf-8",
    )
    (artifact / "done.json").write_text(
        json.dumps(
            {
                "outcome": "completed",
                "finished_at": float(_BASE_TS + shell.end),
            }
        ),
        encoding="utf-8",
    )
    if not shell.appears_as_agent:
        (artifact / "workflow_state.json").write_text(
            json.dumps(
                {
                    "workflow_name": "bookkeeping",
                    "status": "completed",
                    "appears_as_agent": False,
                }
            ),
            encoding="utf-8",
        )


def _occupancy_start(shell: _Shell) -> int | None:
    if shell.monitor_id:
        return shell.created
    return shell.start


def _record_as_of(shell: _Shell, instant: int) -> AgentArtifactRecordWire:
    start = _occupancy_start(shell)
    done = start is not None and instant >= shell.end
    pending = (
        shell.question_start is not None
        and shell.question_end is not None
        and shell.question_start <= instant < shell.question_end
    )
    run_started = shell.start is not None and instant >= shell.start
    return AgentArtifactRecordWire(
        project_name=shell.project,
        project_dir=f"/projects/{shell.project}",
        project_file=f"/projects/{shell.project}/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=f"/{shell.project}/{_compact(shell.created)}",
        timestamp=_compact(shell.created),
        agent_meta=AgentMetaWire(
            pid=shell.pid,
            parent_timestamp=shell.parent,
            agent_family=shell.family,
            agent_family_parallel=shell.parallel,
            monitor_id=shell.monitor_id,
            run_started_at=_iso(shell.start) if run_started else None,
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=shell.appears_as_agent),
        has_done_marker=done,
        pending_question=(
            PendingQuestionMarkerWire(session_id="question") if pending else None
        ),
    )


def _python_occupancy_at(shells: tuple[_Shell, ...], instant: int) -> int:
    records = [_record_as_of(shell, instant) for shell in shells]

    def is_live(record: AgentArtifactRecordWire) -> bool:
        for shell in shells:
            if record.timestamp != _compact(shell.created):
                continue
            if record.project_name != shell.project:
                continue
            start = _occupancy_start(shell)
            return start is not None and start <= instant < shell.end
        return False

    return running_agent_slot_count(records, is_live)


def _expected_runner_stats(shells: tuple[_Shell, ...]) -> tuple[int, float]:
    series = [_python_occupancy_at(shells, instant) for instant in range(_WINDOW)]
    return max(series, default=0), float(sum(series))


def _query_runners(tmp_path: Path, shells: tuple[_Shell, ...]) -> dict[str, object]:
    projects = tmp_path / "projects"
    for shell in shells:
        _write_shell(projects, shell)
    index = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index, projects)
    payload = query_run_stats(
        start_ts=_BASE_TS,
        end_ts=_BASE_TS + _WINDOW,
        bucket_seconds=_WINDOW,
        index_path=index,
    )
    runners = payload.get("runners")
    assert isinstance(runners, dict)
    return runners


def _assert_parity(tmp_path: Path, shells: tuple[_Shell, ...]) -> None:
    peak, runner_seconds = _expected_runner_stats(shells)
    runners = _query_runners(tmp_path, shells)
    assert runners["peak_runners"] == peak
    assert runners["runner_seconds"] == pytest.approx(runner_seconds)


def test_standalone_agent_matches_python_occupancy(tmp_path: Path) -> None:
    _assert_parity(
        tmp_path,
        (_Shell(name="solo", created=0, start=10, end=70),),
    )


def test_overlapping_serial_family_does_not_double_count(tmp_path: Path) -> None:
    _assert_parity(
        tmp_path,
        (
            _Shell(name="root", created=0, start=0, end=50, family="fam"),
            _Shell(
                name="serial",
                created=20,
                start=20,
                end=60,
                family="fam",
                parent="root",
            ),
        ),
    )


def test_monitor_handoff_gap_stays_occupied(tmp_path: Path) -> None:
    _assert_parity(
        tmp_path,
        (
            _Shell(name="starter", created=0, start=0, end=20, family="fam"),
            _Shell(
                name="monitor",
                created=15,
                start=30,
                end=80,
                family="fam",
                monitor_id="mon-1",
            ),
            _Shell(
                name="followup",
                created=80,
                start=80,
                end=100,
                family="fam",
                parent=_compact(0),
            ),
        ),
    )


def test_parallel_members_add_their_own_slots(tmp_path: Path) -> None:
    _assert_parity(
        tmp_path,
        (
            _Shell(name="root", created=0, start=0, end=10, family="fam"),
            _Shell(
                name="p1",
                created=10,
                start=10,
                end=80,
                family="fam",
                parent=_compact(0),
                parallel=True,
            ),
            _Shell(
                name="p2",
                created=20,
                start=20,
                end=90,
                family="fam",
                parent=_compact(0),
                parallel=True,
            ),
        ),
    )


def test_shared_family_name_across_projects_counts_separately(tmp_path: Path) -> None:
    _assert_parity(
        tmp_path,
        (
            _Shell(
                name="a",
                created=0,
                start=0,
                end=50,
                family="fam",
                project="proj-a",
            ),
            _Shell(
                name="b",
                created=0,
                start=0,
                end=50,
                family="fam",
                project="proj-b",
            ),
        ),
    )


def test_workflow_step_does_not_occupy(tmp_path: Path) -> None:
    _assert_parity(
        tmp_path,
        (
            _Shell(
                name="step",
                created=0,
                start=0,
                end=80,
                appears_as_agent=False,
            ),
        ),
    )
