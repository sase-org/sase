"""Plan-family handoff wait_checks chop script tests."""

import json
from pathlib import Path

import pytest

import sase.scripts.sase_chop_wait_checks as wait_checks
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import (
    make_waiting_agent,
    run_wait_checks,
    write_workflow_state,
)
from tests._monitor_wait_dependency_helpers import _update_meta, _write_monitor_done


def _stale_index_handoff_wait_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create the handoff window where cached membership misses ``--mon-0``."""
    waiter_dir = make_waiting_agent(tmp_path, "lane")
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
    make_agent(
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
    write_workflow_state(handoff_dir)
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
    return waiter_dir, next_monitor_dir


def test_stale_index_membership_defers_family_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    waiter_dir, next_monitor_dir = _stale_index_handoff_wait_fixture(tmp_path)
    all_rows = wait_checks._filesystem_dependency_rows(tmp_path / ".sase/projects")
    stale_rows = [row for row in all_rows if row[0] != next_monitor_dir]
    monkeypatch.setattr(
        wait_checks, "query_ace_run_index_records", lambda _root: [object()]
    )
    monkeypatch.setattr(
        wait_checks,
        "wait_rows_from_index_records",
        lambda _records: stale_rows,
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert not (waiter_dir / "ready.json").exists()
    out = capsys.readouterr().out
    assert "deferred_unconfirmed=1" in out
    assert "Deferred release for waiter-cl" in out


def test_complete_index_membership_still_releases_family_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waiter_dir, next_monitor_dir = _stale_index_handoff_wait_fixture(tmp_path)
    (next_monitor_dir / "done.json").write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )
    rows = wait_checks._filesystem_dependency_rows(tmp_path / ".sase/projects")
    monkeypatch.setattr(
        wait_checks, "query_ace_run_index_records", lambda _root: [object()]
    )
    monkeypatch.setattr(
        wait_checks, "wait_rows_from_index_records", lambda _records: rows
    )

    run_wait_checks(tmp_path, monkeypatch)

    assert json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8")) == {
        "resolved_deps": ["lane"]
    }


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
        agent_session="33.r1",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "33.r1--2",
        workflow_name="33.r1",
        agent_session="33.r1",
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
        agent_session="33.r1",
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
        agent_session="3j",
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
        agent_session="planfam",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "planfam--2",
        workflow_name="planfam",
        agent_session="planfam",
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
        agent_session="planfam",
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
        agent_session="planfam",
        done=True,
        outcome="completed",
    )
    feedback_dir = make_agent(
        tmp_path,
        "proj",
        "20260606095139",
        "planfam--2",
        workflow_name="planfam",
        agent_session="planfam",
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
        agent_session="planfam",
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
        agent_session="planfam",
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
        agent_session="planfam",
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
        agent_session="planfam",
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
