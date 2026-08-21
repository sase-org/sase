"""Focused tests for run-agent wait dependency helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.axe.run_agent_wait_deps import (
    initial_dependencies_resolved,
    mark_bead_wait_sync_hint,
    waiting_marker_dependencies_resolved,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent, write_workflow_state


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
def test_waiting_marker_dependencies_resolved_matches_terminal_outcome_semantics(
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
        waiting_marker_dependencies_resolved(
            waiter_dir / "waiting.json",
            project_name="proj",
            artifacts_dir=str(waiter_dir),
        )
        is should_resolve
    )


def test_waiting_marker_fallback_resolves_non_monitor_completed_workflow_without_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    waiter_dir = make_waiting_agent(tmp_path, "handoff-lane")
    root_dir = make_agent(
        tmp_path,
        "proj",
        "20260813085800",
        "handoff-lane--plan",
        workflow_name="handoff-lane",
        agent_family="handoff-lane",
        role_suffix="--plan",
        done=True,
        outcome="completed",
    )
    child_dir = make_agent(
        tmp_path,
        "proj",
        "20260813090000",
        "handoff-lane--code",
        workflow_name="handoff-lane",
        agent_family="handoff-lane",
        role_suffix="--code",
        parent_timestamp=root_dir.name,
    )
    write_workflow_state(child_dir)

    assert waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )


def test_waiting_marker_fallback_waits_for_settled_monitor_without_terminal_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
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
        "monitor-lane--mon-0",
        workflow_name="monitor-lane",
        agent_family="monitor-lane",
        role_suffix="--mon-0",
        parent_timestamp=root_dir.name,
        extra_meta={"monitor_state": "completed"},
    )
    write_workflow_state(monitor_dir)

    assert not waiting_marker_dependencies_resolved(
        waiter_dir / "waiting.json",
        project_name="proj",
        artifacts_dir=str(waiter_dir),
    )
