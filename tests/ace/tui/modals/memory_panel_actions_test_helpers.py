"""Shared harnesses and write fakes for Memory panel action tests."""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Input, Select, Static, TextArea

from sase.ace.testing import wait_for
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.memory_panel_catalog import MemoryNoteDigest
from sase.ace.tui.modals import memory_panel_write as write_mod
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.memory_pane import MemoryPane
from sase.ace.tui.modals.memory_panel_add import (
    MemoryNoteFormDraft,
    MemoryNoteFormModal,
)
from sase.ace.tui.modals.memory_panel_publish import MemoryPublishModal
from sase.memory.mutation import MemoryMutationOutcome
from sase.memory.notes import AGENTS_PARENT
from tests.ace.tui.modals.memory_panel_test_helpers import MemoryPanelTestApp

UNSET = object()


class MemoryNoteFormApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: MemoryNoteFormModal) -> None:
        super().__init__()
        self.modal = modal
        self.result: MemoryNoteFormDraft | None | object = UNSET

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.modal, self._capture)

    def _capture(self, result: MemoryNoteFormDraft | None) -> None:
        self.result = result


class MemoryPanelActionsApp(MemoryPanelTestApp):
    def __init__(self, panel: MemoryPane) -> None:
        super().__init__(panel)
        self.session_calls: list[str] = []
        self.session_kwargs: list[dict[str, Any]] = []
        self.notifications: list[tuple[str, str]] = []
        self.catalog_refreshes: list[str] = []

    def notify(
        self, message: str, *, severity: str = "information", **kwargs: Any
    ) -> None:
        self.notifications.append((message, severity))

    def _schedule_prompt_catalog_rebuild(
        self, *, reason: str, force: bool = False
    ) -> None:
        del force
        self.catalog_refreshes.append(reason)

    def _submit_session_worker(
        self,
        proc_type: str,
        body: Any,
        *,
        on_complete: Any = None,
        **kwargs: Any,
    ) -> object:
        self.session_calls.append(proc_type)
        self.session_kwargs.append(kwargs)
        box: dict[str, TrackedProcResult[Any]] = {}

        def run() -> None:
            box["result"] = body()

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        result = box["result"]
        if on_complete is not None:
            on_complete(
                TrackedProcCompletion(
                    proc_info=None,  # type: ignore[arg-type]
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return object()


def plain_text(renderable: object) -> str:
    if isinstance(renderable, str):
        return renderable
    console = Console(width=200, no_color=True, legacy_windows=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


def note_digest(relative_path: str, sha: str = "abc") -> dict[str, MemoryNoteDigest]:
    return {relative_path: MemoryNoteDigest(mtime_ns=1, size=10, sha256=sha)}


def mutation_outcome(
    stem: str,
    *,
    scope_key: str = "sase",
    note_type: str = "reference",
    parent: str = AGENTS_PARENT,
    description: str | None = "A note.",
    backup_path: Path | None = None,
) -> MemoryMutationOutcome:
    return MemoryMutationOutcome(
        scope_key=scope_key,
        content_root=Path("/tmp/memory"),
        relative_path=f"sase/memory/{stem}.md",
        stem=stem,
        type=note_type,  # type: ignore[arg-type]
        parent=parent,
        description=description,
        backup_path=backup_path,
    )


def install_write_fakes(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: dict[str, Any],
    *,
    create: Any = None,
    update: Any = None,
    delete: Any = None,
) -> None:
    monkeypatch.setattr(
        write_mod,
        "load_memory_scope_snapshot",
        lambda scope: snapshots[scope.key],
    )
    monkeypatch.setattr(write_mod, "invalidate_memory_scope", lambda _key: None)
    if create is not None:
        monkeypatch.setattr(write_mod, "create_memory_note", create)
    if update is not None:
        monkeypatch.setattr(write_mod, "update_memory_note", update)
    if delete is not None:
        monkeypatch.setattr(write_mod, "delete_memory_note", delete)


async def fill_form(
    app: App[None],
    *,
    stem: str | None = None,
    note_type: str | None = None,
    parent: str | None = None,
    description: str | None = None,
) -> MemoryNoteFormModal:
    modal = app.screen
    assert isinstance(modal, MemoryNoteFormModal)
    if stem is not None:
        modal.query_one("#memory-note-form-stem", Input).value = stem
    if note_type is not None:
        modal.query_one("#memory-note-form-type", Select).value = note_type
    if parent is not None:
        modal.query_one("#memory-note-form-parent", Select).value = parent
    if description is not None:
        modal.query_one("#memory-note-form-description", TextArea).text = description
    return modal


async def skip_post_write_offers(pilot: Any, app: MemoryPanelActionsApp) -> None:
    if isinstance(app.screen, ConfirmActionModal):
        await pilot.press("escape")
        await wait_for(
            pilot,
            lambda: (
                isinstance(app.screen, MemoryPublishModal)
                or not isinstance(app.screen, ConfirmActionModal)
            ),
        )
    if isinstance(app.screen, MemoryPublishModal):
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, MemoryPublishModal))


__all__ = [
    "UNSET",
    "MemoryNoteFormApp",
    "MemoryPanelActionsApp",
    "fill_form",
    "install_write_fakes",
    "mutation_outcome",
    "note_digest",
    "plain_text",
    "skip_post_write_offers",
]
