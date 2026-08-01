"""Behavioral coverage for close-with-reason bead modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Checkbox, Input, Select, Static

from sase.ace.tui.modals.bead_close_modal import BeadCloseModal, BeadCloseResult
from sase.bead.model import BeadTier, Issue, IssueType, Resolution


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_close_requires_reason_and_previews_descendants() -> None:
    dismissed: list[BeadCloseResult | None] = []
    issue = Issue(
        "sase-epic",
        "Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadCloseModal(
            issue,
            unclosed_descendants=("sase-epic.1", "sase-epic.2"),
        )
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        descendants = modal.query_one("#bead-close-descendants", Static)
        assert "sase-epic.1" in str(descendants.render())
        force = modal.query_one("#bead-close-force", Checkbox)
        assert not force.disabled

        modal.action_save()
        await pilot.pause()
        assert dismissed == []


async def test_force_selects_non_done_resolution_and_returns_close_contract() -> None:
    dismissed: list[BeadCloseResult | None] = []
    issue = Issue(
        "sase-epic",
        "Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = BeadCloseModal(issue, unclosed_descendants=("sase-epic.1",))
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        modal.query_one("#bead-close-force", Checkbox).value = True
        await pilot.pause()
        assert modal.query_one("#bead-close-resolution", Select).value == (
            Resolution.CANCELED.value
        )
        modal.query_one("#bead-close-reason", Input).value = "Superseded work"
        modal.action_save()
        await pilot.pause()

    assert dismissed == [
        BeadCloseResult(
            resolution="canceled",
            reason="Superseded work",
            note=None,
            force=True,
        )
    ]
