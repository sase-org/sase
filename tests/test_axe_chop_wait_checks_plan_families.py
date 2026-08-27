"""Core plan-family wait_checks chop script tests."""

import json
import os
from pathlib import Path

import pytest

from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, run_wait_checks


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


def _write_gate_done(artifact_dir: Path, *, gate_state: str = "answered") -> None:
    (artifact_dir / "done.json").write_text(
        json.dumps({"outcome": "gated", "gate_state": gate_state}),
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


def test_settled_gate_member_releases_plan_family_waiter_without_unknown_log(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    waiter_dir = make_waiting_agent(tmp_path, "gate-lane")
    plan_dir = make_agent(
        tmp_path,
        "proj",
        "20260827080101",
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
        "20260827080202",
        "gate-lane--gate",
        workflow_name="gate-lane",
        agent_family="gate-lane",
        role_suffix="--gate",
        parent_timestamp=plan_dir.name,
        extra_meta={
            "agent_family_role": "gate",
            "gate_id": "gate-1",
            "gate_state": "answered",
        },
    )
    _write_gate_done(gate_dir)

    run_wait_checks(tmp_path, monkeypatch)

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["gate-lane"]}
    out = capsys.readouterr().out
    assert "Unknown done outcome blocks waiter" not in out
    assert "unknown_outcome=0" in out


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
