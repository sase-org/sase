"""Task creation modal coverage for the required size contract."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Select, TextArea

from sase.ace.tui.modals.bead_create_modal import BeadCreateModal, BeadCreateResult
from sase.bead.model import PhaseSize


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_create_modal_requires_and_returns_an_explicit_size() -> None:
    dismissed: list[BeadCreateResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadCreateModal("SASE")
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        size = modal.query_one("#bead-create-size", Select)
        assert size.value == ""
        modal.query_one("#bead-create-title", Input).value = "Sized task"
        modal.action_save()
        await pilot.pause()

        assert dismissed == []
        assert size.has_focus

        size.value = PhaseSize.SMALL.value
        modal.action_save()
        await pilot.pause()
        assert dismissed == []
        assert modal.query_one("#bead-create-task-type", Select).has_focus

        modal.query_one("#bead-create-task-type", Select).value = "bug"
        modal.query_one(
            "#bead-create-task-fields", TextArea
        ).text = "location=src/retry.py\nrepro=fails on retry\n"
        modal.action_save()
        await pilot.pause()

    assert dismissed == [
        BeadCreateResult(
            title="Sized task",
            description="",
            size=PhaseSize.SMALL.value,
            ready=False,
            task_type="bug",
            task_type_fields={
                "location": "src/retry.py",
                "repro": "fails on retry",
            },
        )
    ]
