"""Wait-dependency semantics for a single gate family/clan member."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._gate_wait_dependency_helpers import (
    _MISSING,
    _gate_member,
    _identity_dep,
    _write_completed_workflow_state,
    _write_gate_done,
)


@pytest.mark.parametrize("gate_state", ["answered", "completed", "stopped"])
def test_successful_gate_resolves_family_and_clan(
    tmp_path: Path,
    gate_state: str,
) -> None:
    artifact_dir = _gate_member(tmp_path, gate_state)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert index.is_resolved("gate-lane")
    family = index.family_candidate("gate-lane")
    clan = index.clan_candidate("gate-clan")
    assert family is not None and family.is_resolved and family.is_done
    assert clan is not None and clan.is_resolved and clan.is_done
    assert index.artifacts_by_dir[str(artifact_dir)].outcome == "completed"
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == ()


@pytest.mark.parametrize(
    "gate_state",
    ["failed", "timeout", "lost", "unknown", None, [], _MISSING],
    ids=["failed", "timeout", "lost", "unknown", "none", "non_string", "missing"],
)
def test_unsuccessful_gate_blocks_and_is_reported_as_terminal(
    tmp_path: Path,
    gate_state: Any,
) -> None:
    artifact_dir = _gate_member(tmp_path, gate_state)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("gate-lane")
    family = index.family_candidate("gate-lane")
    clan = index.clan_candidate("gate-clan")
    assert family is not None and family.is_failed
    assert clan is not None and clan.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == (
        index.artifacts_by_dir[str(artifact_dir)],
    )
    assert index.artifacts_by_dir[str(artifact_dir)].outcome == "failed"


def test_settled_gate_members_resolve_interleaved_family_and_clan(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260827124955",
        "gate-lane--plan",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
        extra_meta={
            "agent_clan": "gate-clan",
            "agent_clan_generation": "20260827124955",
        },
    )
    gate_dir = make_agent(
        tmp_path,
        "proj",
        "20260827130544",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--gate",
        parent_timestamp=root_dir.name,
        extra_meta={
            "agent_family_role": "gate",
            "agent_clan": "gate-clan",
            "agent_clan_generation": root_dir.name,
            "gate_id": "gate-1",
            "gate_state": "answered",
        },
    )
    _write_gate_done(gate_dir, gate_state="answered")
    child_dir = make_agent(
        tmp_path,
        "proj",
        "20260827130554",
        "gate-lane--1",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--1",
        parent_timestamp=gate_dir.name,
        done=True,
        outcome="completed",
        extra_meta={
            "agent_clan": "gate-clan",
            "agent_clan_generation": root_dir.name,
        },
    )
    gate_0_dir = make_agent(
        tmp_path,
        "proj",
        "20260827131341",
        "gate-lane--gate-0",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--gate-0",
        parent_timestamp=child_dir.name,
        extra_meta={
            "agent_family_role": "gate",
            "agent_clan": "gate-clan",
            "agent_clan_generation": root_dir.name,
            "gate_id": "gate-2",
            "gate_state": "answered",
        },
    )
    _write_gate_done(gate_0_dir, gate_state="answered")
    make_agent(
        tmp_path,
        "proj",
        "20260827134403",
        "gate-lane--2",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--2",
        parent_timestamp=gate_0_dir.name,
        done=True,
        outcome="completed",
        extra_meta={
            "agent_clan": "gate-clan",
            "agent_clan_generation": root_dir.name,
        },
    )

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert index.is_resolved("gate-lane")
    assert dependency_resolution_status(
        index,
        [],
        [_identity_dep(root_dir, name="gate-lane")],
    ).resolved
    family = index.family_candidate("gate-lane")
    clan = index.clan_candidate("gate-clan")
    assert family is not None and family.is_resolved and family.is_done
    assert clan is not None and clan.is_resolved and clan.is_done


def test_pending_gate_member_does_not_resolve_from_workflow_state_fallback(
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
            "agent_clan": "gate-clan",
            "agent_clan_generation": root_dir.name,
            "gate_id": "gate-1",
            "gate_state": "answered",
        },
    )
    _write_completed_workflow_state(gate_dir)

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    gate_candidate = index.artifacts_by_dir[str(gate_dir)]
    assert gate_candidate.outcome is None
    assert not gate_candidate.is_resolved
    assert not index.is_resolved(gate_candidate.name)

    family = index.family_candidate("gate-lane")
    clan = index.clan_candidate("gate-clan")
    assert family is not None and not family.is_resolved and family.is_done
    assert clan is not None and not clan.is_resolved and not clan.is_failed
    assert index.terminal_blocking_artifacts_for_name("gate-lane") == ()
