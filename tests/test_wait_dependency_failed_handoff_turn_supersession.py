"""Failed agent-turn supersession when the turn handed off to a monitor or gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks
from tests._gate_wait_dependency_helpers import _write_gate_done
from tests._monitor_wait_dependency_helpers import _update_meta, _write_monitor_done

SESSION = "lane"
PROJECT = "proj"
ROOT_TS = "20261026160816"
MON_TS = "20261026221539"
FOLLOWUP_TS = "20261026231556"
MON_0_TS = "20261026232303"
NEWEST_TS = "20261026233958"


def _index(tmp_path: Path):
    return build_wait_dependency_index(
        PROJECT,
        projects_root=tmp_path / ".sase/projects",
    )


def _failed_plan(tmp_path: Path) -> Path:
    return make_agent(
        tmp_path,
        PROJECT,
        ROOT_TS,
        f"{SESSION}--plan",
        workflow_name=SESSION,
        agent_session=SESSION,
        role_suffix="--plan",
        done=True,
        outcome="failed",
    )


def _turn(
    tmp_path: Path,
    *,
    timestamp: str,
    suffix: str,
    parent_timestamp: str,
    outcome: str,
) -> Path:
    return make_agent(
        tmp_path,
        PROJECT,
        timestamp,
        f"{SESSION}{suffix}",
        workflow_name=SESSION,
        agent_session=SESSION,
        role_suffix=suffix,
        parent_timestamp=parent_timestamp,
        done=True,
        outcome=outcome,
    )


def _monitor(
    tmp_path: Path,
    *,
    timestamp: str,
    suffix: str,
    parent_timestamp: str,
    monitor_state: str,
    followup_outcome: str | None,
    followup_agent: str | None,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        PROJECT,
        timestamp,
        f"{SESSION}{suffix}",
        workflow_name=SESSION,
        agent_session=SESSION,
        role_suffix=suffix,
        parent_timestamp=parent_timestamp,
    )
    _update_meta(
        artifact_dir,
        monitor_state=monitor_state,
        monitor_followup_outcome=followup_outcome,
        monitor_followup_agent=followup_agent,
    )
    _write_monitor_done(
        artifact_dir,
        monitor_state=monitor_state,
        followup_outcome=followup_outcome,
        followup_agent=followup_agent,
    )
    return artifact_dir


def _gate(
    tmp_path: Path,
    *,
    timestamp: str,
    suffix: str,
    parent_timestamp: str,
    gate_state: str,
    followup_outcome: str | None,
    followup_agent: str | None,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        PROJECT,
        timestamp,
        f"{SESSION}{suffix}",
        workflow_name=SESSION,
        agent_session=SESSION,
        role_suffix=suffix,
        parent_timestamp=parent_timestamp,
        extra_meta={
            "agent_session_role": "gate",
            "gate_id": "gate-1",
            "gate_state": gate_state,
            "gate_followup_outcome": followup_outcome,
            "gate_followup_agent": followup_agent,
        },
    )
    _write_gate_done(
        artifact_dir,
        gate_state=gate_state,
        followup_outcome=followup_outcome,
        followup_agent=followup_agent,
    )
    return artifact_dir


def _sase_1oj4_shape(
    tmp_path: Path,
    *,
    handoff_kind: str = "monitor",
    newest_outcome: str = "completed",
) -> Path:
    """Reproduce the sase-1oj.4 generation; return the newest follow-up dir."""
    root = _failed_plan(tmp_path)
    followup_name = f"{SESSION}--1"
    newest_name = f"{SESSION}--2"
    if handoff_kind == "gate":
        _gate(
            tmp_path,
            timestamp=MON_TS,
            suffix="--gate",
            parent_timestamp=root.name,
            gate_state="timeout",
            followup_outcome="launched",
            followup_agent=followup_name,
        )
        followup = _turn(
            tmp_path,
            timestamp=FOLLOWUP_TS,
            suffix="--1",
            parent_timestamp=root.name,
            outcome="completed",
        )
        _gate(
            tmp_path,
            timestamp=MON_0_TS,
            suffix="--gate-0",
            parent_timestamp=followup.name,
            gate_state="answered",
            followup_outcome="launched",
            followup_agent=newest_name,
        )
    else:
        _monitor(
            tmp_path,
            timestamp=MON_TS,
            suffix="--mon",
            parent_timestamp=root.name,
            monitor_state="failed",
            followup_outcome="launched",
            followup_agent=followup_name,
        )
        followup = _turn(
            tmp_path,
            timestamp=FOLLOWUP_TS,
            suffix="--1",
            parent_timestamp=root.name,
            outcome="completed",
        )
        _monitor(
            tmp_path,
            timestamp=MON_0_TS,
            suffix="--mon-0",
            parent_timestamp=followup.name,
            monitor_state="completed",
            followup_outcome="launched",
            followup_agent=newest_name,
        )
    return _turn(
        tmp_path,
        timestamp=NEWEST_TS,
        suffix="--2",
        parent_timestamp=root.name,
        outcome=newest_outcome,
    )


@pytest.mark.parametrize("handoff_kind", ["monitor", "gate"])
def test_failed_handoff_turn_resolves_when_followup_lane_completes(
    tmp_path: Path,
    handoff_kind: str,
) -> None:
    newest = _sase_1oj4_shape(tmp_path, handoff_kind=handoff_kind)
    index = _index(tmp_path)

    assert dependency_resolution_status(index, [SESSION]).resolved
    assert index.terminal_blocking_artifacts_for_name(SESSION) == ()
    assert index.artifacts_by_dir[str(newest)].is_resolved
    agent_session = index.agent_session_candidate(SESSION)
    assert agent_session is not None
    assert agent_session.is_resolved
    assert agent_session.is_done


def test_failed_handoff_turn_ready_json_for_waiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, SESSION)
    _sase_1oj4_shape(tmp_path)
    run_wait_checks(tmp_path, monkeypatch)
    assert (waiter_dir / "ready.json").exists()


def test_failed_newest_followup_stays_waiting_and_blocks(tmp_path: Path) -> None:
    newest = _sase_1oj4_shape(tmp_path, newest_outcome="failed")
    index = _index(tmp_path)

    status = dependency_resolution_status(index, [SESSION])
    assert not status.resolved
    assert index.terminal_blocking_artifacts_for_name(SESSION) == (
        index.artifacts_by_dir[str(newest)],
    )


def test_launched_monitor_with_absent_followup_stays_waiting(tmp_path: Path) -> None:
    root = _failed_plan(tmp_path)
    _monitor(
        tmp_path,
        timestamp=MON_TS,
        suffix="--mon",
        parent_timestamp=root.name,
        monitor_state="failed",
        followup_outcome="launched",
        followup_agent=f"{SESSION}--1",
    )
    index = _index(tmp_path)

    status = dependency_resolution_status(index, [SESSION])
    assert not status.resolved


def test_monitor_with_unsuccessful_followup_outcome_stays_waiting(
    tmp_path: Path,
) -> None:
    root = _failed_plan(tmp_path)
    _monitor(
        tmp_path,
        timestamp=MON_TS,
        suffix="--mon",
        parent_timestamp=root.name,
        monitor_state="failed",
        followup_outcome="not-launchable",
        followup_agent=f"{SESSION}--1",
    )
    index = _index(tmp_path)

    status = dependency_resolution_status(index, [SESSION])
    assert not status.resolved


def test_monitor_parented_to_different_turn_does_not_supersede(tmp_path: Path) -> None:
    root = _failed_plan(tmp_path)
    other = _turn(
        tmp_path,
        timestamp=FOLLOWUP_TS,
        suffix="--1",
        parent_timestamp=root.name,
        outcome="completed",
    )
    _monitor(
        tmp_path,
        timestamp="20261026232000",
        suffix="--mon",
        parent_timestamp=other.name,
        monitor_state="failed",
        followup_outcome="launched",
        followup_agent=f"{SESSION}--2",
    )
    _turn(
        tmp_path,
        timestamp=NEWEST_TS,
        suffix="--2",
        parent_timestamp=root.name,
        outcome="completed",
    )
    index = _index(tmp_path)

    status = dependency_resolution_status(index, [SESSION])
    assert not status.resolved
    agent_session = index.agent_session_candidate(SESSION)
    assert agent_session is not None
    assert not agent_session.is_resolved
