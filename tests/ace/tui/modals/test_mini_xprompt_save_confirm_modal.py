"""Behavior of the mini-xprompt save confirmation panel."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets import Static

from sase.ace.tui.modals.mini_xprompt_save_confirm_modal import (
    MiniXPromptSaveConfirmModal,
    MiniXPromptSaveConfirmState,
)
from sase.xprompt.save import SaveTargetFormat


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


@asynccontextmanager
async def _open_modal(
    state: MiniXPromptSaveConfirmState,
    results: list[str | None],
) -> AsyncIterator[tuple[_ModalApp, Pilot[None]]]:
    app = _ModalApp()
    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(MiniXPromptSaveConfirmModal(state), results.append)
        await pilot.pause()
        yield app, pilot


def _static_text(static: Static) -> str:
    renderable = getattr(static, "_Static__content", static.render())
    if isinstance(renderable, Syntax):
        return renderable.code
    return getattr(renderable, "plain", str(renderable))


async def test_create_markdown_opens_on_draft_and_saves() -> None:
    results: list[str | None] = []
    async with _open_modal(
        MiniXPromptSaveConfirmState(
            name="review",
            display_path="~/sase/xprompts/review.md",
            body="Check this",
            frontmatter="---\ndescription: Review\n---",
            target_format=SaveTargetFormat.MARKDOWN,
            entry_name=None,
            exists=False,
            existing_markdown=None,
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, MiniXPromptSaveConfirmModal)
        header = _static_text(
            modal.query_one("#mini-xprompt-save-confirm-header", Static)
        )
        preview = _static_text(
            modal.query_one("#mini-xprompt-save-confirm-preview", Static)
        )
        assert "Create in ~/sase/xprompts/review.md" in header
        assert "[Draft]" in header
        assert "description: Review" in preview
        assert preview.endswith("Check this\n")

        await pilot.press("enter")
        await pilot.pause()

    assert results == ["save"]


async def test_config_preview_renders_frontmatter_fields() -> None:
    results: list[str | None] = []
    async with _open_modal(
        MiniXPromptSaveConfirmState(
            name="review",
            display_path="sase.yml:review",
            body="Check this",
            frontmatter="---\ndescription: Review\ninput:\n  path: path\n---",
            target_format=SaveTargetFormat.CONFIG,
            entry_name="review",
            exists=False,
            existing_markdown=None,
        ),
        results,
    ) as (app, _pilot):
        modal = app.screen
        assert isinstance(modal, MiniXPromptSaveConfirmModal)
        preview = _static_text(
            modal.query_one("#mini-xprompt-save-confirm-preview", Static)
        )
        assert "xprompts:" in preview
        assert "  review:" in preview
        assert "    description: Review" in preview
        assert "    input:" in preview
        assert "    content: |-" in preview


async def test_changed_on_disk_requires_explicit_overwrite() -> None:
    results: list[str | None] = []
    async with _open_modal(
        MiniXPromptSaveConfirmState(
            name="review",
            display_path="review.md",
            body="new body",
            frontmatter="",
            target_format=SaveTargetFormat.MARKDOWN,
            entry_name=None,
            exists=True,
            existing_markdown="old body\n",
            changed_on_disk=True,
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, MiniXPromptSaveConfirmModal)
        verdict = _static_text(
            modal.query_one("#mini-xprompt-save-confirm-verdict", Static)
        )
        assert "changed on disk" in verdict

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, MiniXPromptSaveConfirmModal)
        assert results == []

        await pilot.press("o")
        await pilot.pause()

    assert results == ["overwrite"]


async def test_real_swarm_separator_blocks_save() -> None:
    results: list[str | None] = []
    async with _open_modal(
        MiniXPromptSaveConfirmState(
            name="review",
            display_path="review.md",
            body="first\n---\nsecond",
            frontmatter="",
            target_format=SaveTargetFormat.MARKDOWN,
            entry_name=None,
            exists=False,
            existing_markdown=None,
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, MiniXPromptSaveConfirmModal)
        await pilot.press("enter")
        await pilot.pause()
        verdict = _static_text(
            modal.query_one("#mini-xprompt-save-confirm-verdict", Static)
        )
        assert "swarm separator" in verdict
        assert isinstance(app.screen, MiniXPromptSaveConfirmModal)

    assert results == []
