"""Release confirmation for waits whose aggregate membership can change live."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    confirm_dependency_resolution,
    dependency_resolution_status,
)
from tests._agent_names_fixtures import make_agent
from tests._monitor_wait_dependency_helpers import (
    _update_meta,
    _write_completed_workflow_state,
    _write_monitor_done,
)


def _index(*artifact_dirs: Path) -> WaitDependencyIndex:
    index = WaitDependencyIndex.empty()
    index.add_many(
        (
            artifact_dir,
            json.loads((artifact_dir / "agent_meta.json").read_text(encoding="utf-8")),
            "proj",
        )
        for artifact_dir in artifact_dirs
    )
    return index


def _stale_handoff_agent_session(tmp_path: Path) -> tuple[Path, list[Path]]:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090000",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    code_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090100",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="completed",
    )
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090200",
        "lane--mon",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )
    _update_meta(
        monitor_dir,
        monitor_state="failed",
        monitor_followup_outcome="launched",
        monitor_followup_agent="lane--1",
    )
    _write_monitor_done(
        monitor_dir,
        monitor_state="failed",
        followup_outcome="launched",
        followup_agent="lane--1",
    )
    handoff_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090300",
        "lane--1",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--1",
        parent_timestamp=root_dir.name,
    )
    _write_completed_workflow_state(handoff_dir)
    next_monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260924090400",
        "lane--mon-0",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--mon",
        parent_timestamp=handoff_dir.name,
    )
    return root_dir, [
        root_dir,
        code_dir,
        monitor_dir,
        handoff_dir,
        next_monitor_dir,
    ]


def test_stale_agent_session_membership_defers_release_against_live_successor(
    tmp_path: Path,
) -> None:
    _root_dir, artifacts = _stale_handoff_agent_session(tmp_path)
    stale = _index(*artifacts[:-1])
    fresh = _index(*artifacts)

    assert dependency_resolution_status(stale, ["lane"]).resolved
    confirmation = confirm_dependency_resolution(stale, lambda: fresh, ["lane"])

    assert not confirmation.confirmed
    assert confirmation.status.blocked_on == ("lane",)


def test_completed_agent_session_is_confirmed_with_one_fresh_build(
    tmp_path: Path,
) -> None:
    _root_dir, artifacts = _stale_handoff_agent_session(tmp_path)
    (artifacts[-1] / "done.json").write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )
    complete = _index(*artifacts)
    fresh = Mock(return_value=complete)

    confirmation = confirm_dependency_resolution(complete, fresh, ["lane"])

    assert confirmation.confirmed
    assert fresh.call_count == 1


def test_confirmation_retries_once_when_a_resolved_member_appears(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260924100000",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    first_child = make_agent(
        tmp_path,
        "proj",
        "20260924100100",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="completed",
    )
    stale = _index(root_dir)
    fresh = _index(root_dir, first_child)
    factory = Mock(return_value=fresh)

    confirmation = confirm_dependency_resolution(stale, factory, ["lane"])

    assert confirmation.confirmed
    assert factory.call_count == 2


def test_confirmation_defers_when_each_round_finds_another_member(
    tmp_path: Path,
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260924110000",
        "lane--plan",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    child_one = make_agent(
        tmp_path,
        "proj",
        "20260924110100",
        "lane--code",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="completed",
    )
    child_two = make_agent(
        tmp_path,
        "proj",
        "20260924110200",
        "lane--review",
        workflow_name="lane",
        agent_session="lane",
        role_suffix="--review",
        parent_timestamp=root_dir.name,
        done=True,
        outcome="completed",
    )
    stale = _index(root_dir)
    fresh_one = _index(root_dir, child_one)
    fresh_two = _index(root_dir, child_one, child_two)
    factory = Mock(side_effect=[fresh_one, fresh_two])

    confirmation = confirm_dependency_resolution(stale, factory, ["lane"])

    assert not confirmation.confirmed
    assert confirmation.new_member_dirs == (str(child_two.resolve()),)
    assert factory.call_count == 2


def test_bead_and_time_only_waits_skip_the_fresh_factory() -> None:
    index = WaitDependencyIndex.empty()
    fresh = Mock(side_effect=AssertionError("factory must not be called"))

    bead_confirmation = confirm_dependency_resolution(
        index,
        fresh,
        [],
        wait_beads=["closed"],
        closed_bead_ids={"closed"},
    )
    time_confirmation = confirm_dependency_resolution(index, fresh, [])

    assert bead_confirmation.confirmed
    assert time_confirmation.confirmed
    assert fresh.call_count == 0


def test_identity_and_hood_waits_defer_on_stale_membership(tmp_path: Path) -> None:
    root_dir, artifacts = _stale_handoff_agent_session(tmp_path)
    stale = _index(*artifacts[:-1])
    fresh = _index(*artifacts)

    identity_confirmation = confirm_dependency_resolution(
        stale,
        lambda: fresh,
        [],
        [
            {
                "project_name": "proj",
                "timestamp": root_dir.name,
                "artifact_dir": str(root_dir),
                "name": "lane",
            }
        ],
    )

    hood_done = make_agent(
        tmp_path,
        "proj",
        "20260924120000",
        "research.done",
        done=True,
        outcome="completed",
    )
    hood_live = make_agent(
        tmp_path,
        "proj",
        "20260924120100",
        "research.live",
    )
    hood_stale = _index(hood_done)
    hood_fresh = _index(hood_done, hood_live)
    hood_confirmation = confirm_dependency_resolution(
        hood_stale,
        lambda: hood_fresh,
        [],
        wait_hoods=["research"],
        self_artifact_dir=tmp_path / "waiter" / "20260924130000",
    )

    assert not identity_confirmation.confirmed
    assert not hood_confirmation.confirmed
    assert hood_confirmation.status.blocked_on == ("hood=research",)
