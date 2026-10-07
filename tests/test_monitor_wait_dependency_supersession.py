"""Retry supersession and effective-outcome semantics for monitor members."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.core.dismissed_agent_completion import effective_done_outcome
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._monitor_wait_dependency_helpers import _update_meta, _write_monitor_done


def _host_completion_recovery_session(
    tmp_path: Path,
    *,
    followup_outcome: str | None,
) -> tuple[Path, Path, Path]:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "monitor-recovery--plan",
        workflow_name="monitor-recovery",
        agent_session="monitor-recovery",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-recovery--mon",
        workflow_name="monitor-recovery",
        agent_session="monitor-recovery",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    _update_meta(
        monitor_dir,
        monitor_state="failed",
        monitor_host_completion_status="recovery",
        monitor_followup_agent="monitor-recovery--1",
    )
    monitor_meta_path = monitor_dir / "agent_meta.json"
    monitor_meta = json.loads(monitor_meta_path.read_text(encoding="utf-8"))
    if followup_outcome is None:
        monitor_meta.pop("monitor_followup_outcome", None)
    else:
        monitor_meta["monitor_followup_outcome"] = followup_outcome
    monitor_meta_path.write_text(json.dumps(monitor_meta), encoding="utf-8")
    _write_monitor_done(
        monitor_dir,
        monitor_state="failed",
        followup_outcome=followup_outcome,
        followup_agent=None,
    )
    followup_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090100",
        "monitor-recovery--1",
        workflow_name="monitor-recovery",
        agent_session="monitor-recovery",
        role_suffix="--1",
        parent_timestamp=monitor_dir.name,
        done=True,
        outcome="completed",
    )
    return root_dir, monitor_dir, followup_dir


def test_recovery_monitor_with_recorded_launch_resolves_agent_session(
    tmp_path: Path,
) -> None:
    _root_dir, monitor_dir, followup_dir = _host_completion_recovery_session(
        tmp_path,
        followup_outcome="launched",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    monitor = index.artifacts_by_dir[str(monitor_dir)]
    assert monitor.outcome == "failed"
    assert index.artifacts_by_dir[str(followup_dir)].is_resolved
    assert dependency_resolution_status(index, ["monitor-recovery"]).resolved


def test_recovery_monitor_without_recorded_launch_keeps_agent_session_blocked(
    tmp_path: Path,
) -> None:
    _root_dir, monitor_dir, _followup_dir = _host_completion_recovery_session(
        tmp_path,
        followup_outcome=None,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    monitor = index.artifacts_by_dir[str(monitor_dir)]
    assert monitor.outcome == "failed"
    status = dependency_resolution_status(index, ["monitor-recovery"])
    assert not status.resolved


def test_start_failed_monitor_superseded_by_retry_resolves_agent_session(
    tmp_path: Path,
) -> None:
    """Reproduces the sase-zt.6.5.3 incident.

    A ``--mon`` that failed at start (teardown shape: ``monitor_state:
    "failed"``, no follow-up fields) must stop blocking the agent session once a
    later ``--mon-0`` retry in the same generation recovers the lane and
    hands off to a completed successor.
    """
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260913170029",
        "sase-zt.6.5.3--plan",
        workflow_name="sase-zt.6.5.3",
        agent_session="sase-zt.6.5.3",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    mon_dir = make_agent(
        tmp_path,
        "proj",
        "20260913170758",
        "sase-zt.6.5.3--mon",
        workflow_name="sase-zt.6.5.3",
        agent_session="sase-zt.6.5.3",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    (mon_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "monitored",
                "monitor_state": "failed",
                "error": (
                    "could not claim workspace for monitor: workspace #11 "
                    "with pid 1556836 was not found; conflicting RUNNING "
                    "claim: #11 pid 3917772 workflow ace(run)-260913_170147"
                ),
            }
        ),
        encoding="utf-8",
    )
    mon_0_dir = make_agent(
        tmp_path,
        "proj",
        "20260913171010",
        "sase-zt.6.5.3--mon-0",
        workflow_name="sase-zt.6.5.3",
        agent_session="sase-zt.6.5.3",
        role_suffix="--mon-0",
        parent_timestamp=mon_dir.name,
    )
    _update_meta(
        mon_0_dir,
        monitor_state="timeout",
        monitor_followup_outcome="launched",
        monitor_followup_agent="sase-zt.6.5.3--2",
    )
    _write_monitor_done(
        mon_0_dir,
        monitor_state="timeout",
        followup_outcome="launched",
        followup_agent=None,
    )
    successor_dir = make_agent(
        tmp_path,
        "proj",
        "20260913171100",
        "sase-zt.6.5.3--2",
        workflow_name="sase-zt.6.5.3",
        agent_session="sase-zt.6.5.3",
        role_suffix="--2",
        parent_timestamp=mon_0_dir.name,
        done=True,
        outcome="completed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    mon_candidate = index.artifacts_by_dir[str(mon_dir)]
    assert mon_candidate.turn_member_kind == "monitor"
    assert mon_candidate.outcome == "failed"

    assert dependency_resolution_status(index, ["sase-zt.6.5.3"]).resolved
    agent_session = index.agent_session_candidate("sase-zt.6.5.3")
    assert agent_session is not None
    assert agent_session.is_resolved
    assert agent_session.is_done
    assert not agent_session.is_failed
    assert index.terminal_blocking_artifacts_for_name("sase-zt.6.5.3") == ()
    assert index.artifacts_by_dir[str(successor_dir)].is_resolved


def test_failed_monitor_not_superseded_by_newer_different_kind_shell_member(
    tmp_path: Path,
) -> None:
    """A newer shell member of a different kind must not supersede a failure.

    Only a same-kind retry proves the lane recovered; a gate opened after a
    failed monitor says nothing about the monitor lane's fate.
    """
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
    mon_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    (mon_dir / "done.json").write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "failed"}),
        encoding="utf-8",
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260813091000",
        "monitor-lane--gate",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--gate",
        parent_timestamp=mon_dir.name,
        extra_meta={
            "agent_session_role": "gate",
            "gate_id": "gate-1",
            "gate_state": "answered",
        },
    )
    (gate_dir / "done.json").write_text(
        json.dumps({"outcome": "gated", "gate_state": "answered"}),
        encoding="utf-8",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    mon_candidate = index.artifacts_by_dir[str(mon_dir)]
    assert mon_candidate.turn_member_kind == "monitor"
    gate_candidate = index.artifacts_by_dir[str(gate_dir)]
    assert gate_candidate.turn_member_kind == "gate"

    agent_session = index.agent_session_candidate("monitor-lane")
    assert agent_session is not None
    assert not agent_session.is_resolved
    assert agent_session.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        mon_candidate,
    )


def _launched_followup_session(
    tmp_path: Path,
    *,
    successor_outcome: str | None | bool,
) -> tuple[Path, Path, Path | None]:
    """Session where a failed ``--mon`` launched its follow-up (sase-1h8.2 shape).

    The clan shares the session name, so the clan entity ties the
    agent-session entity and its unfiltered members reach terminal-blocker
    detection.
    """
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "monitor-lane--plan",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--plan",
        parent_timestamp=None,
        done=True,
        outcome="completed",
    )
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    _update_meta(
        monitor_dir,
        monitor_state="failed",
        monitor_followup_outcome="launched",
        monitor_followup_agent="monitor-lane--1",
    )
    _write_monitor_done(
        monitor_dir,
        monitor_state="failed",
        followup_outcome="launched",
        followup_agent="monitor-lane--1",
    )
    successor_dir: Path | None = None
    if successor_outcome is not None:
        successor_dir = make_agent(
            tmp_path,
            "proj",
            "20260813090100",
            "monitor-lane--1",
            workflow_name="monitor-lane",
            agent_session="monitor-lane",
            role_suffix="--1",
            parent_timestamp=monitor_dir.name,
            done=isinstance(successor_outcome, str),
            outcome=successor_outcome if isinstance(successor_outcome, str) else None,
        )
    for member_dir in (
        root_dir,
        monitor_dir,
        *((successor_dir,) if successor_dir is not None else ()),
    ):
        _update_meta(
            member_dir,
            agent_clan="monitor-lane",
            agent_clan_generation=root_dir.name,
        )
    return root_dir, monitor_dir, successor_dir


@pytest.mark.parametrize("successor_outcome", [False, "completed"])
def test_failed_monitor_with_launched_followup_raises_no_terminal_alert(
    tmp_path: Path,
    successor_outcome: str | bool,
) -> None:
    """A failed monitor whose follow-up launched is not a terminal blocker.

    Whether the follow-up is still running or already completed, the failed
    ``--mon`` was superseded and must not raise a "can never self-resolve"
    alert through the unfiltered clan entity.
    """
    _root_dir, monitor_dir, _successor_dir = _launched_followup_session(
        tmp_path,
        successor_outcome=successor_outcome,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    monitor = index.artifacts_by_dir[str(monitor_dir)]
    assert monitor.outcome == "failed"
    assert monitor.turn_member_kind == "monitor"
    assert monitor.turn_followup_outcome == "launched"
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


def test_newest_member_failed_remains_terminal_blocker(tmp_path: Path) -> None:
    """The session's newest member failed (the sase-1h7.3--2 shape): alert fires."""
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "plain-lane--plan",
        workflow_name="plain-lane",
        agent_session="plain-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    failed_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "plain-lane--1",
        workflow_name="plain-lane",
        agent_session="plain-lane",
        role_suffix="--1",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="failed",
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert index.terminal_blocking_artifacts_for_name("plain-lane") == (
        index.artifacts_by_dir[str(failed_dir)],
    )


@pytest.mark.parametrize(
    ("monitor_state", "expected"),
    [
        ("completed", "completed"),
        ("stopped", "completed"),
        ("failed", "failed"),
        ("timeout", "failed"),
        (None, "failed"),
        ([], "failed"),
    ],
)
def test_effective_monitor_outcome_fails_closed(
    monitor_state: object,
    expected: str,
) -> None:
    assert (
        effective_done_outcome({"outcome": "monitored", "monitor_state": monitor_state})
        == expected
    )
