"""Initial wait-dependency resolution tests for run-agent waits.

Split from ``tests.test_run_agent_wait_deps``; the original module re-exports
these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import sase.bead.store_locator as bead_store_locator
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.core.wait_dependency_resolution import WaitDependencyIndex
from sase.axe.run_agent_wait_deps import (
    initial_dependencies_resolved,
    mark_bead_wait_sync_hint,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent
from tests._monitor_wait_dependency_helpers import (
    monitor_handoff_agent_session,
    write_completed_workflow_state,
)
from tests.test_bead.resolution_test_helpers import bead_store_snapshot

__all__ = [
    "test_initial_dependencies_resolved_matches_terminal_outcome_semantics",
    "test_initial_dependencies_resolved_routes_full_bead_wait_to_owner_project",
    "test_initial_dependencies_resolved_uses_cross_project_stored_job_identity",
    "test_mark_bead_wait_sync_hint_contains_hint_failures",
    "test_mark_bead_wait_sync_hint_honors_off_mode",
    "test_mark_bead_wait_sync_hint_marks_the_beads_role",
    "test_runner_confirmation_rejects_stale_agent_session_then_accepts_complete_agent_session",
    "test_runner_fallback_confirmation_failure_warns_and_stays_parked",
    "test_runner_fallback_index_failure_warns_and_stays_parked",
]


def _wait_index(*artifact_dirs: Path) -> WaitDependencyIndex:
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


def test_mark_bead_wait_sync_hint_honors_off_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mark = MagicMock()
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "off")
    monkeypatch.setattr("sase._sidecar_sync_hints.mark_sidecar_sync_hint", mark)

    mark_bead_wait_sync_hint("proj")

    mark.assert_not_called()


def test_mark_bead_wait_sync_hint_marks_the_beads_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "background")
    mark = MagicMock()
    monkeypatch.setattr("sase._sidecar_sync_hints.mark_sidecar_sync_hint", mark)

    mark_bead_wait_sync_hint("proj")

    mark.assert_called_once_with("proj", "beads")


def test_mark_bead_wait_sync_hint_contains_hint_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "background")
    monkeypatch.setattr(
        "sase._sidecar_sync_hints.mark_sidecar_sync_hint",
        MagicMock(side_effect=RuntimeError("disk full")),
    )

    mark_bead_wait_sync_hint("proj")  # must not raise


@pytest.mark.parametrize(
    ("outcome", "should_resolve"),
    [
        ("completed", True),
        ("noop", True),
        ("epic_approved", True),
        ("plan_committed", True),
        ("failed", False),
        ("killed", False),
        ("stopped", False),
        ("epic_launch_failed", False),
        ("plan_rejected", False),
    ],
)
def test_initial_dependencies_resolved_matches_terminal_outcome_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    should_resolve: bool,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "foo")
    make_agent(
        tmp_path,
        "proj",
        "20260506010101",
        "foo",
        done=True,
        outcome=outcome,
    )

    assert (
        initial_dependencies_resolved(
            ["foo"],
            [],
            project_name="proj",
            artifacts_dir=str(waiter_dir),
        )
        is should_resolve
    )


def test_runner_confirmation_rejects_stale_agent_session_then_accepts_complete_agent_session(
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
    stale = _wait_index(root_dir, monitor_dir, handoff_dir)
    fresh = _wait_index(root_dir, monitor_dir, handoff_dir, next_monitor_dir)
    indexes = iter((stale, fresh))
    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.build_wait_dependency_index",
        lambda _project: next(indexes),
    )

    assert not initial_dependencies_resolved(
        ["monitor-lane"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )

    (next_monitor_dir / "done.json").write_text(
        json.dumps({"outcome": "monitored", "monitor_state": "completed"}),
        encoding="utf-8",
    )
    complete = _wait_index(root_dir, monitor_dir, handoff_dir, next_monitor_dir)
    complete_indexes = iter((complete, complete))
    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.build_wait_dependency_index",
        lambda _project: next(complete_indexes),
    )

    assert initial_dependencies_resolved(
        ["monitor-lane"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_initial_dependencies_resolved_uses_cross_project_stored_job_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner's single-project fast path must not alias-collapse ``@job``.

    An independent ``job`` identity assigned in a different project is
    reachable only through the cross-project assignment store, not this
    project's own artifacts. Without that shared evidence, ``@job`` falls
    back to the built-in ``chop`` alias and incorrectly binds to this
    project's own later ``chop``-tribe agent.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "@job", suffix="20260506010000")
    make_agent(
        tmp_path,
        "proj",
        "20260506020000",
        "built-in",
        done=True,
        outcome="completed",
        extra_meta={"tribe": "chop"},
    )
    make_agent(
        tmp_path,
        "other-project",
        "20260506015000",
        "independent-job",
        done=True,
        outcome="completed",
        extra_meta={"tribe": "job"},
    )
    tribes_path = tmp_path / ".sase" / "agent_tribes.json"
    tribes_path.parent.mkdir(parents=True, exist_ok=True)
    tribes_path.write_text(
        json.dumps(
            [
                {
                    "id": ["run", "independent-job", "20260506015000"],
                    "tribe": "job",
                }
            ]
        ),
        encoding="utf-8",
    )

    assert not initial_dependencies_resolved(
        ["@job"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_initial_dependencies_resolved_routes_full_bead_wait_to_owner_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_root = tmp_path / "local"
    owner_root = tmp_path / "owner"
    with BeadProject.init(local_root):
        pass
    with BeadProject.init(owner_root) as project:
        open_bead = project.create("Open", IssueType.PLAN)
        closed_bead = project.create("Closed", IssueType.PLAN)
        project.close([closed_bead.id])

    def beads_dir_for(project: str) -> Path | None:
        if project == "proj":
            return local_root / "sdd/beads"
        if project == "owner":
            return owner_root / "sdd/beads"
        return None

    hints: list[str | None] = []
    monkeypatch.setattr(
        bead_store_locator, "canonical_beads_dir_for_project", beads_dir_for
    )
    monkeypatch.setattr(
        "sase.bead.wait_status.enabled_project_store_snapshots",
        lambda: (
            bead_store_snapshot("owner", owner_root, open_bead.id, closed_bead.id),
        ),
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.build_wait_dependency_index",
        lambda _project: WaitDependencyIndex.empty(),
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.mark_bead_wait_sync_hint",
        lambda project: hints.append(project),
    )

    assert not initial_dependencies_resolved(
        [],
        [],
        wait_beads=[open_bead.id],
        project_name="proj",
        artifacts_dir=str(tmp_path),
    )
    assert initial_dependencies_resolved(
        [],
        [],
        wait_beads=[closed_bead.id],
        project_name="proj",
        artifacts_dir=str(tmp_path),
    )
    assert "owner" in hints


def test_runner_fallback_confirmation_failure_warns_and_stays_parked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("confirm exploded")

    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.confirm_dependency_resolution", _boom
    )

    assert not initial_dependencies_resolved(
        ["foo"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    out = capsys.readouterr().out
    assert "Wait dependency check failed (confirmation)" in out
    assert "RuntimeError" in out
    assert "staying parked" in out


def test_runner_fallback_index_failure_warns_and_stays_parked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
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

    def _boom(_project: str) -> object:
        raise RuntimeError("index exploded")

    monkeypatch.setattr(
        "sase.axe.run_agent_wait_deps.build_wait_dependency_index", _boom
    )

    assert not initial_dependencies_resolved(
        ["foo"],
        [],
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
    out = capsys.readouterr().out
    assert "Wait dependency check failed (index)" in out
    assert "staying parked" in out
