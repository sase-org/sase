"""Host-side effects of answering a BeadSnooze wake gate."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
from typing import Any
from unittest.mock import patch

import pytest

from sase.bead.snooze_gate import (
    BEAD_SNOOZE_COMMAND_PATHS,
    _bead_snooze_close_reason,
    translate_bead_snooze_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications
from tests.test_bead.conftest import FIXED_BEAD_NOW
from tests.test_bead.snooze_gate_test_helpers import (
    WAKE_TIME,
    bead_snooze_spec,
    mutation_double,
)


def test_bead_snooze_close_uses_the_preset_reason_when_feedback_is_empty(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-close-preset"))
    project, mutation, mutation_scope = mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
    ):
        execute_gate_selection(gate.bundle_path, ["close"], {}, source="tui")

    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason=_bead_snooze_close_reason(WAKE_TIME),
        resolution="canceled",
    )
    mutation.commit.assert_called_once_with("chore(beads): close sase-task.1")


def test_bead_snooze_close_feedback_replaces_the_preset_reason(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-close-override"))
    project, _mutation, mutation_scope = mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
    ):
        execute_gate_selection(
            gate.bundle_path,
            ["close"],
            {},
            feedback="Fixed upstream.",
            source="mobile",
        )

    project.close.assert_called_once_with(
        ["sase-task.1"],
        reason="Fixed upstream.",
        resolution="canceled",
    )


def test_bead_snooze_ready_cancels_the_snooze_and_notes_the_wake(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-ready"))
    project, mutation, mutation_scope = mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        execute_gate_selection(gate.bundle_path, ["ready"], {}, source="tui")

    project.cancel_snooze.assert_called_once_with("sase-task.1", actor="owner@example")
    project.append_note.assert_called_once_with(
        "sase-task.1",
        "Woken from snooze and returned to triage.",
        author="owner@example",
    )
    mutation.commit.assert_called_once_with("chore(beads): wake sase-task.1")


def _resnooze(
    gate: Any,
    duration_input: dict[str, Any],
    *,
    feedback: str | None = None,
) -> Any:
    """Answer one wake gate's Snooze branch with a declared duration."""
    return execute_gate_selection(
        gate.bundle_path,
        ["snooze"],
        feedback=feedback,
        option_inputs={"snooze": duration_input},
        source="tui",
    )


def test_bead_snooze_resnooze_defers_again_with_the_typed_duration(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-again"))
    project, mutation, mutation_scope = mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        execution = _resnooze(gate, {"duration": "3d +2"})

    # The duration reaches the command on stdin and comes back as its result,
    # rather than being re-parsed out of the free-text note host-side.
    assert execution.response["option_inputs"]["snooze"] == {"duration": "3d +2"}
    assert execution.response["option_results"] == [
        {"id": "snooze", "result": {"action": "snooze", "duration": "3d +2"}}
    ]
    [call] = project.snooze.call_args_list
    assert call.args == ("sase-task.1",)
    assert call.kwargs["plus_ones"] == 2
    assert call.kwargs["reason"] == "waiting on the upstream fix"
    assert call.kwargs["actor"] == "owner@example"
    resolved = datetime.fromisoformat(call.kwargs["until"])
    reference = FIXED_BEAD_NOW.replace(tzinfo=resolved.tzinfo)
    assert resolved == (reference + timedelta(days=3)).replace(microsecond=0)
    mutation.commit.assert_called_once_with("chore(beads): snooze sase-task.1")


def test_bead_snooze_resnooze_accepts_a_preset_and_records_the_note_as_the_reason(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-preset"))
    project, _mutation, mutation_scope = mutation_double()

    with (
        patch(
            "sase.bead.snooze_gate._resolve_bead_snooze_project_cwd",
            return_value=Path("/canonical/sase"),
        ),
        patch("sase.bead.cli_common.bead_store_mutation", side_effect=mutation_scope),
        patch("sase.agent.identity.discover_agent_identity", return_value=None),
    ):
        _resnooze(gate, {"duration": "4h"}, feedback="Still blocked upstream.")

    [call] = project.snooze.call_args_list
    assert call.kwargs["plus_ones"] is None
    assert call.kwargs["reason"] == "Still blocked upstream."
    resolved = datetime.fromisoformat(call.kwargs["until"])
    reference = FIXED_BEAD_NOW.replace(tzinfo=resolved.tzinfo)
    assert resolved == (reference + timedelta(hours=4)).replace(microsecond=0)


def test_bead_snooze_rejects_an_unparsable_duration_and_leaves_the_gate_pending(
    gate_home: Path,
) -> None:
    """The property the deleted host-side feedback check existed to provide."""
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-typo"))

    with pytest.raises(GateError) as exc_info:
        _resnooze(gate, {"duration": "threeish days"})

    assert exc_info.value.code == "command_failed"
    assert not gate.response_path.exists()
    [error] = sorted((gate.bundle_path / "errors").glob("*.json"))
    recorded = json.loads(error.read_text(encoding="utf-8"))
    assert recorded["option_id"] == "snooze"
    assert "accepted forms" in recorded["stderr"]
    [notification] = load_notifications()
    assert notification.snooze_until == WAKE_TIME


@pytest.mark.parametrize(
    ("duration_input", "code"),
    [
        ({}, "schema_validation_failed"),
        ({"duration": 3}, "schema_validation_failed"),
        ({"duration": ""}, "command_failed"),
    ],
)
def test_bead_snooze_rejects_unusable_duration_input(
    gate_home: Path,
    duration_input: dict[str, Any],
    code: str,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id=f"bead-snooze-bad-{code}"))

    with pytest.raises(GateError) as exc_info:
        _resnooze(gate, duration_input)

    assert exc_info.value.code == code
    assert not gate.response_path.exists()


def test_bead_snooze_rejects_legacy_custom_duration_on_new_gate(
    gate_home: Path,
) -> None:
    """The compiled one-line schema rejects the old companion property."""
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-forged-extra"))

    with pytest.raises(GateError) as exc_info:
        _resnooze(gate, {"duration": "3d", "custom_duration": "3d +2"})

    assert exc_info.value.code == "schema_validation_failed"
    assert not gate.response_path.exists()


def test_bead_snooze_translation_requires_a_matching_result(gate_home: Path) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-translate"))
    response = {
        "selected_option_ids": ["ready"],
        "option_results": [{"id": "ready", "result": {"action": "close"}}],
    }

    with pytest.raises(GateError) as exc_info:
        translate_bead_snooze_response(gate.bundle_path, response)

    assert exc_info.value.code == "invalid_response"


@pytest.mark.parametrize(
    ("option_id", "command_input", "expected_stderr"),
    [
        ("close", b'{"unexpected": true}\n', b"must be empty"),
        ("snooze", b"{}\n", b"duration must be a string"),
        (
            "snooze",
            b'{"duration": "custom"}\n',
            b"a custom snooze needs a wake time",
        ),
    ],
)
def test_bead_snooze_commands_reject_unusable_input(
    gate_home: Path,
    option_id: str,
    command_input: bytes,
    expected_stderr: bytes,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id=f"bead-snooze-command-{option_id}"))
    command_path = gate.bundle_path / BEAD_SNOOZE_COMMAND_PATHS[option_id]

    completed = subprocess.run(
        [str(command_path)],
        cwd=gate.bundle_path,
        input=command_input,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert expected_stderr in completed.stderr


def test_bead_snooze_command_accepts_legacy_custom_duration_payload(
    gate_home: Path,
) -> None:
    del gate_home
    gate = create_gate(bead_snooze_spec(request_id="bead-snooze-legacy-command"))
    command_path = gate.bundle_path / BEAD_SNOOZE_COMMAND_PATHS["snooze"]

    completed = subprocess.run(
        [str(command_path)],
        cwd=gate.bundle_path,
        input=b'{"duration": "custom", "custom_duration": "3d +2"}\n',
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"action": "snooze", "duration": "3d +2"}
