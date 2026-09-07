"""Stale retry-descendant assignee classification for bead-work relaunch."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.names import claim_registered_name
from sase.bead.cli_work_cleanup_apply import revalidate_bead_work_launch_selection
from sase.bead.cli_work_cleanup_selection import select_bead_work_launch
from sase.bead.cli_work_cleanup_types import BeadWorkLaunchSelection, BeadWorkSlot

from .cli_work_helpers import seed_task, write_bead_agent_meta

OWNER = "sase-x7.4"
DEAD_RETRY = "sase-x7.4.r0.r0"
LIVE_RETRY = "sase-x7.4.r0"
ANCESTOR = "sase-x7"
FOREIGN = "unrelated-agent"


def _slot(name: str, *, launch_name: str | None = None) -> BeadWorkSlot:
    return BeadWorkSlot(
        slot_id=name,
        owner_name=name,
        expected_bead_id=name,
        launch_name=name if launch_name is None else launch_name,
    )


def _isolate_home(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake_home = project_dir / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


def _claim_failed_owner(home: Path, name: str, *, bead_id: str) -> Path:
    artifact_dir = write_bead_agent_meta(home, name, bead_id=bead_id, done=True)
    claim_registered_name(name, artifact_dir, replace_existing=True)
    return artifact_dir


def _mismatch_detail(bead_id: str, assignee: str, owner_name: str) -> str:
    return (
        f"bead {bead_id} is assigned to {assignee}, which does "
        f"not match the relaunch owner {owner_name}"
    )


def _select(name: str, assignee: str) -> BeadWorkLaunchSelection:
    return select_bead_work_launch(
        slots=(_slot(name),),
        bead_assignees={name: assignee},
    )


def test_dead_retry_descendant_assignee_is_compatible(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _isolate_home(project_dir, monkeypatch)
    _claim_failed_owner(home, OWNER, bead_id=OWNER)
    write_bead_agent_meta(home, DEAD_RETRY, bead_id=OWNER, done=True)

    selection = _select(OWNER, DEAD_RETRY)

    assert selection.blocked_targets == ()
    assert OWNER in selection.launch_names
    removed = [target for target in selection.targets if target.action == "REMOVE"]
    assert [target.name for target in removed] == [OWNER]


def test_missing_retry_descendant_record_is_compatible(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _isolate_home(project_dir, monkeypatch)
    _claim_failed_owner(home, OWNER, bead_id=OWNER)

    selection = _select(OWNER, DEAD_RETRY)

    assert selection.blocked_targets == ()
    assert OWNER in selection.launch_names
    assert any(
        target.action == "REMOVE" and target.name == OWNER
        for target in selection.targets
    )


def test_live_retry_descendant_assignee_is_preserved(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _isolate_home(project_dir, monkeypatch)
    _claim_failed_owner(home, OWNER, bead_id=OWNER)
    write_bead_agent_meta(home, LIVE_RETRY, bead_id=OWNER)

    selection = _select(OWNER, LIVE_RETRY)

    assert selection.blocked_targets == ()
    assert OWNER not in selection.launch_names
    preserved = [target for target in selection.targets if target.preserved]
    assert preserved
    assert preserved[0].name == OWNER
    assert preserved[0].detail == f"live retry {LIVE_RETRY} is working bead {OWNER}"


def test_foreign_assignee_stays_blocked(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _isolate_home(project_dir, monkeypatch)
    _claim_failed_owner(home, OWNER, bead_id=OWNER)

    selection = _select(OWNER, FOREIGN)

    assert [target.detail for target in selection.blocked_targets] == [
        _mismatch_detail(OWNER, FOREIGN, OWNER)
    ]
    assert selection.launch_names == frozenset()


def test_ancestor_assignee_stays_blocked(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _isolate_home(project_dir, monkeypatch)
    _claim_failed_owner(home, OWNER, bead_id=OWNER)

    selection = _select(OWNER, ANCESTOR)

    assert [target.detail for target in selection.blocked_targets] == [
        _mismatch_detail(OWNER, ANCESTOR, OWNER)
    ]
    assert selection.launch_names == frozenset()


def test_task_slot_dead_retry_assignee_is_compatible(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = seed_task(project_dir)
    retry_name = f"{task_id}.r0"
    home = _isolate_home(project_dir, monkeypatch)
    _claim_failed_owner(home, task_id, bead_id=task_id)
    write_bead_agent_meta(home, retry_name, bead_id=task_id, done=True)

    selection = select_bead_work_launch(
        slots=(_slot(task_id, launch_name=task_id),),
        bead_assignees={task_id: retry_name},
    )

    assert selection.blocked_targets == ()
    assert task_id in selection.launch_names
    assert any(
        target.action == "REMOVE" and target.name == task_id
        for target in selection.targets
    )


def test_dead_retry_assignee_revalidates_when_unchanged(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _isolate_home(project_dir, monkeypatch)
    _claim_failed_owner(home, OWNER, bead_id=OWNER)
    write_bead_agent_meta(home, DEAD_RETRY, bead_id=OWNER, done=True)
    assignees = {OWNER: DEAD_RETRY}
    previous = select_bead_work_launch(
        slots=(_slot(OWNER),),
        bead_assignees=assignees,
    )

    current = revalidate_bead_work_launch_selection(previous, bead_assignees=assignees)

    assert current.blocked_targets == ()
    assert current.launch_names == previous.launch_names
    assert [target.action for target in current.targets] == [
        target.action for target in previous.targets
    ]
