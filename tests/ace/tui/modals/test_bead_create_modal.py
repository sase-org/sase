"""Behavioral coverage for required task sizing in ACE creation."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Select

from sase.ace.tui.modals.bead_create_modal import BeadCreateModal, BeadCreateResult


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_create_task_requires_an_explicit_size() -> None:
    dismissed: list[BeadCreateResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadCreateModal("sase")
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        modal.query_one("#bead-create-title", Input).value = "Fix retry race"
        modal.action_save()
        await pilot.pause()

        assert dismissed == []
        assert modal.query_one("#bead-create-size", Select).has_focus


async def test_create_task_returns_the_selected_size() -> None:
    dismissed: list[BeadCreateResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadCreateModal("sase")
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        modal.query_one("#bead-create-title", Input).value = "Fix retry race"
        modal.query_one("#bead-create-size", Select).value = "medium"
        modal.action_save()
        await pilot.pause()

    assert dismissed == [
        BeadCreateResult(
            title="Fix retry race",
            description="",
            size="medium",
            ready=False,
        )
    ]
