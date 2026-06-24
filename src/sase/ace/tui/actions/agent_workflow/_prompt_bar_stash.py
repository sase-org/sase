"""Prompt-stash capture handler + top-bar indicator refresh.

The prompt bar is presentation-only (boundary rule D6): it captures pane
text(s) and posts a ``PromptInputBar.Stashed`` message.  This mixin is the app
glue that persists the captured panes through ``prompt_stash_facade`` (which
fronts the Rust ``sase_core_rs`` store), shows a toast, and refreshes the
``StashedPromptsIndicator`` badge.  Reads/writes go through the per-user pile at
``prompt_stash_path()`` (``~/.sase/prompt_stash.jsonl``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.tui.modals import StashRestoreResult
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
        StashedPromptPane,
    )
    from sase.core.prompt_stash_wire import PromptStashEntryWire


class PromptBarStashMixin:
    """Persist stashed prompt panes and keep the top-bar badge in sync."""

    _prompt_context: PromptContext | None

    def on_prompt_input_bar_stashed(self, event: object) -> None:
        """Persist stashed panes, toast, and refresh the indicator badge."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.Stashed):
            return

        panes = event.panes
        if not panes:
            # An empty pane stashes nothing; tell the user without touching the
            # store or the badge.
            self.notify("Nothing to stash", severity="warning")  # type: ignore[attr-defined]
            return

        try:
            self._persist_stashed_panes(panes, source=event.source)
        except Exception as exc:  # pragma: no cover - defensive (store/IO error)
            self.notify(  # type: ignore[attr-defined]
                f"Failed to stash prompt: {exc}", severity="error"
            )
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
        self._refresh_prompt_stash_indicator()

        if event.dismiss_bar:
            # The bar emptied: drop it via the post-submit path so the stashed
            # text is not *also* re-recorded as cancelled prompt history.
            self._unmount_prompt_bar_after_submit()  # type: ignore[attr-defined]
            self._prompt_context = None

    def _persist_stashed_panes(
        self,
        panes: list[StashedPromptPane],
        *,
        source: str,
    ) -> None:
        """Append the captured stash unit to the per-user prompt-stash store.

        The originating project (D2 metadata) comes from the active prompt
        context so the Phase 3 restore picker can show a project chip; id and
        timestamp are minted here per entry.  ``gs`` captures arrive as multiple
        panes but are stored as one canonical multi-prompt row.
        """
        from datetime import datetime
        from uuid import uuid4

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import (
            PromptStashEntryWire,
            append_prompt_stash,
        )
        from sase.core.time import get_timezone

        path = prompt_stash_path()
        project = (
            self._prompt_context.project_name
            if self._prompt_context is not None
            else None
        )
        entry = PromptStashEntryWire(
            id=str(uuid4()),
            created_at=datetime.now(get_timezone()).isoformat(),
            text="\n---\n".join(pane.text for pane in panes),
            frontmatter=next(
                (pane.frontmatter for pane in panes if pane.frontmatter), ""
            ),
            project=project,
            source=source,
            pane_index=min(pane.pane_index for pane in panes),
        )
        append_prompt_stash(path, entry)

    # -- restore -------------------------------------------------------------

    async def on_prompt_input_bar_restore_requested(self, event: object) -> None:
        """Open the unified stash panel when the prompt bar requests it."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.RestoreRequested):
            return
        await self._open_prompt_stash_panel(bar_mode=event.mode)

    async def action_restore_prompt_stash(self) -> None:
        """Global ``@`` keymap: open the unified prompt-stash panel.

        Reuses the same flow as the prompt-local ``Ctrl+G p`` restore. No
        ``bar_mode`` is forced: ``_open_prompt_stash_panel`` inspects the mounted
        bar (so a feedback / approve-prompt bar still no-ops) and defaults to
        ``prompt`` mode when no bar is mounted, mounting the home prompt bar
        with the restored drafts.
        """
        await self._open_prompt_stash_panel()

    async def _open_prompt_stash_panel(self, bar_mode: str | None = None) -> None:
        """Read the stash snapshot off-thread and push the unified stash picker.

        Restore is guarded to ``prompt`` bars (D5): a feedback /
        approve-prompt bar toasts a no-op.  When *bar_mode* is ``None`` the
        currently mounted bar — if any — supplies the mode. An empty store
        toasts instead of opening an empty modal. The snapshot read runs on a
        worker thread so key handling never blocks the paint path (boundary rule
        D6).
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

        entries = await asyncio.to_thread(self._read_prompt_stash_entries)
        if not entries:
            self.notify("No stashed prompts to restore")  # type: ignore[attr-defined]
            return

        self.push_screen(  # type: ignore[attr-defined]
            StashedPromptsModal(entries),
            self._on_prompt_stash_restore_confirmed,
        )

    async def _on_prompt_stash_restore_confirmed(self, result: object) -> None:
        """Apply the picker outcome: pop, keep, and delete marked ids."""
        from ...modals import StashRestoreResult

        if not isinstance(result, StashRestoreResult):
            return  # cancelled (None) or unexpected payload

        await self._apply_stash_restore(result)

    async def _apply_stash_restore(self, result: StashRestoreResult) -> None:
        """Apply per-entry pop/keep/delete decisions from the unified panel.

        Snapshot reads and stash pops run off the event loop. The app loads
        ``pop`` + ``keep`` ids oldest-first, removes ``pop`` + ``delete`` ids in
        one store call, and refreshes the badge only when the store changed.
        """
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import pop_prompt_stash

        restore_ids = [*result.pop_ids, *result.keep_ids]
        remove_ids = [*result.pop_ids, *result.delete_ids]
        if not restore_ids and not remove_ids:
            return

        restore_entries: list[PromptStashEntryWire] = []
        if restore_ids:
            snapshot = await asyncio.to_thread(self._read_prompt_stash_entries)
            by_id = {entry.id: entry for entry in snapshot}
            restore_entries = [
                by_id[entry_id] for entry_id in restore_ids if entry_id in by_id
            ]
            # Original drafting order (oldest first); bundle rows expand later
            # in their stored segment order.
            restore_entries.sort(key=lambda entry: (entry.created_at, entry.pane_index))

        removed_ids: set[str] = set()
        if remove_ids:
            try:
                outcome = await asyncio.to_thread(
                    pop_prompt_stash, prompt_stash_path(), remove_ids
                )
            except Exception as exc:  # pragma: no cover - defensive (store/IO error)
                self.notify(  # type: ignore[attr-defined]
                    f"Failed to restore prompt: {exc}", severity="error"
                )
                return
            removed_ids = {entry.id for entry in outcome.removed}

        restored_count = 0
        if restore_entries:
            restored_count = len(self._entries_to_restore_items(restore_entries))
            self._load_restored_entries(restore_entries)

        deleted = sum(1 for entry_id in result.delete_ids if entry_id in removed_ids)
        self._notify_restore_outcome(restored_count, deleted)
        if removed_ids:
            self._refresh_prompt_stash_indicator()

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
            from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

            snapshot = read_prompt_stash_snapshot(prompt_stash_path())
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

    async def on_app_focus(self, _event: object) -> None:
        """Reconcile the badge when the terminal regains focus (D-P4 lifecycle).

        The prompt stash is a single per-user pile (D2), so a *concurrent* ACE
        instance can stash or restore prompts while this app is unfocused.
        Local ops already refresh the badge inline; re-reading the count on
        focus closes the multi-instance drift the Phase-1 plan flagged, without
        a dedicated polling timer.  The disk read runs on a worker thread so the
        focus event never blocks the paint path, and any read/binding failure
        degrades to leaving the badge untouched (``_read_prompt_stash_count``
        already floors to ``0``).
        """
        import asyncio

        try:
            count = await asyncio.to_thread(self._read_prompt_stash_count)
        except Exception:  # pragma: no cover - defensive (thread/IO error)
            return
        self._apply_prompt_stash_count(count)

    def _refresh_prompt_stash_indicator(self) -> None:
        """Reload the stash count from disk and update the top-bar badge."""
        self._apply_prompt_stash_count(self._read_prompt_stash_count())

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
            count = await asyncio.to_thread(self._read_prompt_stash_count)
        except Exception:  # pragma: no cover - defensive (thread/IO error)
            return
        self._apply_prompt_stash_count(count)

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
        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import read_prompt_stash_snapshot

            snapshot = read_prompt_stash_snapshot(prompt_stash_path())
        except Exception:
            return 0
        return len(snapshot.entries)

    def _apply_prompt_stash_count(self, count: int) -> None:
        """Push *count* into the ``StashedPromptsIndicator`` badge widget."""
        from ...widgets import StashedPromptsIndicator

        try:
            indicator = self.query_one(  # type: ignore[attr-defined]
                "#stashed-prompts-indicator", StashedPromptsIndicator
            )
        except Exception:
            return
        indicator.set_count(count)
