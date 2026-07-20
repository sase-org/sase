"""Prompt-stash capture handler + top-bar indicator refresh.

The prompt bar is presentation-only (boundary rule D6): it captures pane
text(s) and posts a ``PromptInputBar.Stashed`` message.  This mixin is the app
glue that persists the captured panes through ``prompt_stash_facade`` (which
fronts the Rust ``sase_core_rs`` store), shows a toast, and refreshes the
``StashedPromptsIndicator`` badge.  Reads/writes go through the per-user pile at
``prompt_stash_path()`` (``~/.sase/prompt_stash.jsonl``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._prompt_bar_stash_restore import PromptBarStashRestoreMixin
from ._types import PromptContext

log = logging.getLogger(__name__)
_RESTART_STASH_SOURCE = "restart"

if TYPE_CHECKING:
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
        StashedPromptPane,
    )
    from sase.core.prompt_stash_wire import (
        PromptStashEntryWire,
        PromptStashSnapshotWire,
    )


class PromptBarStashMixin(PromptBarStashRestoreMixin):
    """Persist stashed prompt panes and keep the top-bar badge in sync."""

    _prompt_context: PromptContext | None

    def _stash_prompt_bar_before_restart(self) -> bool:
        """Synchronously stash the mounted agent prompt before a TUI restart."""
        try:
            bar = self._mounted_prompt_bar()
            if bar is None or bar._mode != "prompt":
                return False
            panes = bar.capture_stashable_panes()
            if not panes:
                return False
            self._persist_stashed_panes(panes, source=_RESTART_STASH_SOURCE)
        except Exception:
            log.exception("Failed to stash prompt draft before TUI restart")
            return False
        return True

    def on_prompt_input_bar_stashed(self, event: object) -> None:
        """Optimistically stage a stash and persist it in a tracked worker."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.Stashed):
            return

        panes = event.panes
        if not panes:
            # No stashable pane was captured; tell the user without touching
            # the store or the badge.
            self.notify("Nothing to stash", severity="warning")  # type: ignore[attr-defined]
            return

        count = len(panes)
        message = "Stashed prompt"
        if count > 1:
            message = (
                f"Stashed {count} prompts as a bundle"
                if event.source == "all"
                else f"Stashed {count} prompts"
            )
        self.notify(  # type: ignore[attr-defined]
            message
        )
        previous_counts = self._cached_prompt_stash_counts()
        self._apply_prompt_stash_counts(
            previous_counts[0] + 1,
            previous_counts[1],
        )
        try:
            entry = self._build_prompt_stash_entry(panes, source=event.source)
        except Exception as exc:
            self._apply_prompt_stash_counts(*previous_counts)
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message("Failed to stash prompt", exc),
                severity="error",
            )
            return

        if event.dismiss_bar:
            # The bar emptied: drop it via the post-submit path so the stashed
            # text is not *also* re-recorded as cancelled prompt history.
            self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
            self._prompt_context = None

        self._submit_prompt_stash_persist_task(entry, previous_counts)

    def _submit_prompt_stash_persist_task(
        self,
        entry: PromptStashEntryWire,
        previous_counts: tuple[int, int],
    ) -> None:
        """Append one entry in the tracked task queue and reconcile the badge."""
        from ..task_actions import (
            TrackedTaskCompletion,
            TrackedTaskResult,
        )

        def _persist() -> TrackedTaskResult[PromptStashSnapshotWire]:
            try:
                snapshot = self._append_prompt_stash_entry(entry)
            except Exception as exc:
                return TrackedTaskResult(
                    success=False,
                    message=str(exc),
                    error=str(exc),
                )
            return TrackedTaskResult(
                success=True,
                message="Prompt stashed",
                payload=snapshot,
            )

        def _completed(
            completion: TrackedTaskCompletion[PromptStashSnapshotWire],
        ) -> None:
            if completion.success and completion.payload is not None:
                self._reconcile_prompt_stash_snapshot_counts(completion.payload)
                return
            self._apply_prompt_stash_counts(*previous_counts)
            error = RuntimeError(completion.error or completion.message)
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message("Failed to stash prompt", error),
                severity="error",
            )

        submit = getattr(self, "_submit_tracked_task", None)
        if not callable(submit):
            self._spawn_prompt_stash_task(
                self._persist_prompt_stash_entry_async(
                    entry,
                    previous_counts,
                )
            )
            return
        submit(
            "prompt-stash",
            "",
            "",
            _persist,
            display_name="Stash prompt",
            dedup_key=f"prompt-stash:{entry.id}",
            on_complete=_completed,
            reload_on_complete=False,
            notify_on_complete=False,
        )

    async def _persist_prompt_stash_entry_async(
        self,
        entry: PromptStashEntryWire,
        previous_counts: tuple[int, int],
    ) -> None:
        """Fallback for narrow harnesses that do not include task actions."""
        import asyncio

        try:
            snapshot = await asyncio.to_thread(
                self._append_prompt_stash_entry,
                entry,
            )
        except Exception as exc:
            self._apply_prompt_stash_counts(*previous_counts)
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message("Failed to stash prompt", exc),
                severity="error",
            )
            return
        self._reconcile_prompt_stash_snapshot_counts(snapshot)

    def _persist_stashed_panes(
        self,
        panes: list[StashedPromptPane],
        *,
        source: str,
    ) -> PromptStashSnapshotWire:
        """Append the captured stash unit to the per-user prompt-stash store.

        The originating project (D2 metadata) comes from the active prompt
        context so the Phase 3 restore picker can show a project chip; id and
        timestamp are minted here per entry.  ``gs`` captures arrive as multiple
        panes but are stored as one canonical multi-prompt row.
        """
        entry = self._build_prompt_stash_entry(panes, source=source)
        return self._append_prompt_stash_entry(entry)

    def _build_prompt_stash_entry(
        self,
        panes: list[StashedPromptPane],
        *,
        source: str,
    ) -> PromptStashEntryWire:
        """Build the immutable store entry before optimistic UI teardown."""
        from datetime import datetime
        from uuid import uuid4

        from sase.core.prompt_stash_facade import PromptStashEntryWire
        from sase.core.time import get_timezone

        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        return PromptStashEntryWire(
            id=str(uuid4()),
            created_at=datetime.now(get_timezone()).isoformat(),
            text=self._captured_stash_text(panes),
            frontmatter=self._captured_stash_frontmatter(panes),
            project=project,
            source=source,
            pane_index=min(pane.pane_index for pane in panes),
        )

    @staticmethod
    def _append_prompt_stash_entry(
        entry: PromptStashEntryWire,
    ) -> PromptStashSnapshotWire:
        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import append_prompt_stash

        return append_prompt_stash(prompt_stash_path(), entry)

    @staticmethod
    def _captured_stash_text(panes: list[StashedPromptPane]) -> str:
        """Return the canonical prompt bundle text for captured panes."""
        return "\n---\n".join(pane.text for pane in panes)

    @staticmethod
    def _captured_stash_frontmatter(panes: list[StashedPromptPane]) -> str:
        """Return the shared frontmatter captured with a prompt bundle."""
        return next((pane.frontmatter for pane in panes if pane.frontmatter), "")

    # -- update pinned ------------------------------------------------------

    async def on_prompt_input_bar_update_pinned_requested(self, event: object) -> None:
        """Update a pinned stash row from the current prompt-bar draft."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.UpdatePinnedRequested):
            return

        panes = event.panes
        if not panes:
            self.notify("Nothing to save", severity="warning")  # type: ignore[attr-defined]
            return
        self._spawn_prompt_stash_task(self._update_pinned_stash(panes))

    async def _update_pinned_stash(self, panes: list[StashedPromptPane]) -> None:
        """Choose a pinned target and schedule an in-place stash update."""
        import asyncio

        from ...modals import UpdatePinnedStashModal

        text = self._captured_stash_text(panes)
        frontmatter = self._captured_stash_frontmatter(panes)
        if not text.strip():
            self.notify("Nothing to save", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            presentation = await asyncio.to_thread(
                self._read_prompt_stash_presentation_snapshot
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read pinned prompts",
                    exc,
                ),
                severity="error",
            )
            return
        pinned = [entry for entry in presentation.entries if entry.pinned]
        if not pinned:
            self.notify(  # type: ignore[attr-defined]
                "No pinned prompt stash to update — pin one with space in the "
                "stash picker (Ctrl+G p)",
                severity="warning",
            )
            return

        if len(pinned) == 1:
            self._spawn_prompt_stash_task(
                self._write_pinned_update(pinned[0], text, frontmatter)
            )
            return

        by_id = {entry.id: entry for entry in pinned}

        def _on_picked(entry_id: str | None) -> None:
            if entry_id is None:
                return
            entry = by_id.get(entry_id)
            if entry is None:
                return
            self._spawn_prompt_stash_task(
                self._write_pinned_update(entry, text, frontmatter)
            )

        self.push_screen(  # type: ignore[attr-defined]
            UpdatePinnedStashModal(
                pinned,
                project_display_snapshot=presentation.project_display_snapshot,
            ),
            _on_picked,
        )

    async def _write_pinned_update(
        self,
        base_entry: PromptStashEntryWire,
        text: str,
        frontmatter: str,
    ) -> None:
        """Rewrite one pinned stash row with freshly captured prompt text."""
        import asyncio
        from dataclasses import replace

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import rewrite_prompt_stash

        updated = replace(base_entry, text=text, frontmatter=frontmatter)
        lock = self._prompt_stash_write_lock()
        async with lock:
            try:
                snapshot = await asyncio.to_thread(
                    rewrite_prompt_stash,
                    prompt_stash_path(),
                    [updated],
                )
            except Exception as exc:  # pragma: no cover - stale wheel/IO failure
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to update pinned prompt",
                        exc,
                    ),
                    severity="error",
                )
                return

        self._apply_prompt_stash_snapshot_counts(snapshot)
        from ...modals.prompt_stash_row import first_line_preview

        preview = first_line_preview(text, 48)
        self.notify(f'Updated pinned prompt 📌 "{preview}"')  # type: ignore[attr-defined]
