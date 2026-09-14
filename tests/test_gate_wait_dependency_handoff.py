"""Wait-dependency semantics for a gate handing off to a successor agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._gate_wait_dependency_helpers import (
    _gate_handoff_family,
    _identity_dep,
    _write_gate_done,
)


@pytest.mark.parametrize(
    ("gate_state", "followup_outcome"),
    [("answered", "launched"), ("timeout", "launched-degraded")],
)
def test_gate_handoff_resolves_after_successful_successor(
    tmp_path: Path,
    gate_state: str,
    followup_outcome: str,
) -> None:
    root_dir, gate_dir, _successor_dir = _gate_handoff_family(
        tmp_path,
        gate_state=gate_state,
        followup_outcome=followup_outcome,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert dependency_resolution_status(index, ["gate-lane"]).resolved
    assert dependency_resolution_status(
        index,
        [],
        [_identity_dep(root_dir, name="gate-lane")],
    ).resolved
    family = index.family_candidate("gate-lane")
    assert family is not None
    assert family.is_resolved
    assert family.is_done
    assert not family.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == ()

    gate_candidate = index.artifacts_by_dir[str(gate_dir)]
    assert gate_candidate.outcome == (
        "failed" if gate_state == "timeout" else "completed"
    )
    if gate_state == "timeout":
        assert not index.is_resolved("gate-lane--gate")
    else:
        assert index.is_resolved("gate-lane--gate")


def test_gate_handoff_waits_for_missing_successor(tmp_path: Path) -> None:
    _root_dir, gate_dir, _successor_dir = _gate_handoff_family(
        tmp_path,
        gate_state="answered",
        successor_outcome=None,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    family = index.family_candidate("gate-lane")
    assert family is not None
    assert not family.is_resolved
    assert not family.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == ()
    assert index.artifacts_by_dir[str(gate_dir)].outcome == "completed"


def test_gate_handoff_reports_failed_successor_not_gate(
    tmp_path: Path,
) -> None:
    _root_dir, _gate_dir, successor_dir = _gate_handoff_family(
        tmp_path,
        gate_state="timeout",
        successor_outcome="failed",
    )
    assert successor_dir is not None

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    family = index.family_candidate("gate-lane")
    assert family is not None
    assert not family.is_resolved
    assert family.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == (
        index.artifacts_by_dir[str(successor_dir)],
    )


def test_start_failed_gate_superseded_by_retry_resolves_family(
    tmp_path: Path,
) -> None:
    """Gate symmetry for the wait-supersession fix.

    A start-failed gate member with no follow-up must stop blocking the
    family once a later gate retry in the same generation hands off to a
    completed successor -- the same recovery the monitor case exercises.
    """
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
            "gate_state": "failed",
        },
    )
    _write_gate_done(gate_dir, gate_state="failed")
    gate_0_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090100",
        "gate-lane--gate-0",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--gate-0",
        parent_timestamp=gate_dir.name,
        extra_meta={
            "agent_family_role": "gate",
            "gate_id": "gate-2",
            "gate_state": "answered",
            "gate_followup_outcome": "launched",
            "gate_followup_agent": "gate-lane--1",
        },
    )
    _write_gate_done(
        gate_0_dir,
        gate_state="answered",
        followup_outcome="launched",
        followup_agent=None,
    )
    successor_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090200",
        "gate-lane--1",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--1",
        parent_timestamp=gate_0_dir.name,
        done=True,
        outcome="completed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    gate_candidate = index.artifacts_by_dir[str(gate_dir)]
    assert gate_candidate.shell_member_kind == "gate"
    assert gate_candidate.outcome == "failed"

    family = index.family_candidate("gate-lane")
    assert family is not None
    assert family.is_resolved
    assert family.is_done
    assert not family.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == ()
    assert index.artifacts_by_dir[str(successor_dir)].is_resolved
