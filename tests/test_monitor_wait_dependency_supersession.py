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


def test_start_failed_monitor_superseded_by_retry_resolves_family(
    tmp_path: Path,
) -> None:
    """Reproduces the sase-zt.6.5.3 incident.

    A ``--mon`` that failed at start (teardown shape: ``monitor_state:
    "failed"``, no follow-up fields) must stop blocking the family once a
    later ``--mon-0`` retry in the same generation recovers the lane and
    hands off to a completed successor.
    """
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260913170029",
        "sase-zt.6.5.3--plan",
        workflow_name="sase-zt.6.5.3",
        agent_family="sase-zt.6.5.3",
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
        agent_family="sase-zt.6.5.3",
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
        agent_family="sase-zt.6.5.3",
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
        agent_family="sase-zt.6.5.3",
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
    assert mon_candidate.shell_member_kind == "monitor"
    assert mon_candidate.outcome == "failed"

    assert dependency_resolution_status(index, ["sase-zt.6.5.3"]).resolved
    family = index.family_candidate("sase-zt.6.5.3")
    assert family is not None
    assert family.is_resolved
    assert family.is_done
    assert not family.is_failed
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
        agent_family="monitor-lane",
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
        agent_family="monitor-lane",
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
        agent_family="monitor-lane",
        role_suffix="--gate",
        parent_timestamp=mon_dir.name,
        extra_meta={
            "agent_family_role": "gate",
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
    assert mon_candidate.shell_member_kind == "monitor"
    gate_candidate = index.artifacts_by_dir[str(gate_dir)]
    assert gate_candidate.shell_member_kind == "gate"

    family = index.family_candidate("monitor-lane")
    assert family is not None
    assert not family.is_resolved
    assert family.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        mon_candidate,
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
