"""Custom gate and neutral HITL modal-data loader projection coverage."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from sase.ace.tui.actions.agents._notification_custom_gate import (
    _custom_gate_password_warning_requested,
    _load_custom_gate_modal_data,
)
from sase.ace.tui.actions.agents._notification_hitl_modal import (
    _load_neutral_hitl_data,
    _neutral_hitl_choice_id,
)
from sase.ace.tui.modals.notification_modal_constants import (
    ACTION_BADGES,
    notification_icon,
)
from sase.notification_gates.presentation import GateChip
from sase.notification_gates.service import create_gate
from sase.bead.task_gate import create_task_triage_gate
from sase.notifications.store import load_notifications
from sase.xprompt import HITLResult

from ._notification_custom_gate_helpers import _spec, gate_home_fixture


def test_custom_gate_loader_projects_icons_preview_and_defaults(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(_spec())
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.icon == "🛡️"
    assert data.title == "Custom Gate"
    assert data.origin_agent is None
    assert data.chip is None
    assert data.sender == "safety-agent"
    assert data.preview_name == "preview.md"
    assert data.preview_text is not None and "Guarded work" in data.preview_text
    assert data.gate.options[0].icon == "✅"
    assert data.gate.options[1].default_selected is True
    assert data.gate.branches == (("approve", "audit"),)


def test_custom_gate_loader_carries_declared_chip(
    gate_home: Path,
) -> None:
    del gate_home
    spec = _spec()
    presentation = cast(dict[str, object], spec["presentation"])
    spec["presentation"] = {
        **presentation,
        "chip": {"glyph": "≈", "label": "flake", "color": "#AF87FF"},
    }
    create_gate(spec)
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.chip == GateChip("≈", "flake", "#AF87FF")


def test_custom_gate_loader_carries_declared_origin_agent(
    gate_home: Path,
) -> None:
    del gate_home
    spec = _spec()
    presentation = cast(dict[str, object], spec["presentation"])
    spec["presentation"] = {**presentation, "origin_agent": "claude_coder"}
    create_gate(spec)
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.origin_agent == "claude_coder"


def test_custom_gate_loader_warns_for_agent_authored_password_request(
    gate_home: Path,
) -> None:
    del gate_home
    spec = _spec()
    presentation = cast(dict[str, object], spec["presentation"])
    spec["presentation"] = {
        **presentation,
        "notes": ["Please enter the sudo password in this gate."],
    }
    create_gate(spec)
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.password_warning is True
    assert (
        _custom_gate_password_warning_requested({}, data.preview_text, data.gate)
        is False
    )


def test_custom_gate_password_warning_ignores_negated_password_note(
    gate_home: Path,
) -> None:
    del gate_home
    spec = _spec()
    presentation = cast(dict[str, object], spec["presentation"])
    spec["presentation"] = {
        **presentation,
        "notes": ["This uses sudo but never asks for a password."],
    }
    create_gate(spec)
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.password_warning is False


def test_task_triage_loader_uses_generic_branch_modal_data(
    gate_home: Path,
) -> None:
    del gate_home
    create_task_triage_gate(
        request_id="task-triage-ace-loader",
        bead_id="sase-task.1",
        project="sase",
        title="Review follow-up",
        description="Preserve the compatibility path.",
        notes="Raised by the land agent.",
    )
    notification = load_notifications()[0]

    data = _load_custom_gate_modal_data(notification)

    assert data.icon == "✦"
    assert data.title == "Task Triage"
    assert data.sender == "bead"
    assert data.preview_name == "task.md"
    assert data.preview_text is not None
    assert "Preserve the compatibility path." in data.preview_text
    assert data.gate.branches == (("launch",), ("close",), ("snooze",))
    assert data.gate.primary_branch == ("launch",)
    assert [option.feedback for option in data.gate.options] == [
        "optional",
        "required",
        "optional",
    ]
    # Snooze collects its wake time as a declared input, which the generic
    # branch controls render with no per-kind code.
    assert [[field.id for field in option.inputs] for option in data.gate.options] == [
        [],
        [],
        ["duration"],
    ]
    [duration_field] = data.gate.options[2].inputs
    assert duration_field.label == "Wake time"
    assert duration_field.type.value == "line"
    assert duration_field.required is True
    assert ACTION_BADGES["TaskTriage"] == "[task]"
    assert notification_icon("TaskTriage", None) == "✦"
    assert ACTION_BADGES["OpenLaunchControl"] == "[models]"
    assert notification_icon("OpenLaunchControl", None) == "🎛️"


def test_neutral_hitl_loader_and_accept_alias_use_gate_choice(gate_home: Path) -> None:
    del gate_home
    create_gate(_spec(kind="hitl"))
    notification = load_notifications()[0]

    data = _load_neutral_hitl_data(notification)

    assert data.input_data.step_name == "guarded work"
    assert data.choice_ids == ("accept",)
    assert (
        _neutral_hitl_choice_id(
            HITLResult(action="accept", approved=True), data.choice_ids
        )
        == "accept"
    )
