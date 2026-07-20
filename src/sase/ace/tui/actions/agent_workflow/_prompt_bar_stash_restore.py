"""Prompt-stash restore and pinned-entry workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._prompt_bar_stash_store import PromptBarStashStoreMixin

if TYPE_CHECKING:
    from asyncio import Lock

    from sase.ace.tui.modals import StashRestoreResult
    from sase.core.prompt_stash_wire import (
        PromptStashEntryWire,
        PromptStashSnapshotWire,
    )


class PromptBarStashRestoreMixin(PromptBarStashStoreMixin):
    """Restore, pin, and remove entries from the shared prompt stash."""

    # -- restore -------------------------------------------------------------

    async def on_prompt_input_bar_restore_requested(self, event: object) -> None:
        """Open the unified stash panel when the prompt bar requests it."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.RestoreRequested):
            return
        self._spawn_prompt_stash_task(
            self._open_prompt_stash_panel(bar_mode=event.mode)
        )

    async def action_restore_prompt_stash(self) -> None:
        """Global ``@`` keymap: restore or open the prompt-stash panel.

        A lone unpinned entry restores and pops immediately; a lone pinned entry
        restores while staying stashed. Multi-entry stashes still open the
        picker, and prompt-local ``Ctrl+G p`` remains the panel-only path. No
        ``bar_mode`` is forced: ``_open_prompt_stash_panel`` inspects the
        mounted bar (so a feedback / approve-prompt bar still no-ops) and
        defaults to ``prompt`` mode when no bar is mounted, mounting the home
        prompt bar with the restored drafts.
        """
        self._spawn_prompt_stash_task(
            self._open_prompt_stash_panel(auto_restore_single=True)
        )

    async def action_open_prompt_stash(self) -> None:
        """Leader shortcut: open the prompt-stash panel without auto-restoring."""
        self._spawn_prompt_stash_task(
            self._open_prompt_stash_panel(auto_restore_single=False)
        )

    async def _open_prompt_stash_panel(
        self,
        bar_mode: str | None = None,
        *,
        auto_restore_single: bool = False,
    ) -> None:
        """Read the stash snapshot off-thread and restore or push the picker.

        Restore is guarded to ``prompt`` bars (D5): a feedback /
        approve-prompt bar toasts a no-op.  When *bar_mode* is ``None`` the
        currently mounted bar — if any — supplies the mode. An empty store
        toasts instead of opening an empty modal. When *auto_restore_single* is
        set, a one-entry stash restores directly; otherwise the unified picker
        opens. The snapshot read runs on a worker thread so key handling never
        blocks the paint path (boundary rule D6).
        """
        import asyncio

        from ...modals import StashedPromptsModal

        if bar_mode is None:
            bar = self._mounted_prompt_bar()
            bar_mode = bar._mode if bar is not None else "prompt"
        if bar_mode != "prompt":
            self.notify(  # type: ignore[attr-defined]
                "Restore is only available for agent prompts", severity="warning"
            )
            return

        try:
            presentation = await asyncio.to_thread(
                self._read_prompt_stash_presentation_snapshot
            )
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read stashed prompts",
                    exc,
                ),
                severity="error",
            )
            return
        entries = list(presentation.entries)
        if not entries:
            self.notify("No stashed prompts to restore")  # type: ignore[attr-defined]
            return

        if auto_restore_single and len(entries) == 1:
            await self._auto_restore_single_entry(entries[0])
            return

        self.push_screen(  # type: ignore[attr-defined]
            StashedPromptsModal(
                entries,
                project_display_snapshot=presentation.project_display_snapshot,
            ),
            self._on_prompt_stash_restore_confirmed,
        )

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

    async def _persist_prompt_stash_pin_async(
        self, entry_id: str, pinned: bool
    ) -> None:
        """Apply a pin toggle through the Rust store on a worker thread."""
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import set_prompt_stash_pinned

        lock = self._prompt_stash_write_lock()
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

    def _prompt_stash_write_lock(self) -> Lock:
        """Return the async lock shared by prompt-stash write operations."""
        import asyncio

        lock = getattr(self, "_prompt_stash_pin_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._prompt_stash_pin_lock = lock
        return lock

    async def _apply_stash_restore(self, result: StashRestoreResult) -> None:
        """Apply per-entry pop/keep/delete decisions from the unified panel.

        Snapshot reads and stash pops run off the event loop. The app loads
        ``pop`` + ``keep`` ids oldest-first, removes ``pop`` + ``delete`` ids in
        one store call, and refreshes the badge only when the store changed.
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

        restore_entries: list[PromptStashEntryWire] = []
        if restore_ids:
            try:
                snapshot = await asyncio.to_thread(self._read_prompt_stash_entries)
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
            restore_entries = [
                by_id[entry_id] for entry_id in restore_ids if entry_id in by_id
            ]
            # Original drafting order (oldest first); bundle rows expand later
            # in their stored segment order.
            restore_entries.sort(key=lambda entry: (entry.created_at, entry.pane_index))

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
            removed_ids = {entry.id for entry in outcome.removed}
            snapshot_after_remove = outcome.snapshot

        restored_count = 0
        if restore_entries:
            restored_count = len(self._entries_to_restore_items(restore_entries))
            self._load_restored_entries(restore_entries)

        deleted = sum(1 for entry_id in result.delete_ids if entry_id in removed_ids)
        self._notify_restore_outcome(restored_count, deleted)
        if removed_ids and snapshot_after_remove is not None:
            self._apply_prompt_stash_snapshot_counts(snapshot_after_remove)

    def _load_restored_entries(self, entries: list[PromptStashEntryWire]) -> None:
        """Load restored stash drafts into the prompt bar.

        Appends to a mounted prompt bar as new panes; otherwise mounts the home
        prompt bar pre-populated with the restored drafts (a single empty pane
        when no real text, multiple panes joined by ``---``).
        """
        bar = self._mounted_prompt_bar()
        if bar is not None and bar._mode == "prompt":
            bar.restore_stashed_entries(self._entries_to_restore_items(entries))
            return
        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=self._stash_entries_to_prompt_text(entries),
            as_xprompt_markdown=True,
        )

    @staticmethod
    def _entries_to_restore_items(
        entries: list[PromptStashEntryWire],
    ) -> list[tuple[str, str]]:
        from ...prompt_stash_entries import entries_to_restore_items

        return entries_to_restore_items(entries)

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
            text
            for text, _frontmatter in (
                PromptBarStashRestoreMixin._entries_to_restore_items(entries)
            )
            if text.strip()
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
