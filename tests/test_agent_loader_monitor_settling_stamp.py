"""Loader stamp: a terminal monitor whose live supervisor is still settling.

The monitor supervisor persists ``monitor_state: failed`` before it decides
and launches the continuation, and stamps ``stopped_at`` only afterward.
Loader normalization proves the supervisor is alive with a bounded probe and
stamps ``monitor_settling`` so the owning session root does not read Failed
during that window.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sase.ace.tui.models import _agent_loader_normalization as normalization
from sase.ace.tui.models._agent_loader_normalization import (
    _mark_settling_monitor_turns,
    normalize_loaded_agents,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.agent.status_buckets import agent_status_bucket

_STARTED = datetime(2026, 11, 20, 9, 30, 0)
_ROOT_SUFFIX = "20261120093000"
LIVE_PID = 4242
DEAD_PID = 99_999_999


def _root() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sess",
        project_file="/tmp/settling.sase",
        status="DONE",
        status_bucket="Done",
        start_time=_STARTED,
        stop_time=_STARTED + timedelta(minutes=2),
        raw_suffix=_ROOT_SUFFIX,
        agent_name="sess",
        agent_session="sess",
        agent_session_role="root",
    )


def _monitor(
    *,
    pid: int | None = LIVE_PID,
    monitor_state: str = "failed",
    status_bucket: str = "Failed",
    stop_time: datetime | None = None,
    role: str = "monitor",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sess-mon",
        project_file="/tmp/settling.sase",
        status="RUNNING",
        status_bucket=status_bucket,
        start_time=_STARTED + timedelta(minutes=3),
        run_start_time=_STARTED + timedelta(minutes=3),
        stop_time=stop_time,
        raw_suffix="20261120093300",
        parent_timestamp=_ROOT_SUFFIX,
        role_suffix="--mon",
        agent_name="sess--mon",
        agent_session="sess",
        agent_session_role=role,
        monitor_id="m-settle",
        monitor_state=monitor_state,
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_label="just check",
        monitor_command="just check",
        pid=pid,
    )


def _normalize(
    rows: list[Agent],
    *,
    live_pids: frozenset[int] = frozenset({LIVE_PID}),
) -> list[Agent]:
    return normalize_loaded_agents(
        rows,
        [],
        is_process_running=lambda pid: pid in live_pids,
    )


def _find(rows: list[Agent], name: str) -> Agent:
    seen: set[int] = set()
    stack = list(rows)
    while stack:
        row = stack.pop()
        if id(row) in seen:
            continue
        seen.add(id(row))
        if row.agent_name == name:
            return row
        stack.extend((*row.runtime_children, *row.followup_agents))
    raise AssertionError(f"row {name!r} not found")


def test_live_supervisor_settle_window_is_stamped_and_keeps_root_running() -> None:
    root = _root()
    monitor = _monitor()

    rows = _normalize([root, monitor])

    stamped = _find(rows, "sess--mon")
    assert stamped.monitor_settling is True
    # The monitor row stays truthful about its own command.
    assert agent_status_bucket(stamped) == "Failed"
    mirrored = _find(rows, "sess")
    assert agent_status_bucket(mirrored) == "Running"


def test_dead_supervisor_is_not_settling_and_root_reads_failed() -> None:
    rows = _normalize([_root(), _monitor(pid=DEAD_PID)])

    assert _find(rows, "sess--mon").monitor_settling is False
    assert agent_status_bucket(_find(rows, "sess")) == "Failed"


def test_identity_mismatch_is_not_settling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        normalization, "process_identity_matches", lambda _pid, _recorded: False
    )
    monitor = _monitor()
    monitor.process_identity = "boot:1"

    rows = _normalize([_root(), monitor])

    assert _find(rows, "sess--mon").monitor_settling is False
    assert agent_status_bucket(_find(rows, "sess")) == "Failed"


@pytest.mark.parametrize(
    "monitor",
    [
        pytest.param(
            _monitor(stop_time=_STARTED + timedelta(minutes=5)), id="stop-time-set"
        ),
        pytest.param(
            _monitor(monitor_state="running", status_bucket="Running"), id="running"
        ),
        pytest.param(_monitor(pid=None), id="no-pid"),
        pytest.param(_monitor(role="member"), id="not-a-monitor"),
    ],
)
def test_non_candidates_are_not_settling(monitor: Agent) -> None:
    rows = _normalize([_root(), monitor])

    assert _find(rows, "sess--mon").monitor_settling is False


def test_stale_stamp_is_cleared_on_reload() -> None:
    monitor = _monitor(stop_time=_STARTED + timedelta(minutes=5))
    monitor.monitor_settling = True

    rows = _normalize([_root(), monitor])

    assert _find(rows, "sess--mon").monitor_settling is False


def test_liveness_is_probed_once_per_pid() -> None:
    probes: list[int] = []

    def is_running(pid: int) -> bool:
        probes.append(pid)
        return True

    first = _monitor()
    second = _monitor()
    second.monitor_id = "m-other"

    _mark_settling_monitor_turns([first, second], is_process_running=is_running)

    assert probes == [LIVE_PID]
    assert first.monitor_settling is True
    assert second.monitor_settling is True
