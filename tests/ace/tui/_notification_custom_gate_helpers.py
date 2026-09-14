"""Shared fixtures and test doubles for the notification custom gate test modules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agents._notification_modal_flow import (
    AgentNotificationModalMixin,
)
from sase.notifications import pending_actions


@pytest.fixture(name="gate_home")
def gate_home_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from sase.notification_gates import paths
    from sase.notifications import store

    monkeypatch.setattr(paths, "INTERACTION_REQUESTS_DIR", tmp_path / "requests")
    monkeypatch.setattr(store, "NOTIFICATIONS_DIR", str(tmp_path / "notifications"))
    monkeypatch.setattr(
        store,
        "NOTIFICATIONS_FILE",
        str(tmp_path / "notifications" / "notifications.jsonl"),
    )
    monkeypatch.setattr(
        pending_actions, "PENDING_ACTIONS_PATH", tmp_path / "pending.json"
    )
    monkeypatch.setattr(
        pending_actions,
        "LEGACY_TELEGRAM_PENDING_ACTIONS_PATH",
        tmp_path / "legacy.json",
    )
    store._LOAD_CACHE.clear()
    return tmp_path


def _spec(*, kind: str = "custom") -> dict[str, object]:
    singleton_id = "accept" if kind == "hitl" else "approve"
    return {
        "schema_version": 3,
        "request_id": f"{kind}-ace",
        "kind": kind,
        "producer": {"agent": "test"},
        "payload": {
            "title": "Review guarded work",
            "step_name": "guarded work",
            "output": {"command": "safe-command"},
        },
        "presentation": {
            "sender": "safety-agent",
            "icon": "🛡️",
            "title": "Review guarded work",
            "notes": ["Confirm the guarded command."],
            "preview": "preview.md",
        },
        "query": "(approve AND audit)" if kind == "custom" else singleton_id,
        "primary_branch": (
            ["approve", "audit"] if kind == "custom" else [singleton_id]
        ),
        "options": [
            {
                "id": singleton_id,
                "label": singleton_id.title(),
                "icon": "✅",
                "feedback": "optional" if kind == "custom" else "disabled",
                "command": {"argv": [f"commands/{singleton_id}"]},
                "input_schema": {"type": "object"},
                "result_schema": {"type": "object"},
            },
            *(
                [
                    {
                        "id": "audit",
                        "label": "Write audit record",
                        "icon": "📝",
                        "default_selected": True,
                        "feedback": "disabled",
                        "command": {"argv": ["commands/audit"]},
                        "input_schema": {"type": "object"},
                        "result_schema": {"type": "object"},
                    }
                ]
                if kind == "custom"
                else []
            ),
        ],
        "groups": (
            [{"options": ["approve", "audit"], "label": "Approve", "icon": "✅"}]
            if kind == "custom"
            else []
        ),
        "resources": [
            {
                "path": f"commands/{singleton_id}",
                "role": "command",
                "content": (
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    "value = json.load(sys.stdin)\n"
                    "print(json.dumps({'approved': True, 'input': value}))\n"
                ),
            },
            *(
                [
                    {
                        "path": "commands/audit",
                        "role": "command",
                        "content": "#!/bin/sh\nprintf '{\"audited\": true}\\n'\n",
                    }
                ]
                if kind == "custom"
                else []
            ),
            {
                "path": "preview.md",
                "role": "preview",
                "content": "# Guarded work\n\nReview before proceeding.\n",
            },
        ],
    }


def _sudo_request() -> dict[str, object]:
    executable = "/usr/bin/true"
    return {
        "reason": "Refresh root-owned cache",
        "commands": [{"id": "refresh", "argv": [executable]}],
        "run_as": "root",
        "cwd": "/tmp",
        "env": {},
        "timeout_seconds": 30,
        "stop_policy": "terminate",
        "output_policy": "bounded",
    }


class _TrackedSubmissionApp:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.refresh_count = 0
        self.submitted: list[tuple[tuple[object, ...], dict[str, Any]]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def _submit_durable_proc(self, *args: object, **kwargs: Any) -> object:
        self.submitted.append((args, kwargs))
        completion = SimpleNamespace(
            success=True,
            message="Gate answered with approve",
            payload={"selected_option_ids": ["approve"]},
        )
        kwargs["on_complete"](completion)
        return SimpleNamespace(proc_id="gate-task")


class _NotificationFlowApp(AgentNotificationModalMixin):
    def __init__(self, notification: Any) -> None:
        self.notification = notification
        self.refresh_count = 0
        self.pending_reads = 0
        self.notices: list[tuple[str, str]] = []

    def _read_unread_notification_page_from_provider(self) -> object:
        return SimpleNamespace(notifications=(self.notification,))

    def _read_notification_detail_from_provider(self, _notification_id: str) -> object:
        return SimpleNamespace(notification=self.notification)

    def _read_notification_pending_actions_from_provider(self) -> object:
        self.pending_reads += 1
        return object()

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def push_screen(self, _screen: object, callback: Any) -> None:
        callback(self.notification)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notices.append((message, severity))
