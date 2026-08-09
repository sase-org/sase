"""Focused tests for run-agent wait dependency helpers."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.axe.run_agent_wait_deps import (
    initial_dependencies_resolved,
    refresh_bead_wait_store,
    waiting_marker_dependencies_resolved,
)
from tests._agent_names_fixtures import make_agent
from tests._axe_chop_wait_checks_helpers import make_waiting_agent


def test_refresh_bead_wait_store_honors_off_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locate = MagicMock(return_value=tmp_path / "beads")
    refresh = MagicMock()
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "off")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        locate,
    )
    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", refresh)

    refresh_bead_wait_store("proj")

    locate.assert_not_called()
    refresh.assert_not_called()


def test_refresh_bead_wait_store_contains_refresh_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir = tmp_path / "beads"
    monkeypatch.setattr("sase.bead.sync.bead_refresh_mode", lambda: "background")
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    refresh = MagicMock(side_effect=RuntimeError("integration failed"))
    monkeypatch.setattr("sase.bead.sync.refresh_bead_store", refresh)

    refresh_bead_wait_store("proj")

    refresh.assert_called_once_with(beads_dir)


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
