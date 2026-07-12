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

from ._types import PromptContext

log = logging.getLogger(__name__)
_RESTART_STASH_SOURCE = "restart"

if TYPE_CHECKING:
    from asyncio import Lock

    from sase.ace.tui.modals import StashRestoreResult
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
        StashedPromptPane,
    )
    from sase.core.prompt_stash_wire import (
        PromptStashEntryWire,
        PromptStashSnapshotWire,
    )


class PromptBarStashMixin:
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
            entries = await asyncio.to_thread(self._read_prompt_stash_entries)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read pinned prompts",
                    exc,
                ),
                severity="error",
            )
            return
        pinned = [entry for entry in entries if entry.pinned]
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
            UpdatePinnedStashModal(pinned),
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
            entries = await asyncio.to_thread(self._read_prompt_stash_entries)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read stashed prompts",
                    exc,
                ),
                severity="error",
            )
            return
        if not entries:
            self.notify("No stashed prompts to restore")  # type: ignore[attr-defined]
            return

        if auto_restore_single and len(entries) == 1:
            await self._auto_restore_single_entry(entries[0])
            return

        self.push_screen(  # type: ignore[attr-defined]
            StashedPromptsModal(entries),
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
            for text, _frontmatter in PromptBarStashMixin._entries_to_restore_items(
                entries
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

    def _mounted_prompt_bar(self) -> PromptInputBar | None:
        """Return the mounted ``#prompt-input-bar`` widget, or ``None``."""
        from ...widgets import PromptInputBar

        try:
            return self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None

    def _read_prompt_stash_entries(self) -> list[PromptStashEntryWire]:
        """Return the stashed entries on disk (empty on any read failure)."""
        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import (
                PromptStashLockTimeoutError,
                read_prompt_stash_snapshot,
            )

            snapshot = read_prompt_stash_snapshot(prompt_stash_path())
        except PromptStashLockTimeoutError:
            raise
        except Exception:
            return []
        return list(snapshot.entries)

    def _has_stashed_prompts(self) -> bool:
        """Whether any restorable stash exists (drives the footer keymap).

        Reads the in-memory badge count rather than disk so it stays cheap on
        every leader-mode entry; the badge is refreshed on startup and after
        each capture / restore.
        """
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return False
        return indicator.count > 0

    def _has_pinned_stashed_prompts(self) -> bool:
        """Whether any pinned stash exists (drives the ``gS`` hint gate)."""
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return False
        return indicator.pinned_count > 0

    async def on_app_focus(self, _event: object) -> None:
        """Reconcile the shared stash badge after terminal focus returns."""
        self._spawn_prompt_stash_task(self._refresh_prompt_stash_badge_async())

    def _refresh_prompt_stash_indicator(self) -> None:
        """Reload the stash count from disk and update the top-bar badge."""
        self._apply_prompt_stash_counts(*self._read_prompt_stash_counts())

    # -- failed-launch recovery (off the event loop) -------------------------

    def _schedule_prompt_stash_badge_refresh(self) -> None:
        """Refresh the stash badge from disk without blocking the event loop.

        Launch-completion handlers run on the Textual event loop; a synchronous
        stash read there would block the paint path. This schedules the disk
        read on a worker thread and applies the result back on the UI thread.
        """
        self._spawn_prompt_stash_task(self._refresh_prompt_stash_badge_async())

    async def _refresh_prompt_stash_badge_async(self) -> None:
        """Read the on-disk stash count off-thread and apply it to the badge."""
        import asyncio

        try:
            counts = await asyncio.to_thread(self._read_prompt_stash_counts)
        except Exception:  # pragma: no cover - defensive (thread/IO error)
            return
        self._apply_prompt_stash_counts(*counts)

    def _schedule_failed_launch_prompt_recovery(self, submitted_prompt: str) -> None:
        """Stash a payloadless failed-launch prompt, then refresh the badge.

        Used when a launch worker died before returning an outcome, so nothing
        recorded the submitted prompt yet. The record/stash and the follow-up
        badge read both run off the event loop.
        """
        self._spawn_prompt_stash_task(
            self._recover_failed_launch_prompt_async(submitted_prompt)
        )

    async def _recover_failed_launch_prompt_async(self, submitted_prompt: str) -> None:
        """Record + stash *submitted_prompt* off-thread, then refresh the badge."""
        import asyncio

        from sase.history.prompt import record_failed_launch_prompt

        try:
            await asyncio.to_thread(record_failed_launch_prompt, submitted_prompt)
        except Exception:  # pragma: no cover - defensive (thread/IO error)
            return
        await self._refresh_prompt_stash_badge_async()

    def _spawn_prompt_stash_task(self, coro: object) -> None:
        """Run *coro* on the running loop, holding a reference until it finishes."""
        import asyncio
        from collections.abc import Coroutine
        from typing import cast

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            cast(Coroutine[object, object, None], coro).close()
            return
        task = loop.create_task(cast("Coroutine[object, object, None]", coro))
        tasks = getattr(self, "_prompt_stash_async_tasks", None)
        if tasks is None:
            tasks = set()
            self._prompt_stash_async_tasks = tasks
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def _read_prompt_stash_count(self) -> int:
        """Return the number of stashed prompts on disk (thread-safe read).

        Pure disk read with no widget access, so it is safe to call from a
        worker thread (e.g. wrapped in ``asyncio.to_thread`` during startup).
        Any read/binding failure degrades to ``0`` rather than crashing.
        """
        return self._read_prompt_stash_counts()[0]

    def _read_prompt_stash_counts(self) -> tuple[int, int]:
        """Return total and pinned stashed-prompt counts from disk."""
        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import (
                PromptStashLockTimeoutError,
                read_prompt_stash_snapshot,
            )

            snapshot = read_prompt_stash_snapshot(prompt_stash_path())
        except PromptStashLockTimeoutError:
            return self._cached_prompt_stash_counts()
        except Exception:
            return 0, 0
        return self._prompt_stash_snapshot_counts(snapshot)

    def _cached_prompt_stash_counts(self) -> tuple[int, int]:
        """Return the last badge counts without touching the shared store."""
        return getattr(self, "_prompt_stash_cached_counts", (0, 0))

    @staticmethod
    def _prompt_stash_error_message(prefix: str, exc: Exception) -> str:
        from sase.core.prompt_stash_facade import PromptStashLockTimeoutError

        if (
            isinstance(exc, PromptStashLockTimeoutError)
            or (
                exc.__cause__ is not None
                and isinstance(exc.__cause__, PromptStashLockTimeoutError)
            )
            or "prompt stash lock timed out" in str(exc).lower()
        ):
            return "Prompt stash is busy — retry"
        return f"{prefix}: {exc}"

    @staticmethod
    def _prompt_stash_snapshot_counts(
        snapshot: PromptStashSnapshotWire,
    ) -> tuple[int, int]:
        """Return ``(total, pinned)`` counts for a prompt-stash snapshot."""
        entries = list(snapshot.entries)
        return len(entries), sum(1 for entry in entries if entry.pinned)

    def _apply_prompt_stash_snapshot_counts(
        self, snapshot: PromptStashSnapshotWire
    ) -> None:
        """Apply badge counts from an already-available store snapshot."""
        self._apply_prompt_stash_counts(*self._prompt_stash_snapshot_counts(snapshot))

    def _reconcile_prompt_stash_snapshot_counts(
        self, snapshot: PromptStashSnapshotWire
    ) -> None:
        """Apply a worker result only when it differs from optimistic state."""
        counts = self._prompt_stash_snapshot_counts(snapshot)
        if counts != self._cached_prompt_stash_counts():
            self._apply_prompt_stash_counts(*counts)

    def _apply_prompt_stash_counts(self, count: int, pinned_count: int) -> None:
        """Push total and pinned counts into the stash indicator widget."""
        self._prompt_stash_cached_counts = (count, pinned_count)
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return
        indicator.set_count(count, pinned_count=pinned_count)
