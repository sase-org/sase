"""Unified picker for stashed prompt drafts.

Lists stashed prompts newest-first with numbered restore keycaps, a relative
age, an originating-project chip, bundle marker, persistent pin marker, and a
one-line preview. ``1``-``9`` restore rows 1-9, ``0`` restores row 10, ``space``
toggles any row's pin and posts an intent message for the app layer to persist
immediately, ``tab`` marks it to restore, ``d`` marks one row for deletion,
``D`` marks every row for deletion, and ``enter`` confirms. Pinned rows are
restored while staying stashed; unpinned rows are restored and popped. The
modal never touches the store directly; restore/delete decisions are returned
as :class:`StashRestoreResult`, except a delete-only confirm that leaves rows
remaining, which posts :class:`StashedPromptsModal.DeleteRequested` for the app
to persist while the panel stays open.

The list/preview UI and interactions live in
:class:`sase.ace.tui.modals.stash_pane.StashControllerMixin` so the tabbed
Prompts overlay reuses them without behavior drift; this screen only hosts a
:class:`StashPane` and dismisses with its outcome.
"""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.screen import ModalScreen

from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.project_display_names import ProjectDisplaySnapshot

from .base import OptionListNavigationMixin
from .stash_pane import (
    STASH_BINDINGS,
    DeleteRequested,
    PinToggled,
    StashControllerMixin,
    StashRestoreResult,
)

__all__ = [
    "StashRestoreResult",
    "StashedPromptsModal",
]


class StashedPromptsModal(
    StashControllerMixin,
    OptionListNavigationMixin,
    ModalScreen["StashRestoreResult | None"],
):
    """Multi-select picker for pinning, restoring, and deleting stashed prompts."""

    # Shared stash messages keep their historical handler names so existing
    # app-layer ``on_stashed_prompts_modal_*`` handlers keep firing.
    PinToggled = PinToggled
    DeleteRequested = DeleteRequested

    BINDINGS = STASH_BINDINGS

    def __init__(
        self,
        entries: list[PromptStashEntryWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
    ) -> None:
        super().__init__()
        self._init_stash_controller(
            entries, project_display_snapshot=project_display_snapshot
        )

    def _emit_result(self, result: StashRestoreResult | None = None) -> None:
        self.dismiss(result)

    # -- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield from self._compose_stash_modal_body()

    def on_mount(self) -> None:
        self._on_stash_mount()

    def on_unmount(self) -> None:
        self._on_stash_unmount()

    def on_resize(self, event: events.Resize) -> None:
        self._on_stash_resize(event)
