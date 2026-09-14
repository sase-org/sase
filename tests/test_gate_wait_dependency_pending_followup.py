"""Wait-dependency semantics for a gate with a pending follow-up disposition."""

from __future__ import annotations

from pathlib import Path

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._gate_wait_dependency_helpers import _family_fork_source, _write_gate_done


def test_gate_next_action_without_followup_disposition_blocks_handoff_window(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260827085800",
        "gate-lane--plan",
        workflow_name="gate-lane",
        agent_family="gate-lane",
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
        agent_family="gate-lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_family_role": "gate",
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

    family = index.family_candidate("gate-lane")
    assert family is not None
    assert not family.is_resolved
    assert not family.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == ()


def test_gate_pending_followup_blocks_in_family_waiter(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260827085800",
        "gate-lane--plan",
        workflow_name="gate-lane",
        agent_family="gate-lane",
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
        agent_family="gate-lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_family_role": "gate",
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
        agent_family="gate-lane",
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
            _family_fork_source(root_dir, name="gate-lane"),
        ],
        self_artifact_dir=waiter_dir,
    ).resolved
