"""Behavioral coverage for required task sizing in ACE creation."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Select, TextArea

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
        modal.query_one("#bead-create-task-type", Select).value = "bug"
        modal.query_one(
            "#bead-create-task-fields", TextArea
        ).text = "location=src/retry.py\nrepro=fails on retry\n"
        modal.action_save()
        await pilot.pause()

    assert dismissed == [
        BeadCreateResult(
            title="Fix retry race",
            description="",
            size="medium",
            ready=False,
            task_type="bug",
            task_type_fields={
                "location": "src/retry.py",
                "repro": "fails on retry",
            },
        )
    ]


async def test_create_flag_returns_flag_metadata_without_size() -> None:
    dismissed: list[BeadCreateResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadCreateModal("sase")
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        modal.query_one("#bead-create-type", Select).value = "flag"
        modal.query_one("#bead-create-title", Input).value = "Remove plugin switch"
        modal.query_one("#bead-create-flag-key", Input).value = "plugins_enabled"
        modal.query_one("#bead-create-flag-date", Input).value = "2026-12-01"
        modal.query_one("#bead-create-flag-release", Input).value = "0.19.0"
        modal.action_save()
        await pilot.pause()

    assert dismissed == [
        BeadCreateResult(
            title="Remove plugin switch",
            description="",
            size="",
            ready=False,
            issue_type="flag",
            flag_key="plugins_enabled",
            flag_remove_by_date="2026-12-01",
            flag_remove_by_release="0.19.0",
        )
    ]
