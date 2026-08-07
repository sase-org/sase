"""Coverage for the always-populated gate and summary detail panes."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

import pytest
from rich.console import Console

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.bead.model import SnoozeRecord
from sase.bead.snooze_gate import create_bead_snooze_gate
from sase.bead.task_gate import create_task_triage_gate
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.service import create_gate
from sase.notification_gates.summary import (
    gate_summary_from_notification,
    load_gate_summary,
)
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications
from sase.plan_gate import create_plan_approval_gate

from tests._notification_gates_fixtures import custom_gate_spec, gate_spec
from tests.plan_validation_helpers import VALID_TALE_PLAN


def _render_plain(renderable: object) -> str:
    console = Console(record=True, width=110, color_system=None)
    console.print(renderable)
    return console.export_text()


def _modal_for(notifications: list[Notification]) -> NotificationModal:
    return NotificationModal(notifications)


def _render_loaded(
    modal: NotificationModal, notification: Notification
) -> tuple[str, object]:
    """Preload the bundle-tier summary, then render as the pane would once loaded."""
    modal._gate_summary_cache[notification.id] = ((), load_gate_summary(notification))
    pane = modal._render_gate_pane(notification)
    assert pane is not None
    return pane


def _custom_notification(gate_home: Path) -> Notification:
    del gate_home
    create_gate(custom_gate_spec(request_id="pane-custom"))
    return load_notifications(include_dismissed=True)[0]


def _hitl_notification(gate_home: Path) -> Notification:
    del gate_home
    create_gate(gate_spec(kind="hitl", request_id="pane-hitl"))
    return load_notifications(include_dismissed=True)[0]


def _launch_notification(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> Notification:
    from sase.agent.launch_request import create_launch_approval_request_from_prompt

    monkeypatch.setenv("SASE_HOME", str(gate_home / ".sase"))
    monkeypatch.chdir(gate_home)
    create_launch_approval_request_from_prompt(
        "Do work", reason="Need approval to proceed"
    )
    return load_notifications(include_dismissed=True)[0]


def _task_triage_notification(gate_home: Path) -> Notification:
    del gate_home
    create_task_triage_gate(
        request_id="pane-task-triage",
        bead_id="sase-task.1",
        project="sase",
        title="Review follow-up",
        description="Preserve the compatibility path.",
        notes="Raised by the land agent.",
    )
    return load_notifications(include_dismissed=True)[0]


def _plan_notification(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> Notification:
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    plan = gate_home / "tale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_plan_approval_gate(plan, "pane-plan")
    return load_notifications(include_dismissed=True)[0]


def _bead_snooze_notification(gate_home: Path) -> Notification:
    del gate_home
    snooze = SnoozeRecord(
        until="2099-01-04T09:00:00-05:00",
        snoozed_at="2026-08-01T09:00:00-04:00",
        snoozed_by="owner@example.com",
        reason="waiting on upstream",
    )
    create_bead_snooze_gate(
        request_id="pane-bead-snooze",
        bead_id="sase-task.2",
        project="sase",
        title="Woken follow-up",
        snooze=snooze,
    )
    return load_notifications(include_dismissed=True)[0]


_KIND_BUILDERS: dict[str, Callable[..., Notification]] = {
    "CustomGate": _custom_notification,
    "HITL": _hitl_notification,
    "LaunchApproval": _launch_notification,
    "TaskTriage": _task_triage_notification,
    "PlanApproval": _plan_notification,
    "BeadSnooze": _bead_snooze_notification,
}


@pytest.mark.parametrize("action", sorted(_KIND_BUILDERS))
def test_every_gate_kind_renders_a_populated_card(
    action: str, gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = _KIND_BUILDERS[action]
    try:
        notification = builder(gate_home, monkeypatch)
    except TypeError:
        notification = builder(gate_home)
    assert notification.action == action

    summary = gate_summary_from_notification(notification)
    assert summary is not None

    modal = _modal_for([notification])
    pane_title, content = _render_loaded(modal, notification)
    title = modal._detail_title(notification, pane_title)

    assert title != "No files attached"
    assert pane_title != "No files attached"

    text = _render_plain(content)
    assert "Awaiting your decision" in text
    assert pane_title == summary.title
    assert all(note in text for note in notification.notes)


_TWO_BRANCH_QUERY_SPEC: dict[str, object] = {
    "schema_version": 3,
    "request_id": "pane-decision-order",
    "kind": "custom",
    "producer": {"agent": "test"},
    "payload": {},
    "presentation": {
        "icon": "🚀",
        "title": "Restart example.service",
        "sender": "deployment-confirmation",
        "notes": ["Restart the service now?"],
    },
    "query": "(restart AND verify) OR reject",
    "primary_branch": ["restart", "verify"],
    "options": [
        {
            "id": "restart",
            "label": "Restart service",
            "icon": "🚀",
            "command": {"argv": ["commands/restart"]},
        },
        {
            "id": "verify",
            "label": "Verify service health",
            "icon": "🩺",
            "command": {"argv": ["commands/verify"]},
        },
        {
            "id": "reject",
            "label": "Do not restart",
            "icon": "❌",
            "command": {"argv": ["commands/reject"]},
        },
    ],
    "groups": [
        {"options": ["restart", "verify"], "label": "Restart service", "icon": "🚀"}
    ],
    "resources": [
        {
            "path": "commands/restart",
            "role": "command",
            "content": '#!/bin/sh\nprintf \'{"status":"ok"}\\n\'\n',
        },
        {
            "path": "commands/verify",
            "role": "command",
            "content": '#!/bin/sh\nprintf \'{"status":"ok"}\\n\'\n',
        },
        {
            "path": "commands/reject",
            "role": "command",
            "content": '#!/bin/sh\nprintf \'{"status":"ok"}\\n\'\n',
        },
    ],
    "auto": False,
}


def test_decision_block_lists_branches_in_canonical_order_with_primary_marked(
    gate_home: Path,
) -> None:
    del gate_home
    create_gate(dict(_TWO_BRANCH_QUERY_SPEC))
    notification = load_notifications(include_dismissed=True)[0]

    modal = _modal_for([notification])
    _title, content = _render_loaded(modal, notification)
    text = _render_plain(content)

    restart_index = text.index("Restart service")
    reject_index = text.index("Do not restart")
    assert restart_index < reject_index
    assert "▸ 1" in text
    assert "  2" in text


def test_answered_summary_marks_chosen_options_and_prints_feedback(
    gate_home: Path,
) -> None:
    del gate_home
    result = create_gate(custom_gate_spec(request_id="pane-answered"))
    execute_gate_selection(
        result.bundle_path, ["proceed", "audit"], feedback="Looks safe to me"
    )
    notification = load_notifications(include_dismissed=True)[0]

    modal = _modal_for([notification])
    _title, content = _render_loaded(modal, notification)
    text = _render_plain(content)

    assert "Answered" in text
    assert "you chose" in text
    assert "Proceed safely" in text
    assert "Note" in text
    assert "Looks safe to me" in text


def test_unavailable_summary_renders_degraded_card(gate_home: Path) -> None:
    del gate_home
    notification = Notification(
        id="pane-unavailable",
        timestamp="2026-08-07T09:00:00-04:00",
        sender="test",
        action="CustomGate",
        action_data={"request_id": "does-not-exist"},
        notes=["This gate no longer resolves to a bundle."],
    )
    modal = _modal_for([notification])
    _title, content = _render_loaded(modal, notification)
    text = _render_plain(content)

    assert "Gate details unavailable" in text
    assert "press d to debug" in text


def test_gate_with_attachments_renders_card_and_file_body(gate_home: Path) -> None:
    del gate_home
    spec = custom_gate_spec(request_id="pane-attachments")
    presentation = spec["presentation"]
    assert isinstance(presentation, dict)
    presentation["files"] = ["commands/proceed"]
    create_gate(spec)
    notification = load_notifications(include_dismissed=True)[0]
    assert notification.files

    title_widget = _FakeLabel()
    content_widget = _FakeStatic()
    scroll_widget = _FakeScroll()
    modal = _modal_for([notification])
    modal.query_one = _query_one_stub(  # type: ignore[method-assign]
        title_widget, content_widget, scroll_widget
    )

    modal._display_file(notification)

    assert content_widget.last is not None
    rendered = _render_plain(content_widget.last)
    assert "Awaiting your decision" in rendered
    assert "Attachments" in rendered


def test_non_gate_attachment_less_notification_renders_summary_card() -> None:
    notification = Notification(
        id="pane-plain",
        timestamp="2026-08-07T09:00:00-04:00",
        sender="test",
        notes=["Just an informational notice."],
    )
    modal = _modal_for([notification])
    title_widget = _FakeLabel()
    content_widget = _FakeStatic()
    scroll_widget = _FakeScroll()
    modal.query_one = _query_one_stub(  # type: ignore[method-assign]
        title_widget, content_widget, scroll_widget
    )

    modal._display_file(notification)

    assert content_widget.last is not None
    rendered = _render_plain(content_widget.last)
    assert "Just an informational notice." in rendered
    assert "no attachments" in rendered
    assert title_widget.last is not None
    assert title_widget.last != "No files attached"


def test_stale_summary_is_not_painted_after_highlight_moved(gate_home: Path) -> None:
    del gate_home
    create_gate(custom_gate_spec(request_id="pane-stale"))
    notification = load_notifications(include_dismissed=True)[0]
    other = Notification(
        id="other-row",
        timestamp="2026-08-07T09:01:00-04:00",
        sender="test",
        notes=["Different row"],
    )
    modal = _modal_for([notification, other])
    # Simulate the highlight having moved to a different row by the time the
    # off-pump enrichment resolves.
    modal._get_highlighted_notification = lambda: other  # type: ignore[method-assign]
    repainted: list[Notification] = []
    modal._display_file = lambda n: repainted.append(n)  # type: ignore[method-assign]

    modal._gate_summary_cache[notification.id] = (
        (1, -1, -1),
        gate_summary_from_notification(notification),
    )

    import asyncio

    asyncio.run(modal._load_gate_summary(notification.id))

    assert repainted == []


class _FakeLabel:
    def __init__(self) -> None:
        self.last: object | None = None

    def update(self, value: object) -> None:
        self.last = value

    def add_class(self, *_names: str) -> None:
        pass

    def remove_class(self, *_names: str) -> None:
        pass


class _FakeStatic:
    def __init__(self) -> None:
        self.last: object | None = None

    def update(self, value: object) -> None:
        self.last = value


class _FakeScroll:
    def scroll_home(self, *, animate: bool = False) -> None:
        del animate


def _query_one_stub(
    title: _FakeLabel, content: _FakeStatic, scroll: _FakeScroll
) -> Callable[..., object]:
    def query_one(selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        if selector == "#notification-file-scroll":
            return scroll
        if selector == "#notification-sent-at":
            return _FakeLabel()
        raise LookupError(selector)

    return query_one
