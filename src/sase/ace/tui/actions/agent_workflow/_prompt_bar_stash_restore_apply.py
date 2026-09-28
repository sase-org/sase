"""Stash restore application, pin toggles, and bar loading.

Applies per-entry pop/keep/delete decisions from the unified panel,
persists pin toggles and in-place deletes, and loads restored drafts into
the prompt bar (appending to a mounted prompt bar or mounting the home bar).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._prompt_bar_stash_store import PromptBarStashStoreMixin

if TYPE_CHECKING:
    from sase.ace.tui.modals import StashRestoreResult
    from sase.ace.tui.prompt_stash_entries import RestoredStashPane
    from sase.core.prompt_stash_wire import (
        PromptStashEntryWire,
        PromptStashSnapshotWire,
    )


class PromptBarStashRestoreApplyMixin(PromptBarStashStoreMixin):
    """Restore pop/keep/delete decisions and persist pin/delete edits."""

    async def _auto_restore_single_entry(self, entry: PromptStashEntryWire) -> None:
        """Restore one stash entry according to its persisted pin state."""
        from ...modals import StashRestoreResult

        result = (
            StashRestoreResult(keep_ids=[entry.id])
            if entry.pinned
            else StashRestoreResult(pop_ids=[entry.id])
        )
        await self._apply_stash_restore(result)

    async def _on_prompt_stash_restore_confirmed(self, result: object) -> None:
        """Apply the picker outcome: pop, keep, and delete marked ids."""
        from ...modals import StashRestoreResult

        if not isinstance(result, StashRestoreResult):
            return  # cancelled (None) or unexpected payload

        self._spawn_prompt_stash_task(self._apply_stash_restore(result))

    def on_stashed_prompts_modal_pin_toggled(self, event: object) -> None:
        """Persist a prompt-stash pin toggle without blocking key handling."""
        from ...modals import StashedPromptsModal

        if not isinstance(event, StashedPromptsModal.PinToggled):
            return
        self._spawn_prompt_stash_task(
            self._persist_prompt_stash_pin_async(event.entry.id, event.pinned)
        )

    def on_stashed_prompts_modal_delete_requested(self, event: object) -> None:
        """Delete prompt-stash rows while the picker stays open."""
        from ...modals import StashedPromptsModal

        if not isinstance(event, StashedPromptsModal.DeleteRequested):
            return
        self._spawn_prompt_stash_task(
            self._delete_prompt_stash_entries_async(event.entry_ids)
        )

    async def _delete_prompt_stash_entries_async(self, entry_ids: list[str]) -> None:
        """Remove stash rows deleted in place from the open picker."""
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import pop_prompt_stash

        lock = self._prompt_stash_write_lock()  # type: ignore[attr-defined]
        async with lock:
            try:
                outcome = await asyncio.to_thread(
                    pop_prompt_stash, prompt_stash_path(), entry_ids
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to delete stashed prompt",
                        exc,
                    ),
                    severity="error",
                )
                return
        removed = {entry.id for entry in outcome.removed} & set(entry_ids)
        self._notify_restore_outcome(0, len(removed))
        self._apply_prompt_stash_snapshot_counts(outcome.snapshot)

    async def _persist_prompt_stash_pin_async(
        self, entry_id: str, pinned: bool
    ) -> None:
        """Apply a pin toggle through the Rust store on a worker thread."""
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import set_prompt_stash_pinned

        lock = self._prompt_stash_write_lock()  # type: ignore[attr-defined]
        async with lock:
            try:
                snapshot = await asyncio.to_thread(
                    set_prompt_stash_pinned,
                    prompt_stash_path(),
                    [entry_id],
                    pinned,
                )
            except Exception as exc:  # pragma: no cover - stale wheel/IO failure
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to update stashed prompt pin",
                        exc,
                    ),
                    severity="error",
                )
                return
        self._apply_prompt_stash_snapshot_counts(snapshot)

    async def _apply_stash_restore(self, result: StashRestoreResult) -> None:
        """Apply per-entry pop/keep/delete decisions from the unified panel.

        Snapshot reads and stash pops run off the event loop. ``pop`` rows
        load from the pop outcome (what the store actually removed), not from
        a separately read snapshot; only ``keep`` ids still need a snapshot
        read, and that read is fail-closed so a read failure never pops. The
        app loads ``pop`` + ``keep`` ids oldest-first, removes ``pop`` +
        ``delete`` ids in one store call, and refreshes the badge only when
        the store changed. A load failure after a pop appends the removed
        rows back with their original ids and toasts that the draft was put
        back.
        """
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import pop_prompt_stash

        # Pinned panel selections and global ``@`` restores use keep ids so the
        # loaded entries remain available as templates.
        restore_ids = [*result.pop_ids, *result.keep_ids]
        remove_ids = [*result.pop_ids, *result.delete_ids]
        if not restore_ids and not remove_ids:
            return

        keep_entries: list[PromptStashEntryWire] = []
        if result.keep_ids:
            try:
                snapshot = await asyncio.to_thread(
                    self._read_prompt_stash_entries_strict  # type: ignore[attr-defined]
                )
            except Exception as exc:
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to restore prompt",
                        exc,
                    ),
                    severity="error",
                )
                return
            by_id = {entry.id: entry for entry in snapshot}
            keep_entries = [
                by_id[entry_id] for entry_id in result.keep_ids if entry_id in by_id
            ]

        removed: list[PromptStashEntryWire] = []
        removed_ids: set[str] = set()
        snapshot_after_remove: PromptStashSnapshotWire | None = None
        if remove_ids:
            try:
                outcome = await asyncio.to_thread(
                    pop_prompt_stash, prompt_stash_path(), remove_ids
                )
            except Exception as exc:  # pragma: no cover - defensive (store/IO error)
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to restore prompt",
                        exc,
                    ),
                    severity="error",
                )
                return
            removed = list(outcome.removed)
            removed_ids = {entry.id for entry in removed}
            snapshot_after_remove = outcome.snapshot

        pop_ids = set(result.pop_ids)
        restore_entries = [entry for entry in removed if entry.id in pop_ids]
        restore_entries.extend(keep_entries)
        # Original drafting order (oldest first); bundle rows expand later
        # in their stored segment order.
        restore_entries.sort(key=lambda entry: (entry.created_at, entry.pane_index))

        restored_count = 0
        if restore_entries:
            try:
                restored_count = len(self._entries_to_restore_panes(restore_entries))
                self._load_restored_entries(restore_entries)
            except Exception as exc:
                await self._rollback_stash_restore(removed, pop_ids)
                self.notify(  # type: ignore[attr-defined]
                    self._prompt_stash_error_message(
                        "Failed to restore prompt — draft put back in the stash",
                        exc,
                    ),
                    severity="error",
                )
                return

        deleted = sum(1 for entry_id in result.delete_ids if entry_id in removed_ids)
        self._notify_restore_outcome(restored_count, deleted)
        if removed_ids and snapshot_after_remove is not None:
            self._apply_prompt_stash_snapshot_counts(snapshot_after_remove)

    async def _rollback_stash_restore(
        self,
        removed: list[PromptStashEntryWire],
        pop_ids: set[str],
    ) -> None:
        """Append popped restore rows back after a failed bar load."""
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import append_prompt_stash

        to_restore = [entry for entry in removed if entry.id in pop_ids]
        if not to_restore:
            return
        snapshot = None
        for entry in to_restore:
            try:
                snapshot = await asyncio.to_thread(
                    append_prompt_stash, prompt_stash_path(), entry
                )
            except Exception:  # pragma: no cover - defensive (store/IO error)
                continue
        if snapshot is None:  # pragma: no cover - defensive (rollback failed)
            return
        self._apply_prompt_stash_counts(*self._prompt_stash_snapshot_counts(snapshot))

    def _load_restored_entries(self, entries: list[PromptStashEntryWire]) -> None:
        """Load restored stash drafts into the prompt bar.

        Appends to a mounted prompt bar as new panes; otherwise mounts the home
        prompt bar pre-populated with the restored drafts (a single empty pane
        when no real text, multiple panes joined by ``---``). The final restored
        row's saved pane/cursor wins when present; otherwise the last pane is
        focused at end of text.
        """
        panes = self._entries_to_restore_panes(entries)
        bar = self._mounted_prompt_bar()
        if bar is not None and bar._mode == "prompt":
            bar.restore_stashed_entries(panes)
            return
        selected_pane, cursor = self._restore_home_bar_focus(panes)
        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=self._stash_entries_to_prompt_text(entries),
            as_xprompt_markdown=True,
            initial_selected_pane=selected_pane,
            initial_cursor=cursor,
        )

    @staticmethod
    def _entries_to_restore_panes(
        entries: list[PromptStashEntryWire],
    ) -> list[RestoredStashPane]:
        from ...prompt_stash_entries import entries_to_restore_panes

        return entries_to_restore_panes(entries)

    @staticmethod
    def _restore_home_bar_focus(
        panes: list[RestoredStashPane],
    ) -> tuple[int | None, tuple[int, int] | None]:
        from ...prompt_stash_entries import restore_home_bar_focus

        return restore_home_bar_focus(panes)

    @staticmethod
    def _stash_entries_to_prompt_text(
        entries: list[PromptStashEntryWire],
    ) -> str:
        """Build a multi-prompt string from restored entries (oldest first).

        The first entry that carries frontmatter supplies the shared bar
        frontmatter; the bodies are joined with ``---`` so the bar parses them
        back into one pane per entry (mirroring the whole-stack submit format).
        """
        frontmatter = next(
            (entry.frontmatter for entry in entries if entry.frontmatter),
            "",
        )
        body = "\n---\n".join(
            pane.text
            for pane in PromptBarStashRestoreApplyMixin._entries_to_restore_panes(
                entries
            )
            if pane.text.strip()
        )
        if frontmatter and body:
            return f"{frontmatter}\n{body}"
        return frontmatter or body

    def _notify_restore_outcome(self, restored: int, deleted: int) -> None:
        """Toast a count-aware summary of the restore / delete outcome."""
        messages: list[str] = []
        if restored:
            messages.append(
                "Restored prompt" if restored == 1 else f"Restored {restored} prompts"
            )
        if deleted:
            if restored:
                messages.append(f"deleted {deleted}")
            else:
                messages.append(
                    "Deleted stashed prompt"
                    if deleted == 1
                    else f"Deleted {deleted} stashed prompts"
                )
        if messages:
            self.notify(", ".join(messages))  # type: ignore[attr-defined]
