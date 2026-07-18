"""Tracked TUI execution coverage for neutral plan gates."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from textual.app import App
from textual.widgets import Button

from sase.ace.tui.actions.agents._notification_modals import (
    _load_neutral_plan_modal_data,
    _plan_approval_status,
    handle_plan_approval,
    submit_neutral_plan_response,
)
from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalModal,
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


class _PlanModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def test_plan_modal_loader_projects_tale_branch_model(gate_home: Path) -> None:
    plan = gate_home / "tale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_plan_approval_gate(plan, "tui-branches")
    [notification] = load_notifications()

    loaded = _load_neutral_plan_modal_data(notification)

    assert loaded.default_choice == "tale"
    assert loaded.gate.branches == (
        ("approve", "commit"),
        ("reject",),
        ("feedback",),
    )
    assert loaded.gate.groups[0].label == "Approve"
    assert loaded.gate.groups[0].icon == "✅"
    assert "tier: tale" in loaded.plan_content


async def test_plan_modal_bundle_loading_stays_off_the_message_pump(
    gate_home: Path,
) -> None:
    plan = gate_home / "async-tale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_plan_approval_gate(plan, "tui-async-branches")
    [notification] = load_notifications()

    async with _PlanModalApp().run_test(size=(100, 34)) as pilot:
        assert handle_plan_approval(pilot.app, notification) is True
        for _ in range(20):
            await pilot.pause()
            if isinstance(pilot.app.screen, PlanApprovalModal):
                break

        modal = pilot.app.screen
        assert isinstance(modal, PlanApprovalModal)
        assert modal._plan_content is not None
        assert modal._gate.branches[0] == ("approve", "commit")
        assert "Launch coder agent" in str(
            modal.query_one("#gate-option-0-0", Button).label
        )
        assert "Approve" in str(modal.query_one("#gate-group-submit-0", Button).label)


@pytest.mark.parametrize(
    ("choice", "commit_plan", "expected_option_ids", "expected_status"),
    [
        ("approve", False, ["approve"], "PLAN APPROVED"),
        ("tale", True, ["approve", "commit"], "TALE APPROVED"),
    ],
)
def test_neutral_plan_submission_executes_actual_modal_choice(
    gate_home: Path,
    choice: Literal["approve", "tale"],
    commit_plan: bool,
    expected_option_ids: list[str],
    expected_status: str,
) -> None:
    plan = gate_home / f"{choice}.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_plan_approval_gate(plan, f"tui-{choice}")
    [notification] = load_notifications()
    result = _plan_approval_result_for_choice(
        choice,
        commit_plan=commit_plan,
        run_coder=True,
    )
    app = _TrackedPlanApp()

    submitted = submit_neutral_plan_response(app, notification, None, result)

    assert submitted is True
    assert getattr(app.completion, "success", False) is True
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["selected_option_ids"] == expected_option_ids
    assert [item["id"] for item in response["option_results"]] == expected_option_ids
    assert _plan_approval_status(result) == expected_status
    assert app.notifications == []
    assert app.refresh_count == 1
