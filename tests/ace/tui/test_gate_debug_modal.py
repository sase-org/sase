"""Interaction coverage for Gate Debug entry points and lifecycle."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Input

from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
)
from sase.ace.tui.modals.gate_debug_modal import GateDebugModal
from sase.ace.tui.modals.gate_branch_controls import (
    GateBranchControls,
    GateBranchData,
)
from sase.ace.tui.modals.launch_approval_modal import LaunchApprovalModal
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
from sase.ace.tui.modals.user_question_modal import UserQuestionModal
from sase.ace.tui.modals.workflow_hitl_modal import (
    WorkflowHITLInput,
    WorkflowHITLModal,
)
from sase.notification_gates.debug import debug_context_from_notification
from sase.notification_gates.models import GateGroup, GateOption
from sase.notifications.models import Notification


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def _notification(tmp_path: Path) -> Notification:
    root = tmp_path / "missing-gate"
    return Notification(
        id="debug-notification",
        timestamp="2026-07-17T10:00:00+00:00",
        sender="test-agent",
        icon="🛡️",
        action="CustomGate",
        action_data={
            "request_id": "debug-request",
            "request_kind": "custom",
            "bundle_path": str(root),
        },
    )


def _custom_data(*, feedback: str = "disabled") -> CustomGateModalData:
    options = tuple(
        GateOption.from_mapping(
            {
                "id": option_id,
                "label": option_id.title(),
                "command": {"argv": [f"commands/{option_id}"]},
                "feedback": feedback if option_id == "approve" else "disabled",
            },
            index,
            default_feedback="optional",
        )
        for index, option_id in enumerate(("approve", "audit"))
    )
    return CustomGateModalData(
        request_id="debug-request",
        sender="test-agent",
        icon="🛡️",
        notes=("Review this gate",),
        attachments=(),
        preview_name=None,
        preview_text=None,
        gate=GateBranchData(
            query="approve AND audit",
            options=options,
            groups=(GateGroup(("approve", "audit"), "Approve", None),),
            branches=(("approve", "audit"),),
            primary_branch=("approve", "audit"),
        ),
    )


def _gate_modals(tmp_path: Path) -> list[ModalScreen[Any]]:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")
    context = debug_context_from_notification(_notification(tmp_path))
    return [
        CustomGateModal(_custom_data(), debug_context=context),
        PlanApprovalModal(str(plan), debug_context=context),
        LaunchApprovalModal(
            preview_file=str(plan),
            request_id="debug-request",
            debug_context=context,
        ),
        UserQuestionModal(
            [{"question": "Ship it?", "options": [{"label": "Yes"}]}],
            debug_context=context,
        ),
        WorkflowHITLModal(
            WorkflowHITLInput(
                step_name="review",
                step_type="agent",
                output={"ok": True},
                workflow_name="test",
            ),
            debug_context=context,
        ),
    ]


@pytest.mark.parametrize("modal_index", range(5))
async def test_d_opens_and_closes_debug_from_every_gate_modal(
    tmp_path: Path, modal_index: int
) -> None:
    modal = _gate_modals(tmp_path)[modal_index]

    async with _TestApp().run_test(size=(110, 36)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        assert isinstance(pilot.app.screen, GateDebugModal)

        await pilot.press("d")
        await pilot.pause()
        assert pilot.app.screen is modal


async def test_closing_debug_preserves_custom_gate_form_state(tmp_path: Path) -> None:
    context = debug_context_from_notification(_notification(tmp_path))
    modal = CustomGateModal(_custom_data(feedback="required"), debug_context=context)

    async with _TestApp().run_test(size=(110, 36)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        feedback = modal.query_one("#gate-feedback-input", Input)
        feedback.value = "Keep this answer"
        controls = modal.query_one(GateBranchControls)
        assert controls.selected_option_ids(0) == ("approve", "audit")

        modal.action_debug_view()
        await pilot.pause()
        assert isinstance(pilot.app.screen, GateDebugModal)
        await pilot.press("escape")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert feedback.value == "Keep this answer"
        assert controls.selected_option_ids(0) == ("approve", "audit")


async def test_notification_row_opens_debug_even_without_gate_bundle() -> None:
    notification = Notification(
        id="ordinary",
        timestamp="2026-07-17T10:00:00+00:00",
        sender="test",
        action="JumpToAgent",
        notes=["ordinary row"],
    )

    async with _TestApp().run_test(size=(110, 36)) as pilot:
        modal = NotificationModal([notification])
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        debug = pilot.app.screen
        assert isinstance(debug, GateDebugModal)
        for _ in range(10):
            if debug._snapshot is not None:
                break
            await pilot.pause()
        assert debug._snapshot is not None
        assert "No gate bundle attached" in debug._snapshot.overview.body


async def test_tabs_and_copy_actions_use_prebuilt_snapshot(tmp_path: Path) -> None:
    context = debug_context_from_notification(_notification(tmp_path))
    modal = GateDebugModal(context)

    async with _TestApp().run_test(size=(110, 36)) as pilot:
        pilot.app.push_screen(modal)
        for _ in range(10):
            await pilot.pause()
            if modal._snapshot is not None:
                break
        assert modal._snapshot is not None

        modal.action_next_tab()
        assert modal._tab_index == 1
        modal.action_previous_tab()
        assert modal._tab_index == 0

        with patch(
            "sase.ace.tui.modals.gate_debug_modal.copy_to_system_clipboard",
            return_value=True,
        ) as copy:
            modal.action_copy_tab()
            modal.action_copy_bundle_path()

        assert copy.call_args_list[0].args == (modal._snapshot.overview.raw_text,)
        assert copy.call_args_list[1].args == (str(tmp_path / "missing-gate"),)


def test_d_without_context_shows_quiet_warning() -> None:
    modal = CustomGateModal(_custom_data())
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal.action_debug_view()

    modal.notify.assert_called_once_with(
        "Gate debug context is unavailable for this view",
        severity="warning",
    )


async def test_dismissed_modal_never_applies_late_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = threading.Event()
    release = threading.Event()
    original = __import__(
        "sase.ace.tui.modals.gate_debug_modal", fromlist=["build_gate_debug_snapshot"]
    ).build_gate_debug_snapshot

    def delayed(*args: object, **kwargs: object) -> object:
        started.set()
        release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        "sase.ace.tui.modals.gate_debug_modal.build_gate_debug_snapshot", delayed
    )
    modal = GateDebugModal(debug_context_from_notification(_notification(tmp_path)))

    async with _TestApp().run_test(size=(110, 36)) as pilot:
        pilot.app.push_screen(modal)
        for _ in range(20):
            await pilot.pause()
            if started.is_set():
                break
        assert started.is_set()
        await pilot.press("d")
        release.set()
        await pilot.pause()
        await pilot.pause()

    assert modal._snapshot is None
