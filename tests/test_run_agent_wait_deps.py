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
from tests._axe_chop_wait_checks_helpers import make_waiting_agent


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
