"""Slot-queued session members keep fork waits blocked."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_hold_liveness import (
    AgentSessionIndexCache,
    agent_session_settled,
)
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import (
    make_waiting_agent,
    run_wait_checks,
)
from tests._monitor_wait_dependency_helpers import (
    _agent_session_fork_source,
    _identity_dep,
    _monitor_handoff_agent_session,
    _update_meta,
    _write_monitor_done,
)

_STAMP = "2026-08-13T09:01:30+00:00"
_SLOT_REQUESTED_AT = "2026-09-25T09:46:35+00:00"


def _failed_monitor_with_running_successor(tmp_path: Path):
    root_dir, monitor_dir, successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        monitor_state="failed",
        followup_outcome="launched",
        followup_agent="monitor-lane--1",
        successor_outcome=False,
    )
    assert successor_dir is not None
    _write_monitor_done(
        monitor_dir,
        monitor_state="failed",
        followup_outcome="launched",
        followup_agent="monitor-lane--1",
    )
    return root_dir, monitor_dir, successor_dir


def _make_slot_queued_successor(
    successor_dir: Path, *, with_stamp: bool = True
) -> None:
    if with_stamp:
        _update_meta(
            successor_dir,
            wait_for=["monitor-lane--code"],
            wait_completed_at=_STAMP,
        )
    (successor_dir / "waiting.json").write_text(
        json.dumps({"slot_requested_at": _SLOT_REQUESTED_AT, "waiting_for": []}),
        encoding="utf-8",
    )


def _make_dependency_parked_successor(successor_dir: Path) -> None:
    _update_meta(successor_dir, wait_for=["monitor-lane--code"])
    (successor_dir / "waiting.json").write_text(
        json.dumps({"waiting_for": ["monitor-lane--code"]}),
        encoding="utf-8",
    )


def _build_index(tmp_path: Path):
    return build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )


def test_incident_slot_queued_successor_blocks_all_session_waits(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, successor_dir = _failed_monitor_with_running_successor(
        tmp_path
    )
    _make_slot_queued_successor(successor_dir, with_stamp=True)
    waiter_dir = make_agent(tmp_path, "proj", "20260813090200", "external-waiter")

    index = _build_index(tmp_path)
    successor = index.artifacts_by_dir[str(successor_dir)]
    assert successor.is_queued
    assert not successor.is_dependency_parked

    fork_source = _agent_session_fork_source(root_dir, name="monitor-lane")
    assert not dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[fork_source],
        self_artifact_dir=waiter_dir,
    ).resolved
    assert not dependency_resolution_status(
        index,
        [],
        [_identity_dep(root_dir, name="monitor-lane")],
        self_artifact_dir=waiter_dir,
    ).resolved
    assert not dependency_resolution_status(
        index, ["monitor-lane"], self_artifact_dir=waiter_dir
    ).resolved

    (successor_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    (successor_dir / "waiting.json").unlink()
    index = _build_index(tmp_path)
    assert dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[fork_source],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_slot_queued_successor_without_stamp_blocks_fork_wait(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, successor_dir = _failed_monitor_with_running_successor(
        tmp_path
    )
    _make_slot_queued_successor(successor_dir, with_stamp=False)
    waiter_dir = make_agent(tmp_path, "proj", "20260813090200", "external-waiter")

    index = _build_index(tmp_path)
    successor = index.artifacts_by_dir[str(successor_dir)]
    assert successor.is_queued
    assert not successor.is_dependency_parked
    assert not dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[_agent_session_fork_source(root_dir, name="monitor-lane")],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_dependency_parked_successor_blocks_fork_wait(tmp_path: Path) -> None:
    root_dir, _monitor_dir, successor_dir = _failed_monitor_with_running_successor(
        tmp_path
    )
    _make_dependency_parked_successor(successor_dir)
    waiter_dir = make_agent(tmp_path, "proj", "20260813090200", "external-waiter")

    index = _build_index(tmp_path)
    successor = index.artifacts_by_dir[str(successor_dir)]
    assert successor.is_queued
    assert successor.is_dependency_parked
    assert not dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[_agent_session_fork_source(root_dir, name="monitor-lane")],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_settled_failed_session_releases_fork_wait(tmp_path: Path) -> None:
    root_dir, _monitor_dir, successor_dir = _monitor_handoff_agent_session(
        tmp_path,
        monitor_state="failed",
        followup_outcome=None,
        followup_agent=None,
        successor_outcome=None,
    )
    assert successor_dir is None
    waiter_dir = make_agent(tmp_path, "proj", "20260813090200", "external-waiter")

    index = _build_index(tmp_path)
    assert dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[_agent_session_fork_source(root_dir, name="monitor-lane")],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_failed_member_followed_by_live_member_blocks_fork_wait(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "monitor-lane--plan",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260813085900",
        "monitor-lane--code",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="failed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260813090100",
        "monitor-lane--1",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--1",
        parent_timestamp=root_dir.name,
    )
    waiter_dir = make_agent(tmp_path, "proj", "20260813090200", "external-waiter")

    index = _build_index(tmp_path)
    assert not dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[_agent_session_fork_source(root_dir, name="monitor-lane")],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_dependency_parked_siblings_do_not_block_each_other(tmp_path: Path) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        done=True,
        outcome="completed",
    )
    first_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_session="b",
        parent_timestamp=parent_dir.name,
    )
    second_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131105",
        "b--review",
        workflow_name="b",
        agent_session="b",
        parent_timestamp=parent_dir.name,
    )
    for child_dir in (first_child_dir, second_child_dir):
        _update_meta(child_dir, wait_for=["b"])
        (child_dir / "waiting.json").write_text(
            json.dumps({"waiting_for": ["b"]}),
            encoding="utf-8",
        )

    index = _build_index(tmp_path)
    for child_dir in (first_child_dir, second_child_dir):
        assert dependency_resolution_status(
            index,
            [],
            [_identity_dep(parent_dir, name="b")],
            self_artifact_dir=child_dir,
        ).resolved


def test_hold_settlement_ignores_slot_queued_member(
    tmp_path: Path, monkeypatch
) -> None:
    import sase.core.agent_hold_liveness as hold_liveness

    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "hold-lane--plan",
        workflow_name="hold-lane",
        agent_session="hold-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    successor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090100",
        "hold-lane--1",
        workflow_name="hold-lane",
        agent_session="hold-lane",
        role_suffix="--1",
        parent_timestamp=root_dir.name,
    )
    _update_meta(
        successor_dir,
        wait_for=["hold-lane--code"],
        wait_completed_at=_STAMP,
    )
    (successor_dir / "waiting.json").write_text(
        json.dumps({"slot_requested_at": _SLOT_REQUESTED_AT, "waiting_for": []}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        hold_liveness,
        "sase_projects_dir",
        lambda: tmp_path / ".sase/projects",
    )
    cache = AgentSessionIndexCache(records=(), allow_scans=True)
    assert agent_session_settled(str(root_dir), "proj", cache)

    index = _build_index(tmp_path)
    root = index.artifacts_by_dir[str(root_dir)]
    session = index.agent_session_candidate_for_root(root)
    assert session is not None
    assert not session.is_resolved


def test_chop_wait_checks_keep_slot_queued_fork_waiter_waiting(
    tmp_path: Path, monkeypatch
) -> None:
    root_dir, _monitor_dir, successor_dir = _failed_monitor_with_running_successor(
        tmp_path
    )
    assert successor_dir is not None
    _make_slot_queued_successor(successor_dir, with_stamp=True)
    waiter_dir = make_waiting_agent(
        tmp_path,
        "monitor-lane",
        wait_for_fork_sources=[
            _agent_session_fork_source(root_dir, name="monitor-lane")
        ],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
