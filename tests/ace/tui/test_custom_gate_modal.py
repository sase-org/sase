"""Interaction coverage for the generic custom-gate modal."""

from __future__ import annotations

from textual.app import App
from textual.widgets import Button, Input, SelectionList

from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
    CustomGateModalResult,
    GateExtrasSelectionList,
)
from sase.notification_gates.models import GateChoice


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def _choice(
    choice_id: str,
    label: str,
    *,
    feedback: str = "disabled",
    extras: list[dict[str, object]] | None = None,
) -> GateChoice:
    return GateChoice.from_mapping(
        {
            "id": choice_id,
            "label": label,
            "command": {"argv": [f"commands/{choice_id}"]},
            "feedback": feedback,
            "extras": extras or [],
        },
        0,
        default_feedback="optional",
    )


def _data(*choices: GateChoice) -> CustomGateModalData:
    return CustomGateModalData(
        request_id="guarded-work",
        sender="safety-agent",
        icon="🛡️",
        notes=("Review the command and select any auditable follow-ups.",),
        attachments=("preview.md",),
        preview_name="preview.md",
        preview_text="# Preview\n\nThe command changes local configuration.",
        choices=choices,
    )


async def test_required_feedback_blocks_submit_and_keeps_default_extras() -> None:
    choice = _choice(
        "proceed",
        "Proceed safely",
        feedback="required",
        extras=[
            {
                "id": "audit",
                "label": "Write audit record",
                "icon": "📝",
                "default_selected": True,
                "command": {"argv": ["commands/audit"]},
            },
            {
                "id": "notify",
                "label": "Notify the team",
                "command": {"argv": ["commands/notify"]},
            },
        ],
    )
    results: list[CustomGateModalResult | None] = []

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        modal = CustomGateModal(_data(choice))
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        extras = modal.query_one("#custom-gate-extras-0", SelectionList)
        assert tuple(extras.selected) == ("audit",)
        assert modal.query_one("#custom-gate-submit", Button).disabled is True

        modal.action_submit()
        await pilot.pause()
        assert pilot.app.screen is modal
        assert results == []

        modal.query_one(
            "#custom-gate-feedback-0", Input
        ).value = "Approved after review"
        await pilot.pause()
        assert modal.query_one("#custom-gate-submit", Button).disabled is False

        modal.action_submit()
        await pilot.pause()

    assert results == [
        CustomGateModalResult(
            choice_id="proceed",
            selected_extra_ids=("audit",),
            feedback="Approved after review",
        )
    ]


async def test_choice_navigation_switches_feedback_and_submit_target() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            _choice("approve", "Approve", feedback="optional"),
            _choice("cancel", "Cancel operation"),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        modal.action_next_choice()
        await pilot.pause()
        assert modal._choice_index == 1
        assert modal.query_one("#custom-gate-submit", Button).disabled is False
        modal.action_submit()
        await pilot.pause()

    assert results == [CustomGateModalResult("cancel", (), None)]


async def test_command_keymaps_work_from_initial_button_focus() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            _choice(
                "proceed",
                "Proceed",
                extras=[
                    {
                        "id": "audit",
                        "label": "Write audit record",
                        "default_selected": True,
                        "command": {"argv": ["commands/audit"]},
                    },
                    {
                        "id": "notify",
                        "label": "Notify the team",
                        "command": {"argv": ["commands/notify"]},
                    },
                ],
            )
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        extras = modal.query_one("#custom-gate-extras-0", GateExtrasSelectionList)
        assert pilot.app.focused is modal.query_one("#custom-gate-choice-0", Button)
        assert extras.highlighted == 0

        await pilot.press("j")
        assert pilot.app.focused is extras
        assert extras.highlighted == 1

        await pilot.press("space")
        assert extras.selected_extra_ids == ("audit", "notify")

        await pilot.press("k")
        assert extras.highlighted == 0
        await pilot.press("space")
        assert extras.selected_extra_ids == ("notify",)

        await pilot.press("ctrl+s")

    assert results == [CustomGateModalResult("proceed", ("notify",), None)]


async def test_command_keymaps_only_target_active_choice() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            _choice(
                "approve",
                "Approve",
                extras=[
                    {
                        "id": "audit",
                        "label": "Write audit record",
                        "default_selected": True,
                        "command": {"argv": ["commands/audit"]},
                    }
                ],
            ),
            _choice("cancel", "Cancel operation"),
            _choice(
                "revise",
                "Revise",
                extras=[
                    {
                        "id": "notify",
                        "label": "Notify the team",
                        "command": {"argv": ["commands/notify"]},
                    }
                ],
            ),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        approve_extras = modal.query_one(
            "#custom-gate-extras-0", GateExtrasSelectionList
        )
        revise_extras = modal.query_one(
            "#custom-gate-extras-2", GateExtrasSelectionList
        )

        await pilot.press("right")
        assert modal._choice_index == 1
        cancel_button = modal.query_one("#custom-gate-choice-1", Button)
        assert pilot.app.focused is cancel_button

        await pilot.press("j", "k", "space")
        assert pilot.app.focused is cancel_button
        assert approve_extras.selected_extra_ids == ("audit",)
        assert revise_extras.selected_extra_ids == ()

        await pilot.press("right", "space")
        assert modal._choice_index == 2
        assert pilot.app.focused is revise_extras
        assert revise_extras.selected_extra_ids == ("notify",)
        assert approve_extras.selected_extra_ids == ("audit",)

        await pilot.press("ctrl+s")

    assert results == [CustomGateModalResult("revise", ("notify",), None)]


async def test_feedback_input_keeps_printable_command_keys() -> None:
    modal = CustomGateModal(
        _data(
            _choice(
                "approve",
                "Approve",
                feedback="optional",
                extras=[
                    {
                        "id": "audit",
                        "label": "Write audit record",
                        "default_selected": True,
                        "command": {"argv": ["commands/audit"]},
                    }
                ],
            )
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        feedback = modal.query_one("#custom-gate-feedback-0", Input)
        extras = modal.query_one("#custom-gate-extras-0", GateExtrasSelectionList)
        feedback.focus()
        await pilot.press("j", "k", "space")

        assert pilot.app.focused is feedback
        assert feedback.value == "jk "
        assert extras.highlighted == 0
        assert extras.selected_extra_ids == ("audit",)
