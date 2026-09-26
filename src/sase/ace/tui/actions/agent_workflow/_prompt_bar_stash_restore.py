"""Prompt-stash restore and pinned-entry workflows.

This mixin also owns the shared tabbed Prompts overlay opener: every Stash
and History entry point routes through :meth:`_open_prompts_overlay_async`
so the complete Stash | History | Trash overlay (not the legacy standalone
pickers) is what users see. Outcomes arrive as a typed
:class:`PromptsResult` and fan out by producing tab.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from collections.abc import Callable

from ._prompt_bar_stash_store import PromptBarStashStoreMixin
from datetime import UTC

if TYPE_CHECKING:
    from asyncio import Lock

    from sase.ace.tui.modals import StashRestoreResult
    from sase.ace.tui.modals._prompt_history_models import PromptHistoryResult
    from sase.ace.tui.modals.prompts_modal import PromptsModal, PromptsResult
    from sase.ace.tui.prompt_stash_entries import RestoredStashPane
    from sase.core.prompt_stash_wire import (
        PromptStashEntryWire,
        PromptStashLifecycleOutcomeWire,
        PromptStashSnapshotWire,
        PromptStashTrashRecordWire,
    )
    from sase.project_display_names import ProjectDisplaySnapshot


@dataclass(frozen=True)
class _PromptsOverlaySnapshot:
    """Lifecycle collections plus display labels for one overlay open."""

    entries: tuple[PromptStashEntryWire, ...]
    trash: tuple[PromptStashTrashRecordWire, ...]
    trash_limit: int
    project_display_snapshot: ProjectDisplaySnapshot | None = None


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
        """Read the lifecycle snapshot off-thread and restore or open Stash.

        Restore is guarded to ``prompt`` bars (D5): a feedback /
        approve-prompt bar toasts a no-op.  When *bar_mode* is ``None`` the
        currently mounted bar — if any — supplies the mode. An empty Stash
        still opens the overlay (its empty state points at Trash when Trash
        has rows). When *auto_restore_single* is set, a one-entry stash
        restores directly (the bare-``@`` fast path); otherwise the complete
        overlay opens on Stash. The snapshot read runs on a worker thread so
        key handling never blocks the paint path (boundary rule D6).
        """
        if bar_mode is None:
            bar = self._mounted_prompt_bar()
            bar_mode = bar._mode if bar is not None else "prompt"
        if bar_mode != "prompt":
            self.notify(  # type: ignore[attr-defined]
                "Restore is only available for agent prompts", severity="warning"
            )
            return

        from ...modals.prompts_modal import PromptsOrigin

        await self._open_prompts_overlay_async(
            initial_tab="stash",
            origin=PromptsOrigin(kind="live_bar"),
            auto_restore_single=auto_restore_single,
            history_handler=self._apply_live_bar_history_result,
            cancel_handler=self._cancel_prompts_overlay_noop,
        )

    def _read_prompt_stash_overlay_snapshot(self) -> _PromptsOverlaySnapshot:
        """Read lifecycle collections, limit, and labels (worker-safe).

        Falls back to the v1 active-only snapshot with empty Trash when the
        lifecycle binding is unavailable (stale wheel); Trash then simply
        shows empty until the core upgrade lands.
        """
        from sase.ace.config import get_ace_prompt_stash_trash_limit
        from sase.project_display_names import load_project_display_snapshot

        trash_limit = get_ace_prompt_stash_trash_limit()
        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

            lifecycle = read_prompt_stash_lifecycle(prompt_stash_path())
            entries = tuple(lifecycle.active)
            trash = tuple(lifecycle.trash)
        except Exception:
            entries = tuple(self._read_prompt_stash_entries())
            trash = ()
        try:
            snapshot = load_project_display_snapshot()
        except Exception:
            snapshot = None
        return _PromptsOverlaySnapshot(
            entries=entries,
            trash=trash,
            trash_limit=trash_limit,
            project_display_snapshot=snapshot,
        )

    async def _open_prompts_overlay_async(
        self,
        *,
        initial_tab: str,
        origin: object,
        auto_restore_single: bool = False,
        history_handler: Callable[[object], None] | None = None,
        cancel_handler: Callable[[], None] | None = None,
    ) -> None:
        """Open the complete Prompts overlay on *initial_tab*.

        Every Stash and History entry point funnels here so discard and
        recovery are always available together. *history_handler* receives
        the :class:`PromptHistoryResult` when the History tab dismisses the
        overlay; *cancel_handler* runs on dismiss-without-result. Stash and
        Trash outcomes apply through the shared lifecycle dispatch. A lowered
        configured limit is reconciled on open and its evictions surfaced.
        """
        import asyncio

        from ...modals.prompts_modal import PromptsModal, PromptsOrigin, PromptsTab

        tab = {
            "stash": PromptsTab.STASH,
            "history": PromptsTab.HISTORY,
            "trash": PromptsTab.TRASH,
        }.get(initial_tab, PromptsTab.STASH)
        assert isinstance(origin, PromptsOrigin)

        try:
            overlay = await asyncio.to_thread(self._read_prompt_stash_overlay_snapshot)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read stashed prompts",
                    exc,
                ),
                severity="error",
            )
            return

        await self._reconcile_trash_limit_on_open(overlay)

        if (
            auto_restore_single
            and len(overlay.entries) == 1
            and tab is PromptsTab.STASH
        ):
            await self._auto_restore_single_entry(overlay.entries[0])
            return

        def _on_result(result: object) -> None:
            self._forget_prompts_overlay()
            self._on_prompts_overlay_result(
                result,
                history_handler=history_handler,
                cancel_handler=cancel_handler,
            )

        modal = PromptsModal(
            list(overlay.entries),
            project_display_snapshot=overlay.project_display_snapshot,
            origin=origin,
            initial_tab=tab,
            trash=list(overlay.trash),
            trash_limit=overlay.trash_limit,
        )
        self._remember_prompts_overlay(modal)
        self.push_screen(  # type: ignore[attr-defined]
            modal,
            _on_result,
        )

    async def _reconcile_trash_limit_on_open(
        self, overlay: _PromptsOverlaySnapshot
    ) -> None:
        """Enforce a lowered trash limit before presenting the overlay.

        Over-limit Trash rows are permanently deleted oldest-first in the
        same Rust transaction; the actual evictions are surfaced so the
        permanent loss is never silent. Fail-open: a reconciliation error
        leaves the on-disk state untouched and the overlay still opens.
        """
        if len(overlay.trash) <= overlay.trash_limit:
            return
        import asyncio

        try:
            from sase.core.paths import prompt_stash_path
            from sase.core.prompt_stash_facade import reconcile_prompt_stash_trash

            outcome = await asyncio.to_thread(
                reconcile_prompt_stash_trash,
                prompt_stash_path(),
                overlay.trash_limit,
            )
        except Exception as exc:  # pragma: no cover - defensive (store/IO error)
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to reconcile Trash limit",
                    exc,
                ),
                severity="error",
            )
            return
        if outcome.evicted:
            lost = len(outcome.evicted)
            noun = "draft" if lost == 1 else "drafts"
            self.notify(  # type: ignore[attr-defined]
                f"Trash limit lowered to {overlay.trash_limit}: "
                f"permanently deleted {lost} oldest {noun}"
            )
        self._apply_prompt_stash_lifecycle_counts(outcome)

    def _on_prompts_overlay_result(
        self,
        result: object,
        *,
        history_handler: Callable[[object], None] | None = None,
        cancel_handler: Callable[[], None] | None = None,
    ) -> None:
        """Fan a :class:`PromptsResult` out by its producing tab.

        Stash outcomes restore into the prompt bar and move discards to
        Trash; History outcomes run the entry point's own callback so a tab
        switch can never silently apply the wrong action; Trash outcomes
        restore to Stash or purge permanently. ``None`` (Esc / ``q``) runs
        the entry point's cancel path.
        """
        from ...modals.prompts_modal import PromptsResult, PromptsTab

        if result is None:
            if cancel_handler is not None:
                cancel_handler()
            return
        if not isinstance(result, PromptsResult):
            return  # unexpected payload (e.g. legacy standalone result)
        if result.tab is PromptsTab.STASH and result.stash is not None:
            self._spawn_prompt_stash_task(
                self._apply_prompts_stash_result(result.stash)
            )
        elif result.tab is PromptsTab.HISTORY and result.history is not None:
            if history_handler is not None:
                history_handler(result.history)
        elif result.tab is PromptsTab.TRASH and result.trash is not None:
            self._spawn_prompt_stash_task(
                self._apply_prompts_trash_result(result.trash)
            )

    def _cancel_prompts_overlay_noop(self) -> None:
        """Dismiss-without-result from a Stash open changes nothing."""

    def _apply_live_bar_history_result(self, result: object) -> None:
        """Apply a History-tab outcome for a stash-opened overlay.

        The overlay opened from Stash carries no launch context, so every
        History action loads text into the prompt bar as a draft — nothing
        ever submits directly from here. EDIT opens the editor first, then
        loads the edited text the same way.
        """
        from ...modals import PromptHistoryAction

        action = getattr(result, "action", None)
        text = str(getattr(result, "prompt_text", ""))
        if action is PromptHistoryAction.EDIT_FIRST:
            self._edit_history_text_into_bar(text)
            return
        self._load_history_text_into_bar(text)

    def _load_history_text_into_bar(self, text: str) -> None:
        """Load history text into the mounted bar, or mount the home bar."""
        bar = self._mounted_prompt_bar()
        if bar is not None and bar._mode == "prompt":
            try:
                bar.load_prompt_into_pane(bar.active_text_area(), "", text)
                return
            except Exception:
                pass
        self._show_prompt_input_bar_for_home(  # type: ignore[attr-defined]
            initial_text=text,
        )

    def _edit_history_text_into_bar(self, text: str) -> None:
        """Edit history text in $EDITOR, then load it as a bar draft."""
        from ._prompt_bar_mount import strip_editor_review_markers

        try:
            edited = self._open_editor_for_agent_prompt(text)  # type: ignore[attr-defined]
        except Exception:
            edited = None
        if not edited:
            self.notify(  # type: ignore[attr-defined]
                "No prompt from editor - cancelled", severity="warning"
            )
            return
        _marked, cleaned = strip_editor_review_markers(edited)
        self._load_history_text_into_bar(cleaned)

    async def _apply_prompts_stash_result(self, result: StashRestoreResult) -> None:
        """Apply a Stash-tab dismiss: restore pop/keep, trash discards.

        Trash marks confirm first (with the expected permanent-loss count),
        then move through Rust; the success toast names the actual evictions
        because other processes may change Trash between preview and commit.
        Restores load oldest-first; the badge follows authoritative counts.
        """
        from ...modals import StashRestoreResult

        if result.trash_ids:
            confirmed = await self._confirm_trash_commit_async(list(result.trash_ids))
            if confirmed:
                await self._trash_entries_async(list(result.trash_ids))
        rest = StashRestoreResult(
            pop_ids=list(result.pop_ids),
            keep_ids=list(result.keep_ids),
            delete_ids=list(result.delete_ids),
        )
        if rest.pop_ids or rest.keep_ids or rest.delete_ids:
            await self._apply_stash_restore(rest)

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

    # -- trash lifecycle mutations (confirm → Rust → authoritative repaint) ---

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
        """Confirm staged Stash → Trash marks, apply, and repaint in place."""
        if not entry_ids:
            return
        confirmed = await self._confirm_trash_commit_async(entry_ids)
        if confirmed:
            await self._trash_entries_async(entry_ids)

    async def _purge_staged_in_place_async(self, entry_ids: list[str]) -> None:
        """Confirm staged purges, apply, and repaint in place."""
        if not entry_ids:
            return
        confirmed = await self._confirm_purge_async(entry_ids)
        if confirmed:
            await self._purge_trashed_async(entry_ids)

    async def _confirm_trash_commit_async(self, entry_ids: list[str]) -> bool:
        """Confirm a Stash → Trash move with overflow/pinned consequences."""
        import asyncio

        from ...modals.stash_pane import (
            preview_trash_commit,
            trash_commit_confirm_text,
        )

        try:
            overlay = await asyncio.to_thread(self._read_prompt_stash_overlay_snapshot)
        except Exception as exc:
            self.notify(  # type: ignore[attr-defined]
                self._prompt_stash_error_message(
                    "Failed to read stashed prompts",
                    exc,
                ),
                severity="error",
            )
            return False
        preview = preview_trash_commit(
            list(entry_ids),
            list(overlay.entries),
            trash_count=len(overlay.trash),
            trash_limit=overlay.trash_limit,
        )
        if not preview.marked_ids:
            return False  # stale selection: nothing live to move
        return await self._confirm_async(
            "Move to Trash",
            trash_commit_confirm_text(preview),
        )

    async def _confirm_purge_async(self, entry_ids: list[str]) -> bool:
        """Confirm permanent deletion of Trash rows."""
        import asyncio

        from ...modals.trash_pane import purge_confirm_text

        try:
            overlay = await asyncio.to_thread(self._read_prompt_stash_overlay_snapshot)
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
        from datetime import datetime, timezone

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
            self.notify(f"Permanently deleted {purged} {noun}")  # type: ignore[attr-defined]
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

        lock = self._prompt_stash_write_lock()
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
            restored_count = len(self._entries_to_restore_panes(restore_entries))
            self._load_restored_entries(restore_entries)

        deleted = sum(1 for entry_id in result.delete_ids if entry_id in removed_ids)
        self._notify_restore_outcome(restored_count, deleted)
        if removed_ids and snapshot_after_remove is not None:
            self._apply_prompt_stash_snapshot_counts(snapshot_after_remove)

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
            for pane in PromptBarStashRestoreMixin._entries_to_restore_panes(entries)
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
