"""Wait-dependency semantics for gate family and clan members."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.dismissed_agent_completion import effective_done_outcome
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._dismissed_completion_helpers import (
    add_archive_identity,
    rebuild_completion_archive,
    write_dismissed_completion,
)

_MISSING = object()


def _identity_dep(artifact_dir: Path, *, name: str) -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _family_fork_source(root_dir: Path, *, name: str) -> dict[str, str]:
    return {**_identity_dep(root_dir, name=name), "kind": "family"}


def _update_meta(artifact_dir: Path, **updates: object) -> None:
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(updates)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")


def _write_gate_done(
    artifact_dir: Path,
    *,
    gate_state: object = "answered",
    followup_outcome: str | None = None,
    followup_agent: str | None = None,
) -> None:
    done: dict[str, object] = {"outcome": "gated"}
    if gate_state is not _MISSING:
        done["gate_state"] = gate_state
    if followup_outcome is not None:
        done["gate_followup_outcome"] = followup_outcome
    if followup_agent is not None:
        done["gate_followup_agent"] = followup_agent
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")


def _gate_member(
    tmp_path: Path,
    gate_state: object,
    *,
    with_done_marker: bool = True,
) -> Path:
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260827090000",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--gate",
        extra_meta={
            "agent_family_role": "gate",
            "agent_clan": "gate-clan",
            "agent_clan_generation": "20260827085900",
            "gate_id": "gate-1",
            "gate_state": "pending",
        },
    )
    if with_done_marker:
        _write_gate_done(artifact_dir, gate_state=gate_state)
    return artifact_dir


def _write_completed_workflow_state(artifact_dir: Path) -> None:
    (artifact_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "gate-lane",
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


def _gate_handoff_family(
    tmp_path: Path,
    *,
    gate_state: str = "timeout",
    followup_outcome: str | None = "launched",
    followup_agent: str | None = "gate-lane--1",
    successor_outcome: str | None | bool = "completed",
) -> tuple[Path, Path, Path | None]:
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
            "gate_state": gate_state,
            "gate_followup_outcome": followup_outcome,
            "gate_followup_agent": followup_agent,
        },
    )
    _write_gate_done(
        gate_dir,
        gate_state=gate_state,
        followup_outcome=followup_outcome,
        followup_agent=None,
    )

    successor_dir: Path | None = None
    if successor_outcome is not None:
        successor_dir = make_agent(
            tmp_path,
            "proj",
            "20260827090100",
            followup_agent or "gate-lane--1",
            workflow_name="gate-lane",
            agent_family="gate-lane",
            role_suffix="--1",
            parent_timestamp=gate_dir.name,
            done=isinstance(successor_outcome, str),
            outcome=successor_outcome if isinstance(successor_outcome, str) else None,
        )
    return root_dir, gate_dir, successor_dir


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


@pytest.mark.parametrize(
    ("gate_state", "expected"),
    [
        ("answered", "completed"),
        ("completed", "completed"),
        ("stopped", "completed"),
        ("failed", "failed"),
        ("timeout", "failed"),
        ("lost", "failed"),
        ("unknown", "failed"),
        (None, "failed"),
        ([], "failed"),
    ],
)
def test_effective_gate_outcome_fails_closed(
    gate_state: object,
    expected: str,
) -> None:
    assert effective_done_outcome({"outcome": "gated", "gate_state": gate_state}) == (
        expected
    )


def test_effective_gate_outcome_reads_nested_family_shell() -> None:
    assert (
        effective_done_outcome(
            {
                "outcome": "gated",
                "family_shell": {"kind": "gate", "state": "answered"},
            }
        )
        == "completed"
    )
    assert (
        effective_done_outcome(
            {
                "outcome": "gated",
                "family_shell": {"kind": "monitor", "state": "completed"},
            }
        )
        == "failed"
    )


@pytest.mark.parametrize(
    ("gate_state", "expected_resolved"),
    [("answered", True), ("completed", True), ("failed", False), (None, False)],
)
def test_archived_default_gate_status_uses_gate_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_state: str | None,
    expected_resolved: bool,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260827162000",
        "archived-gate",
    )
    add_archive_identity(artifact_dir)
    extra = {} if gate_state is None else {"gate_state": gate_state}
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "archived-gate",
        status="GATED",
        extra=extra,
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert index.is_resolved("archived-gate") is expected_resolved
    assert (
        dependency_resolution_status(
            index,
            [],
            [_identity_dep(artifact_dir, name="archived-gate")],
        ).resolved
        is expected_resolved
    )
    candidate = index.artifacts_by_dir[str(artifact_dir)]
    assert candidate.archived_completion is not None
    assert candidate.is_failed is (not expected_resolved)


def test_archived_custom_gate_stop_status_remains_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    artifact_dir = make_agent(
        tmp_path,
        "proj",
        "20260827162100",
        "archived-gate",
    )
    add_archive_identity(artifact_dir)
    write_dismissed_completion(
        tmp_path,
        artifact_dir,
        "archived-gate",
        status="REVIEWED",
        extra={"gate_stop_status": "REVIEWED", "gate_state": "answered"},
    )
    rebuild_completion_archive()

    index = build_wait_dependency_index(
        "proj",
        projects_root=tmp_path / ".sase/projects",
    )

    assert not index.is_resolved("archived-gate")
    assert index.artifacts_by_dir[str(artifact_dir)].archived_completion is None
