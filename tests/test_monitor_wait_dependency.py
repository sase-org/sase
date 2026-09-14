"""Wait-dependency semantics for monitor family and clan members."""

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


def _identity_dep(artifact_dir: Path, *, name: str) -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _family_fork_source(root_dir: Path, *, name: str) -> dict[str, str]:
    return {**_identity_dep(root_dir, name=name), "kind": "family"}


def _monitor_member(
    tmp_path: Path,
    monitor_state: object,
    *,
    with_done_marker: bool = True,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon",
    )
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "agent_clan": "monitor-clan",
            "agent_clan_generation": "20260813085900",
            "monitor_state": "running",
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    if with_done_marker:
        done: dict[str, object] = {"outcome": "monitored"}
        if monitor_state is not None:
            done["monitor_state"] = monitor_state
        (artifact_dir / "done.json").write_text(
            json.dumps(done),
            encoding="utf-8",
        )
    return artifact_dir


def _update_meta(artifact_dir: Path, **updates: object) -> None:
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(updates)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _write_monitor_done(
    artifact_dir: Path,
    *,
    monitor_state: str = "timeout",
    followup_outcome: str | None = "launched",
    followup_agent: str | None = "monitor-lane--1",
) -> None:
    done: dict[str, object] = {
        "outcome": "monitored",
        "monitor_state": monitor_state,
    }
    if followup_outcome is not None:
        done["monitor_followup_outcome"] = followup_outcome
    if followup_agent is not None:
        done["monitor_followup_agent"] = followup_agent
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")


def _write_completed_workflow_state(artifact_dir: Path) -> None:
    (artifact_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "monitor-lane",
                "status": "completed",
                "current_step_index": 0,
                "steps": [
                    {
                        "name": "main",
                        "status": "completed",
                        "error": None,
                        "traceback": None,
                    }
                ],
                "appears_as_agent": True,
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "step_name": "main",
                "status": "completed",
                "error": None,
                "traceback": None,
            }
        ),
        encoding="utf-8",
    )


def _monitor_handoff_family(
    tmp_path: Path,
    *,
    monitor_state: str = "timeout",
    followup_outcome: str | None = "launched",
    followup_agent: str | None = "monitor-lane--1",
    successor_outcome: str | None | bool = "completed",
) -> tuple[Path, Path, Path | None]:
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
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    _update_meta(
        monitor_dir,
        monitor_state=monitor_state,
        monitor_followup_outcome=followup_outcome,
        monitor_followup_agent=followup_agent,
    )
    _write_monitor_done(
        monitor_dir,
        monitor_state=monitor_state,
        followup_outcome=followup_outcome,
        followup_agent=None,
    )

    successor_dir: Path | None = None
    if successor_outcome is not None:
        successor_dir = make_agent(
            tmp_path,
            "proj",
            "20260813090100",
            followup_agent or "monitor-lane--1",
            workflow_name="monitor-lane",
            agent_family="monitor-lane",
            role_suffix="--1",
            parent_timestamp=root_dir.name,
            done=isinstance(successor_outcome, str),
            outcome=successor_outcome if isinstance(successor_outcome, str) else None,
        )
    return root_dir, monitor_dir, successor_dir


@pytest.mark.parametrize("monitor_state", ["completed", "stopped"])
def test_successful_monitor_resolves_family_and_clan(
    tmp_path: Path,
    monitor_state: str,
) -> None:
    artifact_dir = _monitor_member(tmp_path, monitor_state)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert index.is_resolved("monitor-lane")
    family = index.family_candidate("monitor-lane")
    clan = index.clan_candidate("monitor-clan")
    assert family is not None and family.is_resolved and family.is_done
    assert clan is not None and clan.is_resolved and clan.is_done
    assert index.artifacts_by_dir[str(artifact_dir)].outcome == "completed"
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


@pytest.mark.parametrize(
    "monitor_state", ["failed", "timeout", "lost", "unknown", None]
)
def test_unsuccessful_monitor_blocks_and_is_reported_as_terminal(
    tmp_path: Path,
    monitor_state: str | None,
) -> None:
    artifact_dir = _monitor_member(tmp_path, monitor_state)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("monitor-lane")
    family = index.family_candidate("monitor-lane")
    clan = index.clan_candidate("monitor-clan")
    assert family is not None and family.is_failed
    assert clan is not None and clan.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        index.artifacts_by_dir[str(artifact_dir)],
    )
    assert index.artifacts_by_dir[str(artifact_dir)].outcome == "failed"


def test_running_monitor_without_done_marker_still_blocks(
    tmp_path: Path,
) -> None:
    _monitor_member(tmp_path, "running", with_done_marker=False)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("monitor-lane")
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


@pytest.mark.parametrize(
    ("agent_family_role", "role_suffix"),
    [
        ("monitor", None),
        (None, "--mon"),
        (None, "--mon-0"),
    ],
)
def test_settled_monitor_without_terminal_outcome_waits_for_handoff_successor(
    tmp_path: Path,
    agent_family_role: str | None,
    role_suffix: str | None,
) -> None:
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
    monitor_suffix = role_suffix or "--mon"
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        f"monitor-lane{monitor_suffix}",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix=role_suffix,
        parent_timestamp=root_dir.name,
        extra_meta={
            key: value
            for key, value in {
                "agent_family_role": agent_family_role,
                "agent_clan": "monitor-clan",
                "agent_clan_generation": root_dir.name,
                "monitor_state": "completed",
            }.items()
            if value is not None
        },
    )
    _write_completed_workflow_state(monitor_dir)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    monitor_candidate = index.artifacts_by_dir[str(monitor_dir)]
    assert monitor_candidate.outcome is None
    assert not monitor_candidate.is_resolved
    assert not index.is_resolved(monitor_candidate.name)

    family = index.family_candidate("monitor-lane")
    assert family is not None
    assert not family.is_resolved
    assert family.is_done
    assert not family.is_failed
    assert not index.is_resolved("monitor-lane")

    clan = index.clan_candidate("monitor-clan")
    assert clan is not None
    assert not clan.is_resolved
    assert not clan.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


@pytest.mark.parametrize("followup_outcome", ["launched", "launched-degraded"])
def test_failed_monitor_handoff_resolves_after_successful_successor(
    tmp_path: Path,
    followup_outcome: str,
) -> None:
    root_dir, monitor_dir, _successor_dir = _monitor_handoff_family(
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
    family = index.family_candidate("monitor-lane")
    assert family is not None
    assert family.is_resolved
    assert family.is_done
    assert not family.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()

    monitor_candidate = index.artifacts_by_dir[str(monitor_dir)]
    assert monitor_candidate.outcome == "failed"
    assert not index.is_resolved("monitor-lane--mon")
    assert index.terminal_blocking_artifacts_for_name("monitor-lane--mon") == (
        monitor_candidate,
    )


def test_failed_monitor_handoff_waits_for_missing_successor(tmp_path: Path) -> None:
    _root_dir, monitor_dir, _successor_dir = _monitor_handoff_family(
        tmp_path,
        successor_outcome=None,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    family = index.family_candidate("monitor-lane")
    assert family is not None
    assert not family.is_resolved
    assert family.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == (
        index.artifacts_by_dir[str(monitor_dir)],
    )


def test_failed_monitor_handoff_waits_for_running_successor(tmp_path: Path) -> None:
    _root_dir, _monitor_dir, _successor_dir = _monitor_handoff_family(
        tmp_path,
        successor_outcome=False,
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    family = index.family_candidate("monitor-lane")
    assert family is not None
    assert not family.is_resolved
    assert not family.is_failed
    assert index.terminal_blocking_artifacts_for_name("monitor-lane") == ()


def test_monitor_handoff_successor_does_not_wait_on_its_own_family(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, successor_dir = _monitor_handoff_family(
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
            _family_fork_source(root_dir, name="monitor-lane"),
        ],
        self_artifact_dir=successor_dir,
    ).resolved


def test_external_waiter_still_blocks_on_a_live_handoff_successor(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, _successor_dir = _monitor_handoff_family(
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
            _family_fork_source(root_dir, name="monitor-lane"),
        ],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_family_member_waiting_on_own_family_blocks_on_a_live_sibling(
    tmp_path: Path,
) -> None:
    root_dir, _monitor_dir, successor_dir = _monitor_handoff_family(
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
        agent_family="monitor-lane",
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
            _family_fork_source(root_dir, name="monitor-lane"),
        ],
        self_artifact_dir=successor_dir,
    ).resolved


def test_failed_monitor_handoff_reports_failed_successor_not_monitor(
    tmp_path: Path,
) -> None:
    _root_dir, _monitor_dir, successor_dir = _monitor_handoff_family(
        tmp_path,
        successor_outcome="failed",
    )
    assert successor_dir is not None

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    family = index.family_candidate("monitor-lane")
    assert family is not None
    assert not family.is_resolved
    assert family.is_failed
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
    _root_dir, monitor_dir, _successor_dir = _monitor_handoff_family(
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
