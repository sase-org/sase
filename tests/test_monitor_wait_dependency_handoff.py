"""Wait-dependency semantics for monitor successor handoff."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._monitor_wait_dependency_helpers import (
    _agent_session_fork_source,
    _identity_dep,
    _monitor_handoff_agent_session,
)


@pytest.mark.parametrize("followup_outcome", ["launched", "launched-degraded"])
def test_failed_monitor_handoff_resolves_after_successful_successor(
    tmp_path: Path,
    followup_outcome: str,
) -> None:
    root_dir, monitor_dir, _successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        followup_outcome=followup_outcome,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert dependency_resolution_status(index, ["monitor-lane"]).resolved
    assert dependency_resolution_status(
        index,
        [],
        [_identity_dep(root_dir, name="monitor-lane")],
    ).resolved
    agent_session = index.agent_session_candidate("monitor-lane")
    assert agent_session is not None
    assert agent_session.is_resolved
    assert agent_session.is_done
    assert not agent_session.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()

    monitor_candidate = index.artifacts_by_dir[str(monitor_dir)]
    assert monitor_candidate.outcome == "failed"
    assert not index.is_resolved("monitor-lane--mon")
    assert index.terminal_blocking_artifacts_for_name("monitor-lane--mon") == (
        monitor_candidate,
    )


def test_failed_monitor_handoff_waits_for_missing_successor(tmp_path: Path) -> None:
    _root_dir, monitor_dir, _successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        successor_outcome=None,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    agent_session = index.agent_session_candidate("monitor-lane")
    assert agent_session is not None
    assert not agent_session.is_resolved
    assert agent_session.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        index.artifacts_by_dir[str(monitor_dir)],
    )


def test_failed_monitor_handoff_waits_for_running_successor(tmp_path: Path) -> None:
    _root_dir, _monitor_dir, _successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        successor_outcome=False,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    agent_session = index.agent_session_candidate("monitor-lane")
    assert agent_session is not None
    assert not agent_session.is_resolved
    assert not agent_session.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


def test_monitor_handoff_successor_does_not_wait_on_its_own_agent_session(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        successor_outcome=False,
    )
    assert successor_dir is not None

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[
            _agent_session_fork_source(root_dir, name="monitor-lane"),
        ],
        self_artifact_dir=successor_dir,
    ).resolved


def test_external_waiter_still_blocks_on_a_live_handoff_successor(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, _successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        successor_outcome=False,
    )
    waiter_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090200",
        "external-waiter",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[
            _agent_session_fork_source(root_dir, name="monitor-lane"),
        ],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_agent_session_member_waiting_on_own_agent_session_blocks_on_a_live_sibling(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        successor_outcome=False,
    )
    assert successor_dir is not None
    make_agent(
        tmp_path,
        "proj",
        "20260813090200",
        "monitor-lane--review",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--review",
        parent_timestamp=root_dir.name,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[
            _agent_session_fork_source(root_dir, name="monitor-lane"),
        ],
        self_artifact_dir=successor_dir,
    ).resolved


def test_failed_monitor_handoff_reports_failed_successor_not_monitor(
    tmp_path: Path,
) -> None:
    _root_dir, _monitor_dir, successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        successor_outcome="failed",
    )
    assert successor_dir is not None

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    agent_session = index.agent_session_candidate("monitor-lane")
    assert agent_session is not None
    assert not agent_session.is_resolved
    assert agent_session.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        index.artifacts_by_dir[str(successor_dir)],
    )


@pytest.mark.parametrize(
    ("followup_outcome", "followup_agent"),
    [
        (None, "monitor-lane--1"),
        ("not-launchable", "monitor-lane--1"),
        ("launched", None),
    ],
)
def test_unsuccessful_monitor_handoff_remains_terminal_blocker(
    tmp_path: Path,
    followup_outcome: str | None,
    followup_agent: str | None,
) -> None:
    _root_dir, monitor_dir, _successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        followup_outcome=followup_outcome,
        followup_agent=followup_agent,
        successor_outcome="completed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("monitor-lane")
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        index.artifacts_by_dir[str(monitor_dir)],
    )
