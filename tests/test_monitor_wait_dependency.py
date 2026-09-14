"""Wait-dependency semantics for a single monitor family/clan member."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.wait_dependency_resolution import build_wait_dependency_index
from tests._agent_names_fixtures import make_agent
from tests._monitor_wait_dependency_helpers import (
    _monitor_member,
    _write_completed_workflow_state,
)


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
