"""Tracked TUI execution coverage for neutral plan gates."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest

from sase.ace.tui.actions.agents._notification_modals import (
    _plan_approval_status,
    submit_neutral_plan_response,
)
from sase.ace.tui.modals.plan_approval_modal import (
    _plan_approval_result_for_choice,
)
from sase.notification_gates import paths
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.plan_gate import create_plan_approval_gate
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture()
def gate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
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
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    store._LOAD_CACHE.clear()
    return tmp_path


class _TrackedPlanApp:
    def __init__(self) -> None:
        self.completion: object | None = None
        self.notifications: list[tuple[str, str]] = []
        self.refresh_count = 0

    def notify(
        self,
        message: str,
        *,
        severity: str = "information",
        **_kwargs: object,
    ) -> None:
        self.notifications.append((message, severity))

    def _refresh_notification_count(self) -> None:
        self.refresh_count += 1

    def _submit_tracked_task(self, *args: Any, **kwargs: Any) -> object:
        self.completion = args[3]()
        kwargs["on_complete"](self.completion)
        return SimpleNamespace(task_id="plan-gate-task")


@pytest.mark.parametrize(
    ("choice", "expected_choice_id", "expected_extra_ids", "selection_provided"),
    [
        ("approve", "approve", ["commit_plan", "run_coder"], True),
        ("tale", "tale", [], False),
    ],
)
def test_neutral_plan_submission_executes_actual_modal_choice(
    gate_home: Path,
    choice: Literal["approve", "tale"],
    expected_choice_id: str,
    expected_extra_ids: list[str],
    selection_provided: bool,
) -> None:
    plan = gate_home / f"{choice}.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_plan_approval_gate(plan, f"tui-{choice}")
    [notification] = load_notifications()
    result = _plan_approval_result_for_choice(
        choice,
        commit_plan=True,
        run_coder=True,
    )
    app = _TrackedPlanApp()

    submitted = submit_neutral_plan_response(app, notification, None, result)

    assert submitted is True
    assert getattr(app.completion, "success", False) is True
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["choice_id"] == expected_choice_id
    assert response["selected_extra_ids"] == expected_extra_ids
    assert response["extras_selection_provided"] is selection_provided
    assert _plan_approval_status(result) == "TALE APPROVED"
    assert app.notifications == []
    assert app.refresh_count == 1
