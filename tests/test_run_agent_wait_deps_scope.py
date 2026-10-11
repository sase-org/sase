"""Runner startup/fallback wait views stay scoped for named waits."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.axe.run_agent_wait_deps import (
    resolve_initial_wait_release,
    waiting_marker_dependencies_resolved,
)
from sase.core.wait_dependency_resolution import (
    WaitDependencyIndex,
    build_wait_dependency_index,
    resolve_wait_release,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent
from tests._monitor_wait_dependency_helpers import (
    monitor_handoff_agent_session,
    write_completed_workflow_state,
)


def _full_runner_decision(
    marker: dict[str, object],
    waiter_dir: Path,
    *,
    project_name: str = "proj",
) -> object:
    def build_index() -> WaitDependencyIndex:
        return build_wait_dependency_index(project_name)

    return resolve_wait_release(
        build_index(),
        marker,
        waiter_dir=waiter_dir,
        closed_bead_ids=frozenset(),
        now=1_800_000_000.0,
        fresh_index=build_index,
    )


def _assert_scoped_matches_full(
    wait_names: list[str],
    waiter_dir: Path,
) -> None:
    marker: dict[str, object] = {"waiting_for": wait_names}
    scoped = resolve_initial_wait_release(
        wait_names,
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    full = _full_runner_decision(marker, waiter_dir)
    assert (
        scoped.status.resolved,
        scoped.status.blocked_on,
        scoped.releasable,
        scoped.confirmation_failed,
    ) == (
        full.status.resolved,
        full.status.blocked_on,
        full.releasable,
        full.confirmation_failed,
    )


def test_runner_scoped_named_wait_matches_full_handoff_followup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "monitor-lane")
    root_dir, monitor_dir, handoff_dir = monitor_handoff_agent_session(
        tmp_path,
        successor_outcome=False,
    )
    assert handoff_dir is not None
    write_completed_workflow_state(handoff_dir)
    next_monitor_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090200",
        "monitor-lane--mon-0",
        workflow_name="monitor-lane",
        agent_session="monitor-lane",
        role_suffix="--mon",
        parent_timestamp=handoff_dir.name,
    )
    make_agent(tmp_path, "proj", "20261011010101", "unrelated")

    _assert_scoped_matches_full(["monitor-lane"], waiter_dir)
    assert not resolve_initial_wait_release(
        ["monitor-lane"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable

    (next_monitor_dir / "done.json").write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )
    _assert_scoped_matches_full(["monitor-lane"], waiter_dir)
    assert resolve_initial_wait_release(
        ["monitor-lane"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable
    assert root_dir.exists() and monitor_dir.exists()


def test_runner_scoped_named_wait_matches_full_newer_failed_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "newer-failure")
    make_agent(
        tmp_path,
        "proj",
        "20261011020701",
        "newer-failure",
        done=True,
        outcome="completed",
    )
    make_agent(
        tmp_path,
        "proj",
        "20261011020702",
        "newer-failure",
        done=True,
        outcome="failed",
    )
    make_agent(tmp_path, "proj", "20261011020703", "unrelated")

    _assert_scoped_matches_full(["newer-failure"], waiter_dir)
    assert not resolve_initial_wait_release(
        ["newer-failure"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable


def test_runner_unscopable_marker_calls_full_project_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "@job")
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    resolve_initial_wait_release(
        ["@job"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    assert spy.call_args_list
    assert all(call.args == ("proj",) for call in spy.call_args_list)


def test_runner_scopable_named_wait_skips_full_project_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    assert resolve_initial_wait_release(
        ["foo"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    ).releasable
    spy.assert_not_called()


def test_runner_identity_dep_keeps_full_project_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    resolve_initial_wait_release(
        [],
        [
            {
                "name": "foo",
                "project_name": "proj",
                "timestamp": "20260506010101",
                "artifact_dir": str(tmp_path / "missing"),
            }
        ],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    spy.assert_called()


def test_waiting_marker_fallback_scopes_satisfied_at_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome="completed",
    )
    spy = MagicMock(return_value=WaitDependencyIndex.empty())
    monkeypatch.setattr("sase.axe.run_agent_wait_deps.build_wait_dependency_index", spy)

    assert waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    spy.assert_not_called()
