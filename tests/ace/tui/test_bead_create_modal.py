"""Task creation modal coverage for the required size contract."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Select

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

    assert dismissed == [
        BeadCreateResult(
            title="Sized task",
            description="",
            size=PhaseSize.SMALL.value,
            ready=False,
        )
    ]


async def test_create_modal_flag_type_returns_threshold_fields() -> None:
    dismissed: list[BeadCreateResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadCreateModal("SASE")
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        modal.query_one("#bead-create-type", Select).value = "flag"
        modal.query_one("#bead-create-title", Input).value = "Retire switch"
        modal.query_one("#bead-create-flag-key", Input).value = "plugins_enabled"
        modal.query_one("#bead-create-flag-date", Input).value = "2026-12-01"
        modal.query_one("#bead-create-flag-release", Input).value = "0.19.0"
        modal.action_save()
        await pilot.pause()

    assert dismissed == [
        BeadCreateResult(
            title="Retire switch",
            description="",
            size="",
            ready=False,
            issue_type="flag",
            flag_key="plugins_enabled",
            flag_remove_by_date="2026-12-01",
            flag_remove_by_release="0.19.0",
        )
    ]
