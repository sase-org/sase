"""Waiting-marker wait-dependency tests for run-agent waits.

Split from ``tests.test_run_agent_wait_deps``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.run_agent_wait_deps import waiting_marker_dependencies_resolved
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import (
    make_waiting_agent,
    write_workflow_state,
)

__all__ = [
    "test_waiting_marker_dependencies_resolved_matches_terminal_outcome_semantics",
    "test_waiting_marker_fallback_resolves_non_monitor_completed_workflow_without_done",
    "test_waiting_marker_fallback_waits_for_settled_gate_without_terminal_outcome",
    "test_waiting_marker_fallback_waits_for_settled_monitor_without_terminal_outcome",
]


@pytest.mark.parametrize(
    ("outcome", "should_resolve"),
    [
        ("completed", True),
        ("noop", True),
        ("epic_approved", True),
        ("plan_committed", True),
        ("failed", False),
        ("killed", False),
        ("stopped", False),
        ("epic_launch_failed", False),
        ("plan_rejected", False),
    ],
)
def test_waiting_marker_dependencies_resolved_matches_terminal_outcome_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    should_resolve: bool,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome=outcome,
    )

    assert (
        bool(
            waiting_marker_dependencies_resolved(
                waiter_dir / "waiting.json",
                project_name="proj",
                artifacts_dir=str(waiter_dir),
            )
        )
        is should_resolve
    )


def test_waiting_marker_fallback_resolves_non_monitor_completed_workflow_without_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "handoff-lane")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "handoff-lane--plan",
        workflow_name="handoff-lane",
        agent_session="handoff-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    child_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "handoff-lane--code",
        workflow_name="handoff-lane",
        agent_session="handoff-lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
    )
    write_workflow_state(child_dir)

    assert waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_waiting_marker_fallback_waits_for_settled_monitor_without_terminal_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "monitor-lane")
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
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon-0",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--mon-0",
        parent_timestamp=root_dir.name,
        extra_meta={"monitor_state": "completed"},
    )
    write_workflow_state(monitor_dir)

    assert not waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_waiting_marker_fallback_waits_for_settled_gate_without_terminal_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "gate-lane")
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
        },
    )
    write_workflow_state(gate_dir)

    assert not waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
