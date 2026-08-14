"""Plan-family handoff wait_checks chop script tests."""

import json
from pathlib import Path

import pytest

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import (
    make_waiting_agent,
    run_wait_checks,
    write_workflow_state,
)


def test_completed_plan_chain_handoff_without_done_resolves_family_dependency(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "33.r1")
    make_agent(
        tmp_path,
        "proj",
        "20260606094012",
        "33.r1",
        workflow_name="33.r1",
        agent_family="33.r1",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "33.r1--2",
        workflow_name="33.r1",
        agent_family="33.r1",
        role_suffix="--2",
        parent_timestamp="20260606094012",
    )
    write_workflow_state(feedback_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260606100411",
        "33.r1--code",
        workflow_name="33.r1",
        agent_family="33.r1",
        role_suffix="--code",
        parent_timestamp="20260606094012",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["33.r1"]}


def test_completed_plan_root_handoff_without_done_does_not_resolve(
    tmp_path: Path, monkeypatch
) -> None:
    # A `--plan` root that merely completed its handoff (completed
    # workflow_state.json, no terminal done.json anywhere in the family) must
    # not resolve the wait barrier: the plan chain is still in flight.
    waiter_dir = make_waiting_agent(tmp_path, "3j")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260607083133",
        "3j",
        workflow_name="3j",
        agent_family="3j",
        role_suffix="--plan",
    )
    write_workflow_state(root_dir)

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize("outcome", ["failed", "killed"])
def test_failed_or_killed_plan_chain_handoff_done_blocks_family_dependency(
    tmp_path: Path, monkeypatch, outcome: str
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260606094012",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "planfam--2",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--2",
        parent_timestamp="20260606094012",
        done=True,
        outcome=outcome,
    )
    write_workflow_state(feedback_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260606100411",
        "planfam--code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--code",
        parent_timestamp="20260606094012",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize(
    ("workflow_status", "step_status", "marker_status"),
    [
        ("running", "completed", "completed"),
        ("completed", "in_progress", "in_progress"),
    ],
)
def test_incomplete_plan_chain_handoff_blocks_family_dependency(
    tmp_path: Path,
    monkeypatch,
    workflow_status: str,
    step_status: str,
    marker_status: str,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260606094012",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "planfam--2",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--2",
        parent_timestamp="20260606094012",
    )
    write_workflow_state(
        feedback_dir,
        status=workflow_status,
        step_status=step_status,
        marker_status=marker_status,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_failed_latest_plan_family_child_blocks_dependency(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam-code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="failed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_killed_latest_plan_family_child_blocks_dependency(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "planfam")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam-code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="-code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="killed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_legacy_dot_plan_family_dependency_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "legacy")
    make_agent(
        tmp_path,
        "proj",
        "20260406010101",
        "legacy.plan",
        workflow_name="legacy",
        role_suffix=".plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260406010202",
        "legacy.code",
        workflow_name="legacy",
        role_suffix=".code",
        parent_timestamp="20260406010101",
        done=True,
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["legacy"]}
