"""Host-side effects of the BeadStaleCleanup close decision."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.bead._stale_cleanup_gate_response import BeadStaleCleanupResponse
from sase.bead._stale_cleanup_gate_spec import BEAD_STALE_CLEANUP_CLOSE_REASON
from sase.bead.stale_cleanup_gate import close_bead_stale_cleanup
from sase.notification_gates.models import GateError


def _mutation_double(closed_ids: list[str]) -> tuple[MagicMock, Any]:
    """Return a bead-store mutation double for one project's close call."""
    project = MagicMock()
    project.last_mutation_outcome = {
        "closed_ids": closed_ids,
        "already_closed_ids": [],
        "noted_ids": [],
        "cascade_closed_ids": [],
    }
    mutation = SimpleNamespace(project=project, commit=MagicMock())
    return project, mutation


def _response(**overrides: Any) -> BeadStaleCleanupResponse:
    fields: dict[str, Any] = {
        "beads": (("sase", "sase-task.1"),),
        "feedback": None,
        "source": "tui",
    }
    fields.update(overrides)
    return BeadStaleCleanupResponse(**fields)


def test_close_bead_stale_cleanup_closes_default_selection_as_canceled() -> None:
    project, mutation = _mutation_double(["sase-task.1"])

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit, cwd
        yield mutation

    with (
        patch(
            "sase.bead._stale_cleanup_gate_actions._resolve_stale_cleanup_project_cwd",
            return_value=Path("/checkouts/sase"),
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=mutation_scope,
        ),
    ):
        close_bead_stale_cleanup(_response())

    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason=BEAD_STALE_CLEANUP_CLOSE_REASON,
        resolution="canceled",
    )
    mutation.commit.assert_called_once_with("chore(beads): close sase-task.1")


def test_close_bead_stale_cleanup_uses_reviewer_note_as_reason() -> None:
    project, mutation = _mutation_double(["sase-task.1"])

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit, cwd
        yield mutation

    with (
        patch(
            "sase.bead._stale_cleanup_gate_actions._resolve_stale_cleanup_project_cwd",
            return_value=Path("/checkouts/sase"),
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=mutation_scope,
        ),
    ):
        close_bead_stale_cleanup(_response(feedback="too noisy to keep triaging"))

    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason="too noisy to keep triaging",
        resolution="canceled",
    )


def test_close_bead_stale_cleanup_requires_at_least_one_selected_bead() -> None:
    with pytest.raises(GateError) as exc_info:
        close_bead_stale_cleanup(_response(beads=()))

    assert exc_info.value.code == "invalid_stale_cleanup_action"


def test_close_bead_stale_cleanup_spanning_two_projects_produces_two_commits() -> None:
    sase_project, sase_mutation = _mutation_double(["sase-task.1", "sase-task.2"])
    athena_project, athena_mutation = _mutation_double(["athena-task.9"])
    mutations_by_cwd = {
        Path("/checkouts/sase"): sase_mutation,
        Path("/checkouts/athena"): athena_mutation,
    }
    cwds_by_project = {
        "sase": Path("/checkouts/sase"),
        "athena": Path("/checkouts/athena"),
    }
    observed_cwds: list[Path] = []

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit
        observed_cwds.append(cwd)
        yield mutations_by_cwd[cwd]

    with (
        patch(
            "sase.bead._stale_cleanup_gate_actions._resolve_stale_cleanup_project_cwd",
            side_effect=lambda project: cwds_by_project[project],
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=mutation_scope,
        ),
    ):
        close_bead_stale_cleanup(
            _response(
                beads=(
                    ("sase", "sase-task.1"),
                    ("athena", "athena-task.9"),
                    ("sase", "sase-task.2"),
                )
            )
        )

    # Sorted project order makes a partial failure deterministic.
    assert observed_cwds == [Path("/checkouts/athena"), Path("/checkouts/sase")]
    athena_project.close.assert_called_once_with(
        ["athena-task.9"],
        reason=BEAD_STALE_CLEANUP_CLOSE_REASON,
        resolution="canceled",
    )
    sase_project.close.assert_called_once_with(
        ["sase-task.1", "sase-task.2"],
        reason=BEAD_STALE_CLEANUP_CLOSE_REASON,
        resolution="canceled",
    )
    athena_mutation.commit.assert_called_once()
    sase_mutation.commit.assert_called_once()


def test_close_bead_stale_cleanup_unresolvable_project_keeps_earlier_commits() -> None:
    athena_project, athena_mutation = _mutation_double(["athena-task.9"])

    def resolve_cwd(project: str) -> Path:
        if project == "sase":
            raise GateError(
                "invalid_stale_cleanup_project", "payload.project", "no checkout"
            )
        return Path("/checkouts/athena")

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit, cwd
        yield athena_mutation

    with (
        patch(
            "sase.bead._stale_cleanup_gate_actions._resolve_stale_cleanup_project_cwd",
            side_effect=resolve_cwd,
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=mutation_scope,
        ),
        pytest.raises(GateError) as exc_info,
    ):
        close_bead_stale_cleanup(
            _response(
                beads=(
                    ("athena", "athena-task.9"),
                    ("sase", "sase-task.1"),
                )
            )
        )

    assert exc_info.value.code == "invalid_stale_cleanup_project"
    athena_project.close.assert_called_once_with(
        ["athena-task.9"],
        reason=BEAD_STALE_CLEANUP_CLOSE_REASON,
        resolution="canceled",
    )
    athena_mutation.commit.assert_called_once()


def test_resolve_stale_cleanup_project_cwd_wraps_lookup_failures() -> None:
    from sase.bead._stale_cleanup_gate_actions import (
        _resolve_stale_cleanup_project_cwd,
    )

    with patch(
        "sase.bead.task_launch.resolve_task_launch_cwd_for_project",
        side_effect=FileNotFoundError("missing project file"),
    ):
        with pytest.raises(GateError) as exc_info:
            _resolve_stale_cleanup_project_cwd("missing")

    assert exc_info.value.code == "invalid_stale_cleanup_project"
