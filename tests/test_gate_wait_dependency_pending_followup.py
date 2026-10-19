"""Wait-dependency semantics for a gate with a pending follow-up disposition."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._gate_wait_dependency_helpers import (
    _agent_session_fork_source,
    _write_gate_done,
)


def _gate_session_with_failed_followup(
    tmp_path: Path,
    *,
    attempt_live: bool,
    attempt_stage: str,
    owner_pid: int | None,
    done_outcome: str | None,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260827085800",
        "gate-lane--plan",
        workflow_name="gate-lane",
        agent_session="gate-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090000",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_session="gate-lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_session_role": "gate",
            "gate_id": "gate-1",
            "gate_state": "answered",
            "gate_next_action": "continue after approval",
            "gate_followup_outcome": "failed",
            "gate_followup_attempt_live": attempt_live,
            "gate_followup_attempt_stage": attempt_stage,
            "gate_followup_attempt_owner_pid": owner_pid,
        },
    )
    _write_gate_done(gate_dir, gate_state="answered", followup_outcome=done_outcome)


def test_gate_next_action_without_followup_disposition_blocks_handoff_window(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260827085800",
        "gate-lane--plan",
        workflow_name="gate-lane",
        agent_session="gate-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090000",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_session="gate-lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_session_role": "gate",
            "gate_id": "gate-1",
            "gate_state": "answered",
            "gate_next_action": "continue after approval",
        },
    )
    _write_gate_done(gate_dir, gate_state="answered")

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    agent_session = index.agent_session_candidate("gate-lane")
    assert agent_session is not None
    assert not agent_session.is_resolved
    assert not agent_session.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == ()


def test_gate_pending_followup_blocks_in_agent_session_waiter(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260827085800",
        "gate-lane--plan",
        workflow_name="gate-lane",
        agent_session="gate-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090000",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_session="gate-lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_session_role": "gate",
            "gate_id": "gate-1",
            "gate_state": "answered",
            "gate_next_action": "continue after approval",
        },
    )
    _write_gate_done(gate_dir, gate_state="answered")
    waiter_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090100",
        "gate-lane--1",
        workflow_name="gate-lane",
        agent_session="gate-lane",
        role_suffix="--1",
        parent_timestamp=gate_dir.name,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not dependency_resolution_status(
        index,
        [],
        wait_fork_sources=[
            _agent_session_fork_source(root_dir, name="gate-lane"),
        ],
        self_artifact_dir=waiter_dir,
    ).resolved


@pytest.mark.parametrize(
    "done_outcome",
    [None, "failed"],
    ids=["meta-only-settle-window", "meta-and-done-resume-window"],
)
def test_live_failed_gate_attempt_keeps_session_pending(
    tmp_path: Path,
    done_outcome: str | None,
) -> None:
    _gate_session_with_failed_followup(
        tmp_path,
        attempt_live=True,
        attempt_stage="launching",
        owner_pid=os.getpid(),
        done_outcome=done_outcome,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    agent_session = index.agent_session_candidate("gate-lane")
    assert agent_session is not None
    assert not agent_session.is_resolved
    assert not dependency_resolution_status(index, ["gate-lane"]).resolved


@pytest.mark.parametrize(
    ("attempt_live", "attempt_stage", "owner_is_live"),
    [(False, "failed", None), (True, "launching", False)],
    ids=["settled-failure", "dead-attempt-owner"],
)
def test_settled_failed_gate_attempt_releases_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attempt_live: bool,
    attempt_stage: str,
    owner_is_live: bool | None,
) -> None:
    checked_pids: list[int] = []
    if owner_is_live is not None:

        def is_process_running(pid: int) -> bool:
            checked_pids.append(pid)
            return owner_is_live

        monkeypatch.setattr(
            "sase.ace.hooks.processes.is_process_running", is_process_running
        )

    _gate_session_with_failed_followup(
        tmp_path,
        attempt_live=attempt_live,
        attempt_stage=attempt_stage,
        owner_pid=os.getpid(),
        done_outcome="failed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    agent_session = index.agent_session_candidate("gate-lane")
    assert agent_session is not None
    assert agent_session.is_resolved
    assert dependency_resolution_status(index, ["gate-lane"]).resolved
    if owner_is_live is False:
        assert checked_pids == [os.getpid()]
