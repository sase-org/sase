"""Host-side effects and translation of the snooze TaskTriage branch."""

from __future__ import annotations

from contextlib import contextmanager
import json
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sase.bead.task_gate import (
    TASK_TRIAGE_COMMAND_PATHS,
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
            option_inputs={"snooze": {"duration": "3d +2"}},
            source="tui",
        )

    # The duration reaches the command on stdin and comes back as its result,
    # rather than being re-parsed out of the free-text note host-side.
    assert execution.response["option_results"] == [
        {"id": "snooze", "result": {"action": "snooze", "duration": "3d +2"}}
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
            gate.bundle_path,
            ["snooze"],
            option_inputs={"snooze": {"duration": "4h"}},
            feedback="Waiting on the upstream fix.",
            source="tui",
        )

    [call] = project.snooze.call_args_list
    assert call.kwargs["plus_ones"] is None
    # An optional note is now the deferral's reason rather than its duration.
    assert call.kwargs["reason"] == "Waiting on the upstream fix."


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
            option_inputs={"snooze": {"duration": "threeish days"}},
            source="tui",
        )

    assert exc_info.value.code == "command_failed"
    assert not gate.response_path.exists()
    [error] = sorted((gate.bundle_path / "errors").glob("*.json"))
    recorded = json.loads(error.read_text(encoding="utf-8"))
    assert recorded["option_id"] == "snooze"
    assert "accepted forms" in recorded["stderr"]


@pytest.mark.parametrize(
    ("duration_input", "code"),
    [
        ({}, "schema_validation_failed"),
        ({"duration": 3}, "schema_validation_failed"),
        ({"duration": ""}, "command_failed"),
    ],
)
def test_task_triage_snooze_rejects_unusable_duration_input(
    gate_home: Path,
    duration_input: dict[str, Any],
    code: str,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id=f"task-triage-snooze-bad-{code}"))

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(
            gate.bundle_path,
            ["snooze"],
            option_inputs={"snooze": duration_input},
            source="tui",
        )

    assert exc_info.value.code == code
    assert not gate.response_path.exists()


def test_task_triage_snooze_rejects_legacy_custom_duration_on_new_gate(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-snooze-extra"))

    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(
            gate.bundle_path,
            ["snooze"],
            option_inputs={"snooze": {"duration": "3d", "custom_duration": "3d +2"}},
            source="tui",
        )

    assert exc_info.value.code == "schema_validation_failed"
    assert not gate.response_path.exists()


def test_task_triage_snooze_command_accepts_legacy_custom_duration_payload(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(task_triage_spec(request_id="task-triage-snooze-legacy-command"))
    command_path = gate.bundle_path / TASK_TRIAGE_COMMAND_PATHS["snooze"]

    completed = subprocess.run(
        [str(command_path)],
        cwd=gate.bundle_path,
        input=b'{"duration": "custom", "custom_duration": "3d +2"}\n',
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"action": "snooze", "duration": "3d +2"}


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


def test_typed_task_triage_gate_still_exposes_the_snooze_option(
    gate_home: Path,
) -> None:
    del gate_home
    spec = task_triage_spec(
        request_id="task-triage-typed-snooze",
        task_type="flake",
        task_type_fields={
            "node_id": "tests/x.py::test_y",
            "evidence": "3/50 under -n 8",
        },
    )
    gate = create_gate(spec)
    request = json.loads(gate.request_path.read_text(encoding="utf-8"))

    assert request["payload"]["task_type"] == "flake"
    assert request["presentation"]["tags"] == ["bead", "task", "flake"]
    assert [option["id"] for option in request["options"]] == [
        "launch",
        "close",
        "snooze",
    ]


def test_task_triage_snooze_helper_refuses_a_mismatched_decision() -> None:
    decision = SimpleNamespace(
        bead_id="sase-task.1",
        project="sase",
        title="Follow up on the cache",
        action="launch",
        feedback=None,
        source="tui",
        duration="3d",
    )

    with pytest.raises(GateError) as exc_info:
        snooze_task_triage(decision)  # type: ignore[arg-type]

    assert exc_info.value.code == "invalid_task_action"
