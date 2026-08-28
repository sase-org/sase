"""Tracked TUI execution coverage for neutral plan gates."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import patch

import pytest
from textual.app import App
from textual.widgets import Button

from sase.ace.testing import wait_for
from sase.ace.tui.actions.agents._notification_modals import (
    _load_neutral_plan_modal_data,
    handle_plan_approval,
    submit_neutral_plan_response,
)
from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalModal,
    PlanApprovalResult,
)
from sase.ace.tui.modals.plan_approval_results import plan_approval_result_for_choice
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.notification_gates import paths
from sase.notification_gates.service import create_gate
from sase.notifications import pending_actions
from sase.notifications.store import load_notifications
from sase.plan_gate import build_plan_approval_gate_spec
from tests._plan_gate_fixtures import (  # noqa: F401
    plan_host_archive_stub,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


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

    def _submit_session_worker(self, *args: Any, **kwargs: Any) -> object:
        self.completion = args[1]()
        kwargs["on_complete"](self.completion)
        return SimpleNamespace(proc_id="plan-gate-task")


class _PlanModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def _has_button(modal: PlanApprovalModal, selector: str) -> bool:
    try:
        modal.query_one(selector, Button)
    except Exception:
        return False
    return True


def test_plan_modal_loader_projects_tale_branch_model(gate_home: Path) -> None:
    plan = gate_home / "tale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_gate(build_plan_approval_gate_spec(plan, "tui-branches"))
    [notification] = load_notifications()

    loaded = _load_neutral_plan_modal_data(notification)

    assert loaded.default_choice == "tale"
    assert loaded.gate.branches == (
        ("approve", "commit"),
        ("reject",),
        ("feedback",),
    )
    assert loaded.gate.groups[0].label == "Tale"
    assert loaded.gate.groups[0].icon == "✅"
    assert loaded.gate.options[0].label == "Launch coder agent"
    assert loaded.gate.options[0].icon == "🚀"
    assert "tier: tale" in loaded.plan_content


async def test_plan_modal_bundle_loading_stays_off_the_message_pump(
    gate_home: Path,
) -> None:
    plan = gate_home / "async-tale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_gate(build_plan_approval_gate_spec(plan, "tui-async-branches"))
    [notification] = load_notifications()

    async with _PlanModalApp().run_test(size=(100, 34)) as pilot:
        assert handle_plan_approval(pilot.app, notification) is True
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, PlanApprovalModal))

        modal = pilot.app.screen
        assert isinstance(modal, PlanApprovalModal)
        assert modal._plan_content is not None
        assert modal._plan_file == str(
            paths.INTERACTION_REQUESTS_DIR / "plan" / "tui-async-branches" / "plan.md"
        )
        assert modal._copy_plan_path == str(plan)
        assert modal._gate.branches[0] == ("approve", "commit")
        await wait_for(pilot, lambda: _has_button(modal, "#gate-option-0-0"))
        coder_label = str(modal.query_one("#gate-option-0-0", Button).label)
        assert "🚀" in coder_label
        assert "Launch coder agent" in coder_label
        assert "Commit plan file to the plans sidecar" in str(
            modal.query_one("#gate-option-0-1", Button).label
        )
        assert "Tale" in str(modal.query_one("#gate-group-submit-0", Button).label)
        assert str(modal.query_one("#gate-group-submit-0", Button).label).startswith(
            "1 "
        )
        assert not coder_label.startswith("1 ")


async def test_tale_plan_modal_renders_no_raw_editor_for_host_collected_properties(
    gate_home: Path,
) -> None:
    """A real plan gate's coder_prompt/coder_model/epic_launch_mode never get a
    duplicate raw YAML box: the plan modal's own controls already collect them.
    """
    plan = gate_home / "tale-no-raw.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_gate(build_plan_approval_gate_spec(plan, "tui-no-raw-tale"))
    [notification] = load_notifications()

    async with _PlanModalApp().run_test(size=(100, 34)) as pilot:
        assert handle_plan_approval(pilot.app, notification) is True
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, PlanApprovalModal))

        modal = pilot.app.screen
        assert isinstance(modal, PlanApprovalModal)
        raw_ids = [
            widget.id
            for widget in modal.query("*")
            if widget.id and "-raw-" in widget.id
        ]
        assert raw_ids == []
        assert not modal.query("#gate-feedback-input")


async def test_epic_plan_modal_renders_canonical_singleton_label(
    gate_home: Path,
) -> None:
    plan = gate_home / "epic.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    create_gate(build_plan_approval_gate_spec(plan, "tui-epic-label"))
    [notification] = load_notifications()

    async with _PlanModalApp().run_test(size=(100, 34)) as pilot:
        assert handle_plan_approval(pilot.app, notification) is True
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, PlanApprovalModal))

        modal = pilot.app.screen
        assert isinstance(modal, PlanApprovalModal)
        assert modal._default_choice == "epic"
        assert modal._gate.options[0].id == "approve"
        assert modal._gate.options[0].label == "Epic"
        assert modal._gate.options[0].icon == "✅"
        await wait_for(pilot, lambda: _has_button(modal, "#gate-singleton-0"))
        epic_label = str(modal.query_one("#gate-singleton-0", Button).label)
        assert epic_label.startswith("1 ")
        assert "✅" in epic_label
        assert "Epic" in epic_label


async def test_tale_feedback_option_opens_the_input_panel(gate_home: Path) -> None:
    plan = gate_home / "tale-feedback.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    create_gate(build_plan_approval_gate_spec(plan, "tui-feedback-panel"))
    [notification] = load_notifications()

    async with _PlanModalApp().run_test(size=(100, 34)) as pilot:
        assert handle_plan_approval(pilot.app, notification) is True
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, PlanApprovalModal))
        modal = pilot.app.screen
        assert isinstance(modal, PlanApprovalModal)
        await wait_for(pilot, lambda: _has_button(modal, "#gate-singleton-2"))
        await pilot.press("3")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = pilot.app.screen
        assert isinstance(panel, GateInputPanel)
        assert panel.query("#gate-input-note")
        raw_ids = [
            widget.id
            for widget in panel.query("*")
            if widget.id and "-raw-" in widget.id
        ]
        assert raw_ids == []
        panel.query_one("#gate-input-note", VimTextArea).text = "needs more detail"
        panel.action_cancel()
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, PlanApprovalModal))


@pytest.mark.parametrize(
    ("choice", "commit_plan", "expected_option_ids"),
    [
        ("approve", False, ["approve"]),
        ("tale", True, ["approve", "commit"]),
    ],
)
def test_neutral_plan_submission_executes_actual_modal_choice(
    gate_home: Path,
    choice: Literal["approve", "tale"],
    commit_plan: bool,
    expected_option_ids: list[str],
    stub_host_plan_archive: Path,
) -> None:
    plan = gate_home / f"{choice}.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, f"tui-{choice}"))
    [notification] = load_notifications()
    result = plan_approval_result_for_choice(
        choice,
        commit_plan=commit_plan,
        run_coder=True,
    )
    app = _TrackedPlanApp()

    submitted = submit_neutral_plan_response(app, notification, None, result)

    assert submitted is True
    assert getattr(app.completion, "success", False) is True
    if commit_plan:
        assert stub_host_plan_archive.is_file()
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["selected_option_ids"] == expected_option_ids
    assert [item["id"] for item in response["option_results"]] == expected_option_ids
    assert app.notifications == []
    assert app.refresh_count == 1


def test_neutral_tale_submission_merges_shared_and_per_option_inputs(
    gate_home: Path,
    stub_host_plan_archive: Path,
) -> None:
    """A declared option_inputs mapping merges over the shared input_data.

    No built-in plan option declares ``inputs:`` yet, but the tale schema
    already accepts ``coder_prompt``/``coder_model`` on ``approve`` and
    ``commit``, so this exercises the merge path a future declared-input
    plan option will use without needing one to exist yet.
    """
    plan = gate_home / "tale-inputs.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "tui-tale-inputs"))
    [notification] = load_notifications()
    result = PlanApprovalResult(
        action="approve",
        commit_plan=True,
        run_coder=True,
        coder_prompt="do the thing",
        choice="tale",
        selected_option_ids=("approve", "commit"),
        option_inputs={"approve": {"coder_model": "opus"}},
    )
    app = _TrackedPlanApp()

    submitted = submit_neutral_plan_response(app, notification, None, result)

    assert submitted is True
    assert getattr(app.completion, "success", False) is True
    response = json.loads(gate.response_path.read_text(encoding="utf-8"))
    assert response["option_inputs"]["approve"] == {
        "coder_prompt": "do the thing",
        "coder_model": "opus",
    }
    assert response["option_inputs"]["commit"] == {"coder_prompt": "do the thing"}
    # The merge path submits per-option; input_data stays the executor's
    # legacy shared-value field and is empty here.
    assert response["input"] == {}


def test_copy_actions_never_expose_collected_input_values(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action_copy_plan/action_copy_plan_path only ever read plan content/path.

    Neither has an input-copy action; this pins that neither one starts
    reaching into anything option_inputs-shaped.
    """
    plan = gate_home / "copy-guard.md"
    plan.write_text("# Plan\n\nDo the thing.\n", encoding="utf-8")
    modal = PlanApprovalModal(str(plan), default_choice="tale")
    captured: dict[str, object] = {}

    def fake_schedule(
        _owner: object, value: object, *, task_name: str, **_kwargs: object
    ) -> None:
        captured[task_name] = value
        return None

    monkeypatch.setattr(
        "sase.ace.tui.modals.plan_approval_modal.schedule_copy_delivery",
        fake_schedule,
    )

    modal.action_copy_plan()
    modal.action_copy_plan_path()

    content = captured["sase-copy-plan-contents"]
    resolved_content = content() if callable(content) else content
    assert resolved_content == "# Plan\n\nDo the thing.\n"
    assert captured["sase-copy-plan-path"] == str(plan)


def test_neutral_epic_submission_records_ace_origin(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = gate_home / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(workspace))
    plan = gate_home / "epic-origin.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    create_gate(build_plan_approval_gate_spec(plan, "tui-epic-origin"))
    [notification] = load_notifications()
    result = plan_approval_result_for_choice("epic")
    app = _TrackedPlanApp()

    with (
        patch(
            "sase.bead.epic_launch.resolve_epic_launch_project",
            return_value="canonical",
        ),
        patch(
            "sase.running_field.get_workspace_directory",
            return_value=str(workspace),
        ),
        patch(
            "sase.bead.cli_work_from_plan.require_epic_launch_store_health",
        ),
        patch(
            "sase.bead.epic_launch.start_epic_launch_monitor",
            return_value=SimpleNamespace(monitor_id="mon-ace"),
        ) as start_launch,
    ):
        submitted = submit_neutral_plan_response(app, notification, None, result)

    assert submitted is True
    assert getattr(app.completion, "success", False) is True
    start_launch.assert_called_once()
    assert start_launch.call_args.kwargs["origin"] == "ace"
