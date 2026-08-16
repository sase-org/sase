"""Host-side effects of the four FlagTriage decision branches."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.bead._flag_gate_response import FlagTriageResponse
from sase.bead.flag_gate import (
    close_flag_triage,
    extend_flag_triage,
    keep_flag_triage,
    remove_flag_triage,
)
from sase.notification_gates.models import GateError


def _mutation_double() -> tuple[MagicMock, Any, Any]:
    """Return a bead-store mutation double and the scope that yields it."""
    project = MagicMock()
    project.owner = "owner@example"
    project.last_mutation_outcome = {
        "closed_ids": ["sase-flag.1"],
        "already_closed_ids": [],
        "noted_ids": [],
        "cascade_closed_ids": [],
    }
    mutation = SimpleNamespace(project=project, commit=MagicMock())

    @contextmanager
    def mutation_scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit, cwd
        yield mutation

    return project, mutation, mutation_scope


def _response(**overrides: Any) -> FlagTriageResponse:
    fields: dict[str, Any] = {
        "bead_id": "sase-flag.1",
        "project": "sase",
        "title": "Remove the prettier_enabled flag",
        "key": "prettier_enabled",
        "old_remove_by_date": "2026-08-01",
        "old_remove_by_release": "0.16.0",
        "action": "remove",
        "feedback": None,
        "source": "tui",
        "winner": None,
        "remove_by_date": None,
        "remove_by_release": None,
    }
    fields.update(overrides)
    return FlagTriageResponse(**fields)


def test_remove_flag_triage_notes_the_winner_and_submits_one_launch() -> None:
    project, mutation, mutation_scope = _mutation_double()
    decision = _response(action="remove", winner="enabled", feedback="Ship it.")
    task = SimpleNamespace(proc_id="task-bg-1")

    with (
        patch(
            "sase.bead._flag_gate_actions._resolve_flag_triage_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch(
            "sase.bead.task_launch.submit_task_launch_task",
            return_value=task,
        ) as submit,
    ):
        result = remove_flag_triage(decision, origin="ace")

    assert result is task
    project.append_note.assert_called_once()
    note_args = project.append_note.call_args
    assert note_args.args[0] == "sase-flag.1"
    assert "the enabled branch wins" in note_args.args[1]
    assert "Ship it." in note_args.args[1]
    assert note_args.kwargs["author"] == "owner@example"
    mutation.commit.assert_called_once_with("chore(beads): note sase-flag.1")
    submit.assert_called_once()
    call = submit.call_args
    assert call.args == ("sase-flag.1",)
    assert call.kwargs["project"] == "sase"
    assert "prettier_enabled" in call.kwargs["feedback"]
    assert "enabled" in call.kwargs["feedback"]
    assert call.kwargs["origin"] == "ace"


def test_remove_flag_triage_requires_remove_action_and_winner() -> None:
    with pytest.raises(GateError) as exc_info:
        remove_flag_triage(_response(action="keep"))
    assert exc_info.value.code == "invalid_flag_action"

    with pytest.raises(GateError):
        remove_flag_triage(_response(action="remove", winner=None))


def test_extend_flag_triage_rewrites_thresholds_and_records_reason() -> None:
    project, mutation, mutation_scope = _mutation_double()
    decision = _response(
        action="extend",
        remove_by_date="2026-12-01",
        remove_by_release="0.17.0",
        feedback="Needs more soak time.",
    )

    with (
        patch(
            "sase.bead._flag_gate_actions._resolve_flag_triage_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        extend_flag_triage(decision)

    project.update.assert_called_once_with(
        "sase-flag.1",
        flag={
            "key": "prettier_enabled",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.17.0",
        },
    )
    project.append_note.assert_called_once()
    note_args = project.append_note.call_args
    note_text = note_args.args[1]
    assert "2026-08-01" in note_text
    assert "2026-12-01" in note_text
    assert "Needs more soak time." in note_text
    mutation.commit.assert_called_once_with("chore(beads): update sase-flag.1")
    # The bead stays open: extend never touches status.
    assert not project.update.call_args.kwargs.get("status")


def test_extend_flag_triage_requires_extend_action_and_thresholds() -> None:
    with pytest.raises(GateError):
        extend_flag_triage(_response(action="close"))
    with pytest.raises(GateError):
        extend_flag_triage(_response(action="extend", remove_by_date=None))


def test_keep_flag_triage_records_rationale_and_launches_promotion_worker() -> None:
    project, mutation, mutation_scope = _mutation_double()
    decision = _response(action="keep", feedback="Permanent ops toggle.")
    task = SimpleNamespace(proc_id="task-bg-2")

    with (
        patch(
            "sase.bead._flag_gate_actions._resolve_flag_triage_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
        patch(
            "sase.bead.task_launch.submit_task_launch_task",
            return_value=task,
        ) as submit,
    ):
        result = keep_flag_triage(decision)

    assert result is task
    project.append_note.assert_called_once()
    assert "Permanent ops toggle." in project.append_note.call_args.args[1]
    mutation.commit.assert_called_once_with("chore(beads): note sase-flag.1")
    submit.assert_called_once()
    brief = submit.call_args.kwargs["feedback"]
    assert 'kind: "ops"' in brief
    assert "Permanent ops toggle." in brief


def test_keep_flag_triage_requires_keep_action() -> None:
    with pytest.raises(GateError):
        keep_flag_triage(_response(action="close"))


def test_close_flag_triage_closes_as_canceled_with_reason() -> None:
    project, mutation, mutation_scope = _mutation_double()
    decision = _response(action="close", feedback="Never shipped.")

    with (
        patch(
            "sase.bead._flag_gate_actions._resolve_flag_triage_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
    ):
        close_flag_triage(decision)

    project.close.assert_called_once_with(
        ["sase-flag.1"],
        reason="Never shipped.",
        resolution="canceled",
    )
    mutation.commit.assert_called_once_with("chore(beads): close sase-flag.1")


def test_close_flag_triage_requires_close_action_and_feedback() -> None:
    with pytest.raises(GateError):
        close_flag_triage(_response(action="keep"))
    with pytest.raises(GateError):
        close_flag_triage(_response(action="close", feedback=None))
