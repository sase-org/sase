"""Plan-family wait_checks chop script tests."""

import json
import os
from pathlib import Path

import pytest

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import (
    make_waiting_agent,
    run_wait_checks,
    write_workflow_state,
)


def _identity_dep(artifact_dir: Path, *, name: str) -> dict[str, str]:
    return {
        "project_name": "proj",
        "timestamp": artifact_dir.name,
        "artifact_dir": str(artifact_dir),
        "name": name,
    }


def _write_waiting_marker(
    artifact_dir: Path,
    *waiting_for: str,
    wait_for_artifacts: list[dict[str, str]] | None = None,
) -> None:
    marker: dict[str, object] = {
        "waiting_for": list(waiting_for),
        "cl_name": "waiter-cl",
        "timestamp": artifact_dir.name,
    }
    if wait_for_artifacts is not None:
        marker["wait_for_artifacts"] = wait_for_artifacts
    (artifact_dir / "waiting.json").write_text(
        json.dumps(marker),
        encoding="utf-8",
    )


def _write_monitor_handoff(
    artifact_dir: Path,
    *,
    followup_outcome: str = "launched",
    followup_agent: str = "monitor-lane--1",
) -> None:
    meta_path = artifact_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.update(
        {
            "monitor_state": "timeout",
            "monitor_followup_outcome": followup_outcome,
            "monitor_followup_agent": followup_agent,
        }
    )
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    (artifact_dir / "done.json").write_text(
        json.dumps(
            {
                "outcome": "monitored",
                "monitor_state": "timeout",
                "monitor_followup_outcome": followup_outcome,
            }
        ),
        encoding="utf-8",
    )


def _monitor_handoff_wait_fixture(
    tmp_path: Path,
    *,
    followup_outcome: str = "launched",
    successor_outcome: str | None | bool = "completed",
) -> Path:
    waiter_dir = make_waiting_agent(tmp_path, "monitor-lane")
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
    _write_monitor_handoff(
        monitor_dir,
        followup_outcome=followup_outcome,
        followup_agent="monitor-lane--1",
    )
    if successor_outcome is not None:
        make_agent(
            tmp_path,
            "proj",
            "20260813090100",
            "monitor-lane--1",
            workflow_name="monitor-lane",
            agent_family="monitor-lane",
            role_suffix="--1",
            parent_timestamp=root_dir.name,
            done=isinstance(successor_outcome, str),
            outcome=successor_outcome if isinstance(successor_outcome, str) else None,
        )
    return waiter_dir


def test_successful_plan_family_dependency_resolves(
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
        outcome="completed",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planfam"]}


def test_completed_monitor_member_releases_plan_family_waiter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "monitor-lane")
    plan_dir = make_agent(
        tmp_path,
        "proj",
        "20260813080101",
        "monitor-lane--plan",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    code_dir = make_agent(
        tmp_path,
        "proj",
        "20260813080202",
        "monitor-lane--code",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--code",
        parent_timestamp=plan_dir.name,
        done=True,
        outcome="completed",
    )
    monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813080303",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=code_dir.name,
    )
    (monitor_dir / "done.json").write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["monitor-lane"]}


def test_running_monitor_member_keeps_plan_family_waiting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "monitor-lane")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813081111",
        "monitor-lane--code",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--code",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260813081212",
        "monitor-lane--mon",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=root_dir.name,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize("followup_outcome", ["launched", "launched-degraded"])
def test_wait_checks_monitor_handoff_successor_releases_plan_family(
    tmp_path: Path,
    monkeypatch,
    followup_outcome: str,
) -> None:
    waiter_dir = _monitor_handoff_wait_fixture(
        tmp_path,
        followup_outcome=followup_outcome,
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["monitor-lane"]}


@pytest.mark.parametrize("successor_outcome", [None, False, "failed"])
def test_wait_checks_monitor_handoff_waits_for_unresolved_successor(
    tmp_path: Path,
    monkeypatch,
    successor_outcome: str | None | bool,
) -> None:
    waiter_dir = _monitor_handoff_wait_fixture(
        tmp_path,
        successor_outcome=successor_outcome,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_running_sequential_grandchild_keeps_family_waiting(
    tmp_path: Path, monkeypatch
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "chain")
    make_agent(
        tmp_path,
        "proj",
        "20260701010101",
        "chain--plan",
        workflow_name="chain",
        agent_family="chain",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260701010202",
        "chain--plan-0",
        workflow_name="chain",
        agent_family="chain",
        role_suffix="--plan-0",
        parent_timestamp="20260701010101",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20260701010303",
        "chain--code",
        workflow_name="chain",
        agent_family="chain",
        role_suffix="--code",
        parent_timestamp="20260701010202",
        pid=os.getpid(),
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


def test_identity_wait_successful_plan_family_generation_resolves(
    tmp_path: Path, monkeypatch
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--plan",
    )
    write_workflow_state(root_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam--code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="completed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "planfam",
        wait_for_artifacts=[_identity_dep(root_dir, name="planfam")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["planfam"]}


def test_identity_wait_failed_plan_family_generation_keeps_waiting(
    tmp_path: Path, monkeypatch
) -> None:
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "planfam",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--plan",
    )
    write_workflow_state(root_dir)
    make_agent(
        tmp_path,
        "proj",
        "20260506010202",
        "planfam--code",
        workflow_name="planfam",
        agent_family="planfam",
        role_suffix="--code",
        parent_timestamp="20260506010101",
        done=True,
        outcome="failed",
    )
    waiter_dir = make_waiting_agent(
        tmp_path,
        "planfam",
        wait_for_artifacts=[_identity_dep(root_dir, name="planfam")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


@pytest.mark.parametrize("parent_has_family_meta", [False, True])
def test_queued_family_child_does_not_block_its_parent_dependency(
    tmp_path: Path,
    monkeypatch,
    parent_has_family_meta: bool,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        workflow_name="b" if parent_has_family_meta else None,
        agent_family="b" if parent_has_family_meta else None,
        done=True,
        outcome="completed",
    )
    child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
    )
    _write_waiting_marker(
        child_dir,
        "b",
        wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((child_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["b"]}


def test_queued_family_child_blocks_external_wait_on_whole_family(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b--plan",
        workflow_name="b",
        agent_family="b",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        role_suffix="--launch",
        parent_timestamp=parent_dir.name,
    )
    _write_waiting_marker(
        child_dir,
        "b",
        wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
    )
    external_waiter = make_waiting_agent(tmp_path, "b", suffix="external-waiter")

    run_wait_checks(tmp_path, monkeypatch)

    assert not (external_waiter / "ready.json").exists()


def test_queued_family_siblings_do_not_mutually_block_parent_dependency(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        done=True,
        outcome="completed",
    )
    first_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
    )
    second_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131105",
        "b--review",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
    )
    for child_dir in (first_child_dir, second_child_dir):
        _write_waiting_marker(
            child_dir,
            "b",
            wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
        )

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((first_child_dir / "ready.json").read_text()) == {
        "resolved_deps": ["b"]
    }
    assert json.loads((second_child_dir / "ready.json").read_text()) == {
        "resolved_deps": ["b"]
    }


def test_stale_waiting_marker_on_failed_family_member_keeps_waiting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    parent_dir = make_agent(
        tmp_path,
        "proj",
        "20260706130831",
        "b",
        workflow_name="b",
        agent_family="b",
        done=True,
        outcome="completed",
    )
    failed_child_dir = make_agent(
        tmp_path,
        "proj",
        "20260706131004",
        "b--launch",
        workflow_name="b",
        agent_family="b",
        parent_timestamp=parent_dir.name,
        done=True,
        outcome="killed",
    )
    _write_waiting_marker(failed_child_dir, "old-dep")
    waiter_dir = make_waiting_agent(
        tmp_path,
        "b",
        wait_for_artifacts=[_identity_dep(parent_dir, name="b")],
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()


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
