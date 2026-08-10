"""Behavior of the snippet-pane save confirmation panel."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets import Static

from sase.ace.tui.modals.snippet_save_confirm_modal import (
    SnippetSaveConfirmModal,
    SnippetSaveConfirmState,
)


class _ModalApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield Static("")


@asynccontextmanager
async def _open_modal(
    state: SnippetSaveConfirmState,
    results: list[str | None],
) -> AsyncIterator[tuple[_ModalApp, Pilot[None]]]:
    app = _ModalApp()
    async with app.run_test(size=(100, 28)) as pilot:
        app.push_screen(SnippetSaveConfirmModal(state), results.append)
        await pilot.pause()
        yield app, pilot


def _static_text(static: Static) -> str:
    renderable = getattr(static, "_Static__content", static.render())
    if isinstance(renderable, Syntax):
        return renderable.code
    return getattr(renderable, "plain", str(renderable))


async def test_create_opens_on_draft_and_saves() -> None:
    results: list[str | None] = []
    async with _open_modal(
        SnippetSaveConfirmState(
            trigger="todo",
            display_path="~/.config/sase/sase.yml",
            body="TODO($1): $0",
            exists=False,
            existing_body=None,
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, SnippetSaveConfirmModal)
        header = _static_text(modal.query_one("#snippet-save-confirm-header", Static))
        preview = _static_text(modal.query_one("#snippet-save-confirm-preview", Static))
        assert "Insert into ~/.config/sase/sase.yml" in header
        assert "[Draft]" in header
        assert "    todo: |-" in preview
        assert "      TODO($1): $0" in preview

        await pilot.press("enter")
        await pilot.pause()

    assert results == ["save"]


async def test_overwrite_opens_on_diff_and_saves() -> None:
    results: list[str | None] = []
    async with _open_modal(
        SnippetSaveConfirmState(
            trigger="todo",
            display_path="sase.yml",
            body="new body",
            exists=True,
            existing_body="old body",
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, SnippetSaveConfirmModal)
        header = _static_text(modal.query_one("#snippet-save-confirm-header", Static))
        preview = _static_text(modal.query_one("#snippet-save-confirm-preview", Static))
        assert "Overwrite sase.yml" in header
        assert "[Diff]" in header
        assert "-      old body" in preview
        assert "+      new body" in preview

        await pilot.press("enter")
        await pilot.pause()

    assert results == ["save"]


async def test_empty_body_refuses_to_save() -> None:
    results: list[str | None] = []
    async with _open_modal(
        SnippetSaveConfirmState(
            trigger="todo",
            display_path="sase.yml",
            body="  ",
            exists=False,
            existing_body=None,
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, SnippetSaveConfirmModal)
        await pilot.press("enter")
        await pilot.pause()
        verdict = _static_text(modal.query_one("#snippet-save-confirm-verdict", Static))
        assert "Snippet body is empty" in verdict
        assert isinstance(app.screen, SnippetSaveConfirmModal)

    assert results == []


async def test_no_change_closes_without_write() -> None:
    results: list[str | None] = []
    async with _open_modal(
        SnippetSaveConfirmState(
            trigger="todo",
            display_path="sase.yml",
            body="same",
            exists=True,
            existing_body="same",
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, SnippetSaveConfirmModal)
        verdict = _static_text(modal.query_one("#snippet-save-confirm-verdict", Static))
        assert "No changes" in verdict

        await pilot.press("enter")
        await pilot.pause()

    assert results == ["close"]


async def test_changed_on_disk_offers_reload_or_overwrite() -> None:
    results: list[str | None] = []
    async with _open_modal(
        SnippetSaveConfirmState(
            trigger="todo",
            display_path="sase.yml",
            body="draft",
            exists=True,
            existing_body="disk",
            changed_on_disk=True,
        ),
        results,
    ) as (app, pilot):
        modal = app.screen
        assert isinstance(modal, SnippetSaveConfirmModal)
        verdict = _static_text(modal.query_one("#snippet-save-confirm-verdict", Static))
        assert "changed on disk" in verdict
        assert "r reload" in verdict

        await pilot.press("r")
        await pilot.pause()

    assert results == ["reload"]
