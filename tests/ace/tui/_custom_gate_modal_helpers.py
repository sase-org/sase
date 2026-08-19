"""Shared helpers for the custom gate modal test modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import App

from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModalData,
)
from sase.ace.tui.modals.gate_branch_controls import GateBranchData
from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.bead._task_gate_spec import build_task_triage_gate_spec
from sase.notification_gates.models import GateGroup, GateOption
from sase.notification_gates.presentation import GateChip


_ROOT = Path(__file__).resolve().parents[3]


class GateTestApp(App[None]):
    """Minimal app harness that records notifications instead of showing them."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.recorded_notifications: list[tuple[str, str]] = []

    def notify(
        self,
        message: str,
        *_args: object,
        severity: str = "information",
        **_kwargs: object,
    ) -> None:
        self.recorded_notifications.append((message, severity))


class StyledGateTestApp(GateTestApp):
    """Harness that loads the real stylesheet so layout rules apply."""

    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"


def option(
    option_id: str,
    *,
    label: str | None = None,
    icon: str | None = None,
    selected: bool = True,
    feedback: str = "disabled",
    inputs: list[dict[str, Any]] | None = None,
) -> GateOption:
    payload: dict[str, Any] = {
        "id": option_id,
        "label": label or option_id.title(),
        "icon": icon,
        "default_selected": selected,
        "feedback": feedback,
        "command": {"argv": [f"commands/{option_id}"]},
    }
    if inputs is not None:
        payload["inputs"] = inputs
    return GateOption.from_mapping(payload, 0)


def data(
    *,
    options: tuple[GateOption, ...],
    branches: tuple[tuple[str, ...], ...],
    groups: tuple[GateGroup, ...] = (),
    primary_branch: tuple[str, ...] | None = None,
    preview_name: str | None = None,
    preview_text: str | None = None,
    title: str = "Custom Gate",
    origin_agent: str | None = None,
    notes: tuple[str, ...] | None = None,
    gate_title: str | None = None,
    chip: GateChip | None = None,
) -> CustomGateModalData:
    return CustomGateModalData(
        request_id="custom-ace",
        title=title,
        sender="review-agent",
        icon="🛡️",
        notes=notes or ("Review guarded work.",),
        attachments=(),
        preview_name=preview_name,
        preview_text=preview_text,
        gate=GateBranchData(
            query="test query",
            options=options,
            groups=groups,
            branches=branches,
            primary_branch=primary_branch or branches[0],
        ),
        origin_agent=origin_agent,
        gate_title=gate_title,
        chip=chip,
    )


def open_panel(app: App[None]) -> GateInputPanel:
    screen = app.screen
    assert isinstance(screen, GateInputPanel)
    return screen


def task_triage_data() -> CustomGateModalData:
    spec = build_task_triage_gate_spec(
        request_id="task-triage-ace-modal",
        bead_id="sase-task.1",
        project="sase",
        title="Review follow-up",
        description="Preserve the compatibility path.",
        notes="Raised by the land agent.",
        created_by="claude_coder",
        created_at="2026-01-01T00:00:00Z",
    )
    presentation = spec["presentation"]
    preview = next(
        resource["content"]
        for resource in spec["resources"]
        if resource["path"] == "task.md"
    )
    options = tuple(
        GateOption.from_mapping(option_payload, index)
        for index, option_payload in enumerate(spec["options"])
    )
    return CustomGateModalData(
        request_id=str(spec["request_id"]),
        title="Task Triage",
        sender=str(presentation["sender"]),
        icon=str(presentation["icon"]),
        notes=tuple(str(note) for note in presentation["notes"]),
        attachments=("task.md",),
        preview_name="task.md",
        preview_text=str(preview),
        gate=GateBranchData(
            query=str(spec["query"]),
            options=options,
            groups=(),
            branches=(("launch",), ("close",), ("snooze",)),
            primary_branch=("launch",),
        ),
        origin_agent=str(presentation["origin_agent"]),
        gate_title=str(presentation["title"]),
    )
