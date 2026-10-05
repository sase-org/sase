"""Trash lifecycle mutations for the shared Prompts overlay.

Stage → Rust → authoritative repaint: staged Stash → Trash moves, Trash
purges, and Trash → Stash restores repaint the open overlay in place from
the store outcome so visible rows stay truthful.
"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from ._prompt_bar_stash_store import PromptBarStashStoreMixin

if TYPE_CHECKING:
    from asyncio import Lock

    from sase.ace.tui.modals import StashRestoreResult
    from sase.ace.tui.modals.prompts_modal import PromptsModal
    from sase.ace.tui.modals.stash_pane import TrashCommitPreview
    from sase.core.prompt_stash_wire import PromptStashLifecycleOutcomeWire

    from ._prompt_bar_stash_restore_overlay import PromptsOverlaySnapshot


class PromptBarStashRestoreTrashMixin(PromptBarStashStoreMixin):
    """Move rows between Stash and Trash and repaint from store outcomes."""

    async def _apply_prompts_stash_result(self, result: StashRestoreResult) -> None:
        """Apply a Stash-tab dismiss: restore pop/keep, trash discards.

        Trash marks move through Rust immediately with no y/n; the success
        toast names the actual evictions because other processes may change
        Trash between preview and commit. Restores load oldest-first; the
        badge follows authoritative counts.
        """
        from ...modals import StashRestoreResult

        if result.trash_ids:
            preview = await self._preview_trash_commit_async(list(result.trash_ids))
            if preview is not None:
                await self._trash_entries_async(list(result.trash_ids))
        rest = StashRestoreResult(
            pop_ids=list(result.pop_ids),
            keep_ids=list(result.keep_ids),
            delete_ids=list(result.delete_ids),
        )
        if rest.pop_ids or rest.keep_ids or rest.delete_ids:
            await self._apply_stash_restore(rest)  # type: ignore[attr-defined]

    async def _apply_prompts_trash_result(self, result: object) -> None:
        """Apply a Trash-tab dismiss (purge-everything path only).

        Restores always arrive as in-place requests while the overlay stays
        open; only purging every remaining row dismisses, so a dismiss
        carries purge ids to confirm and apply permanently.
        """
        purge_ids = list(getattr(result, "purge_ids", ()))
        restore_ids = list(getattr(result, "restore_ids", ()))
        if restore_ids:
            await self._restore_trashed_async(restore_ids)
        if purge_ids:
            confirmed = await self._confirm_purge_async(purge_ids)
            if confirmed:
                await self._purge_trashed_async(purge_ids)

    # -- trash lifecycle mutations (stage → Rust → authoritative repaint) ---

    def on_stashed_prompts_modal_trash_requested(self, event: object) -> None:
        """Move staged Stash rows to Trash while the overlay stays open."""
        from ...modals.stash_pane import TrashRequested

        if not isinstance(event, TrashRequested):
            return
        self._spawn_prompt_stash_task(
            self._trash_staged_in_place_async(list(event.entry_ids))
        )

    def on_trash_pane_purge_requested(self, event: object) -> None:
        """Purge staged Trash rows after explicit confirmation."""
        from ...modals.trash_pane import PurgeRequested

        if not isinstance(event, PurgeRequested):
            return
        self._spawn_prompt_stash_task(
            self._purge_staged_in_place_async(list(event.entry_ids))
        )

    def on_trash_pane_trash_restore_requested(self, event: object) -> None:
        """Restore Trash rows to Stash while the overlay stays open."""
        from ...modals.trash_pane import TrashRestoreRequested

        if not isinstance(event, TrashRestoreRequested):
            return
        self._spawn_prompt_stash_task(
            self._restore_trashed_async(list(event.entry_ids))
        )

    def on_trash_pane_trash_copy_requested(self, event: object) -> None:
        """Copy the highlighted Trash row to the clipboard."""
        from ...modals.trash_pane import TrashCopyRequested

        if not isinstance(event, TrashCopyRequested):
            return
        text = event.entry.text
        copier = getattr(self, "copy_to_clipboard", None)
        if not callable(copier):
            self.notify(  # type: ignore[attr-defined]
                "Clipboard is unavailable", severity="error"
            )
            return
        try:
            copier(text)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message("Failed to copy trashed draft", exc),
                severity="error",
            )
            return
        self.notify("Copied trashed draft to clipboard")  # type: ignore[attr-defined]

    async def _trash_staged_in_place_async(self, entry_ids: list[str]) -> None:
        """Move staged Stash → Trash marks with no y/n, then repaint in place."""
        if not entry_ids:
            return
        preview = await self._preview_trash_commit_async(entry_ids)
        if preview is not None:
            await self._trash_entries_async(entry_ids)

    async def _purge_staged_in_place_async(self, entry_ids: list[str]) -> None:
        """Confirm staged purges, apply, and repaint in place."""
        if not entry_ids:
            return
        confirmed = await self._confirm_purge_async(entry_ids)
        if confirmed:
            await self._purge_trashed_async(entry_ids)

    async def _preview_trash_commit_async(
        self, entry_ids: list[str]
    ) -> TrashCommitPreview | None:
        """Re-read the overlay snapshot and preview a Stash → Trash move.

        Returns the preview when at least one marked id is still active, or
        ``None`` on a read failure (after toasting) or a stale selection
        with nothing live to move (no write, no move toast).
        """
        import asyncio

        from ...modals.stash_pane import preview_trash_commit

        try:
            overlay: PromptsOverlaySnapshot = await asyncio.to_thread(
                self._read_prompt_stash_overlay_snapshot  # type: ignore[attr-defined]
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read stashed prompts",
                    exc,
                ),
                severity="error",
            )
            return None
        preview = preview_trash_commit(
            list(entry_ids),
            list(overlay.entries),
            trash_count=len(overlay.trash),
            trash_limit=overlay.trash_limit,
        )
        if not preview.marked_ids:
            return None  # stale selection: nothing live to move
        return preview

    async def _confirm_purge_async(self, entry_ids: list[str]) -> bool:
        """Confirm permanent deletion of Trash rows."""
        import asyncio

        from ...modals.trash_pane import purge_confirm_text

        try:
            overlay: PromptsOverlaySnapshot = await asyncio.to_thread(
                self._read_prompt_stash_overlay_snapshot  # type: ignore[attr-defined]
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read trashed drafts",
                    exc,
                ),
                severity="error",
            )
            return False
        live = {record.entry.id for record in overlay.trash}
        marked = [entry_id for entry_id in entry_ids if entry_id in live]
        if not marked:
            return False  # stale selection: nothing left to purge
        return await self._confirm_async(
            "Permanently delete",
            purge_confirm_text(marked, list(overlay.trash)),
        )

    async def _confirm_async(self, title: str, message: str) -> bool:
        """Push an explicit confirmation and await its yes/no outcome."""
        import asyncio

        from ...modals import ConfirmActionModal, ConfirmKind

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def _on_confirm(confirmed: bool | None) -> None:
            if not future.done():
                future.set_result(bool(confirmed))

        self.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(title, message, kind=ConfirmKind.DANGER),
            _on_confirm,
        )
        return await future

    async def _trash_entries_async(self, entry_ids: list[str]) -> None:
        """Move active rows to Trash and repaint from the store outcome."""
        import asyncio
        from datetime import datetime

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import trash_prompt_stash
        from ...modals.stash_pane import trash_outcome_text
        from sase.ace.config import get_ace_prompt_stash_trash_limit

        trashed_at = datetime.now(UTC).isoformat()
        lock = self._prompt_stash_write_lock()
        async with lock:
            try:
                outcome = await asyncio.to_thread(
                    trash_prompt_stash,
                    prompt_stash_path(),
                    list(entry_ids),
                    get_ace_prompt_stash_trash_limit(),
                    trashed_at,
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to move drafts to Trash",
                        exc,
                    ),
                    severity="error",
                )
                self._apply_prompts_overlay_failure()
                return
        self.notify(  # type: ignore[attr-defined]
            trash_outcome_text(len(outcome.changed), list(outcome.evicted))
        )
        self._apply_prompt_stash_lifecycle_outcome(outcome)

    async def _restore_trashed_async(self, entry_ids: list[str]) -> None:
        """Move Trash rows back to Stash; the overlay stays open."""
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import restore_prompt_stash

        lock = self._prompt_stash_write_lock()
        async with lock:
            try:
                outcome = await asyncio.to_thread(
                    restore_prompt_stash,
                    prompt_stash_path(),
                    list(entry_ids),
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to restore drafts from Trash",
                        exc,
                    ),
                    severity="error",
                )
                self._apply_prompts_overlay_failure()
                return
        restored = len(outcome.changed)
        if restored:
            noun = "draft" if restored == 1 else "drafts"
            self.notify(f"Restored {restored} {noun} to Stash")  # type: ignore[attr-defined]
        self._apply_prompt_stash_lifecycle_outcome(outcome)

    async def _purge_trashed_async(self, entry_ids: list[str]) -> None:
        """Permanently delete Trash rows and repaint from the store outcome."""
        import asyncio

        from ...modals._stash_trash_commit import STASH_ARCHIVE_RECOVERY_HINT
        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import purge_prompt_stash

        lock = self._prompt_stash_write_lock()
        async with lock:
            try:
                outcome = await asyncio.to_thread(
                    purge_prompt_stash,
                    prompt_stash_path(),
                    list(entry_ids),
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to permanently delete drafts",
                        exc,
                    ),
                    severity="error",
                )
                self._apply_prompts_overlay_failure()
                return
        remaining = {record.entry.id for record in outcome.snapshot.trash}
        purged = sum(1 for entry_id in entry_ids if entry_id not in remaining)
        if purged:
            noun = "draft" if purged == 1 else "drafts"
            self.notify(  # type: ignore[attr-defined]
                f"Permanently deleted {purged} {noun}. {STASH_ARCHIVE_RECOVERY_HINT}"
            )
        self._apply_prompt_stash_lifecycle_outcome(outcome)

    def _apply_prompt_stash_lifecycle_outcome(
        self, outcome: PromptStashLifecycleOutcomeWire
    ) -> None:
        """Repaint the open overlay and badge from a lifecycle outcome."""
        modal = self._open_prompts_overlay()
        if modal is not None:
            try:
                modal.apply_lifecycle_snapshot(
                    list(outcome.snapshot.active),
                    list(outcome.snapshot.trash),
                )
            except Exception:
                pass
        self._apply_prompt_stash_lifecycle_counts(outcome)

    def _apply_prompt_stash_lifecycle_counts(
        self, outcome: PromptStashLifecycleOutcomeWire
    ) -> None:
        """Update the stash badge from authoritative active counts only."""
        active = list(outcome.snapshot.active)
        self._apply_prompt_stash_counts(
            len(active), sum(1 for entry in active if entry.pinned)
        )

    def _apply_prompts_overlay_failure(self) -> None:
        """Leave visible rows and staged marks truthful after a failed write."""
        modal = self._open_prompts_overlay()
        if modal is not None:
            try:
                modal.apply_store_failure()
            except Exception:
                pass

    def _open_prompts_overlay(self) -> PromptsModal | None:
        """Return the currently open Prompts overlay, if this host has one."""
        from ...modals.prompts_modal import PromptsModal

        modal = getattr(self, "_prompts_overlay_ref", None)
        return modal if isinstance(modal, PromptsModal) else None

    def _remember_prompts_overlay(self, modal: object) -> None:
        """Track the pushed overlay so mutations can repaint it."""
        self._prompts_overlay_ref = modal

    def _forget_prompts_overlay(self) -> None:
        """Drop the tracked overlay once it dismisses."""
        self._prompts_overlay_ref = None

    def _prompt_stash_write_lock(self) -> Lock:
        """Return the async lock shared by prompt-stash write operations."""
        import asyncio

        lock = getattr(self, "_prompt_stash_pin_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._prompt_stash_pin_lock = lock
        return lock
