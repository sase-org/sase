"""Behavioral coverage for the typed artifact-link modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input

from sase.ace.tui.modals.artifact_link_modal import (
    ArtifactLinkModal,
    ArtifactLinkRelationChoice,
    ArtifactLinkResult,
)


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_artifact_link_modal_requires_reason_and_returns_result() -> None:
    dismissed: list[ArtifactLinkResult | None] = []
    async with _TestApp().run_test(size=(100, 40)) as pilot:
        modal = ArtifactLinkModal(
            source_label="plan:202608/design.md",
            target_label="bead:sase-tw",
            relations=(ArtifactLinkRelationChoice("implements", "implements"),),
        )
        pilot.app.push_screen(modal, callback=dismissed.append)
        await pilot.pause()

        reason = modal.query_one("#artifact-link-reason", Input)
        modal.action_save()
        await pilot.pause()

        assert dismissed == []
        assert reason.has_focus

        reason.value = "implements the phase acceptance criteria"
        modal.action_save()
        await pilot.pause()

    assert dismissed == [
        ArtifactLinkResult(
            relation="implements",
            reason="implements the phase acceptance criteria",
        )
    ]
