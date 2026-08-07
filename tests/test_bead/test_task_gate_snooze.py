"""Host-side effects and translation of the snooze TaskTriage branch."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.bead.task_gate import (
    TASK_TRIAGE_SNOOZE_REASON,
    snooze_task_triage,
    translate_task_triage_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from tests.test_bead.conftest import FIXED_BEAD_NOW
from tests.test_bead.task_gate_test_helpers import task_triage_spec


def _mutation_scope(mutation: Any) -> Any:
    @contextmanager
    def scope(auto_commit: object, *, cwd: Path) -> Any:
        del auto_commit, cwd
        yield mutation

    return scope


def test_task_triage_snooze_defers_the_bead_with_the_typed_duration_and_target(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-snooze"))
    project = MagicMock()
    project.owner = "owner@example"
    mutation = SimpleNamespace(project=project, commit=MagicMock())

    with (
        patch(
            "sase.bead._task_gate_actions._resolve_task_triage_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=_mutation_scope(mutation),
        ),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ["snooze"],
            {},
            feedback="3d +2",
            source="tui",
        )

    assert execution.response["option_results"] == [
        {"id": "snooze", "result": {"action": "snooze"}}
    ]
    [call] = project.snooze.call_args_list
    assert call.args == ("sase-task.1",)
    assert call.kwargs["plus_ones"] == 2
    assert call.kwargs["reason"] == TASK_TRIAGE_SNOOZE_REASON
    assert call.kwargs["actor"] == "owner@example"
    resolved = datetime.fromisoformat(call.kwargs["until"])
    reference = FIXED_BEAD_NOW.replace(tzinfo=resolved.tzinfo)
    assert resolved == (reference + timedelta(days=3)).replace(microsecond=0)
    mutation.commit.assert_called_once_with("chore(beads): snooze sase-task.1")


def test_task_triage_snooze_accepts_a_bare_duration_without_a_plus_one_target(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-snooze-bare"))
    project = MagicMock()
    project.owner = "owner@example"
    mutation = SimpleNamespace(project=project, commit=MagicMock())

    with (
        patch(
            "sase.bead._task_gate_actions._resolve_task_triage_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch(
            "sase.bead.cli_common.bead_store_mutation",
            side_effect=_mutation_scope(mutation),
        ),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        execute_gate_selection(
            gate.bundle_path, ["snooze"], {}, feedback="2h", source="tui"
        )

    [call] = project.snooze.call_args_list
    assert call.kwargs["plus_ones"] is None


def test_task_triage_snooze_rejects_an_unparsable_duration_and_stays_pending(
    gate_home: Path,
) -> None:
    """A typo must cost a retry, not the ready task's only triage gate."""
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-snooze-typo"))

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(
            gate.bundle_path,
            ["snooze"],
            {},
            feedback="threeish days",
            source="tui",
        )

    assert exc_info.value.code == "invalid_snooze_duration"
    assert "accepted forms" in str(exc_info.value)
    assert not gate.response_path.exists()


def test_task_triage_snooze_translation_requires_a_wake_time(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-snooze-translate"))
    response = {
        "selected_option_ids": ["snooze"],
        "option_results": [{"id": "snooze", "result": {"action": "snooze"}}],
    }

    with pytest.raises(GateError) as exc_info:
        translate_task_triage_response(gate.bundle_path, response)

    assert exc_info.value.code == "invalid_response"
    assert "requires a wake time" in str(exc_info.value)


def test_task_triage_snooze_helper_refuses_a_mismatched_decision() -> None:
    decision = SimpleNamespace(
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        action="launch",
        feedback="3d",
        source="tui",
    )

    with pytest.raises(GateError) as exc_info:
        snooze_task_triage(decision)  # type: ignore[arg-type]

    assert exc_info.value.code == "invalid_task_action"
