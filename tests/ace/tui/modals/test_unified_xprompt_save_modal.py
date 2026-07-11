"""Unified save-as modal target/collision behavior."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.unified_xprompt_save_modal import (
    UnifiedXPromptSaveModal,
    _UnifiedSaveLocation,
)
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.ace.tui.modals.xprompt_save_target_modal import XPromptSaveTarget
from sase.xprompt.save import SaveTargetFormat


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


async def test_collision_is_previewed_and_enter_returns_overwrite_target(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "xprompts"
    directory.mkdir()
    path = directory / "review.md"
    path.write_text("old definition", encoding="utf-8")
    row = _UnifiedSaveLocation(
        XPromptLocation("Test", str(directory), "directory"),
        {"review": "old definition"},
    )
    app = _ModalApp()
    results: list[XPromptSaveTarget | None] = []

    async with app.run_test(size=(100, 35)) as pilot:
        app.push_screen(
            UnifiedXPromptSaveModal([row], initial_name="review"), results.append
        )
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UnifiedXPromptSaveModal)
        assert (
            "Overwrite #review"
            in modal.query_one("#unified-save-status", Static).render().plain
        )
        await pilot.press("enter")
        await pilot.pause()

    target = results[0]
    assert target is not None
    assert target.kind == "write"
    assert target.exists
    assert target.path == str(path)
    assert target.target_format is SaveTargetFormat.MARKDOWN
