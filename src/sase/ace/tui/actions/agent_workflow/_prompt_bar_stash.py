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
        timestamp are minted here per entry.  ``gS`` captures arrive as multiple
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

    # -- restore / load ------------------------------------------------------

    async def on_prompt_input_bar_restore_requested(self, event: object) -> None:
        """Open the restore/load picker when the bar requests it (``gP``/``gp``)."""
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.RestoreRequested):
            return
        await self._open_prompt_stash_restore(
            bar_mode=event.mode, destructive=event.destructive
        )

    async def _open_prompt_stash_restore(
        self, bar_mode: str | None = None, *, destructive: bool = True
    ) -> None:
        """Read the stash snapshot off-thread and push the restore/load picker.

        Restore/load is guarded to ``prompt`` bars (D5): a feedback /
        approve-prompt bar toasts a no-op.  When *bar_mode* is ``None`` the
        currently mounted bar — if any — supplies the mode.  ``destructive``
        selects the picker mode: ``gP`` pops the chosen entries, ``gp`` copies
        them and leaves the stash intact.  An empty store toasts instead of
        opening an empty modal.  The snapshot read runs on a worker thread so key
        handling never blocks the paint path (boundary rule D6).
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
            StashedPromptsModal(entries, destructive=destructive),
            self._on_prompt_stash_restore_confirmed,
        )

    async def _on_prompt_stash_restore_confirmed(self, result: object) -> None:
        """Apply the picker outcome: destructive pop-and-load, or non-destructive load."""
        from ...modals import StashRestoreResult

        if not isinstance(result, StashRestoreResult):
            return  # cancelled (None) or unexpected payload

        if result.destructive:
            await self._apply_destructive_restore(result)
        else:
            await self._apply_nondestructive_load(result)

    async def _apply_destructive_restore(self, result: StashRestoreResult) -> None:
        """Pop the chosen entries, load the restored drafts, refresh the badge.

        The pop is a whole-file rewrite, so it runs on a worker thread; the load
        and badge refresh happen back on the UI thread once it completes.
        """
        import asyncio

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import pop_prompt_stash

        ids = [*result.restore_ids, *result.delete_ids]
        if not ids:
            return

        try:
            outcome = await asyncio.to_thread(
                pop_prompt_stash, prompt_stash_path(), ids
            )
        except Exception as exc:  # pragma: no cover - defensive (store/IO error)
            self.notify(  # type: ignore[attr-defined]
                f"Failed to restore prompt: {exc}", severity="error"
            )
            return

        removed = {entry.id: entry for entry in outcome.removed}
        restored: list[PromptStashEntryWire] = [
            removed[entry_id] for entry_id in result.restore_ids if entry_id in removed
        ]
        # Original drafting order (oldest first); bundle rows expand later in
        # their stored segment order.
        restored.sort(key=lambda entry: (entry.created_at, entry.pane_index))
        restored_count = 0
        if restored:
            restored_count = len(self._entries_to_restore_items(restored))
            self._load_restored_entries(restored)

        deleted = sum(1 for entry_id in result.delete_ids if entry_id in removed)
        self._notify_restore_outcome(restored_count, deleted)
        self._refresh_prompt_stash_indicator()

    async def _apply_nondestructive_load(self, result: StashRestoreResult) -> None:
        """Copy the chosen entries into the bar without touching the store (``gp``).

        Reads the snapshot off-thread, loads the selected entries oldest-first
        with the same ``(created_at, pane_index)`` ordering as a destructive
        restore, and leaves both the stash and its badge untouched.
        """
        import asyncio

        restore_ids = list(result.restore_ids)
        if not restore_ids:
            return

        snapshot = await asyncio.to_thread(self._read_prompt_stash_entries)
        by_id = {entry.id: entry for entry in snapshot}
        loaded: list[PromptStashEntryWire] = [
            by_id[entry_id] for entry_id in restore_ids if entry_id in by_id
        ]
        loaded.sort(key=lambda entry: (entry.created_at, entry.pane_index))
        if not loaded:
            return

        self._load_restored_entries(loaded)
        count = len(self._entries_to_restore_items(loaded))
        self.notify(  # type: ignore[attr-defined]
            "Loaded prompt" if count == 1 else f"Loaded {count} prompts"
        )
        # The entries stay in the stash, so the badge is intentionally unchanged.

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
            initial_text=self._stash_entries_to_prompt_text(entries)
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
