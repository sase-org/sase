"""Prompt-stash overlay opener and history-to-bar loading.

Every Stash and History entry point routes through
:meth:`PromptBarStashRestoreOverlayMixin._open_prompts_overlay_async`
so the complete Stash | History | Trash overlay (not the legacy standalone
pickers) is what users see. Outcomes arrive as a typed
:class:`PromptsResult` and fan out by producing tab.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._prompt_bar_stash_store import PromptBarStashStoreMixin

if TYPE_CHECKING:
    from sase.core.prompt_stash_wire import (
        PromptStashEntryWire,
        PromptStashTrashRecordWire,
    )
    from sase.project_display_names import ProjectDisplaySnapshot


@dataclass(frozen=True)
class PromptsOverlaySnapshot:
    """Lifecycle collections plus display labels for one overlay open."""

    entries: tuple[PromptStashEntryWire, ...]
    trash: tuple[PromptStashTrashRecordWire, ...]
    trash_limit: int
    project_display_snapshot: ProjectDisplaySnapshot | None = None


class PromptBarStashRestoreOverlayMixin(PromptBarStashStoreMixin):
    """Open the shared Prompts overlay and load history results into the bar."""

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

    def _read_prompt_stash_overlay_snapshot(self) -> PromptsOverlaySnapshot:
        """Read lifecycle collections, limit, and labels (worker-safe).

        The lifecycle read is authoritative and fail-closed: a missing
        binding (stale wheel), parse failure, or store read/lock error
        propagates to the caller, which surfaces the actual error and never
        opens a misleading overlay with empty Trash. A missing stash file
        is benign inside the lifecycle binding's own contract (it reads as
        empty). Only the display-only project labels degrade to ``None``.
        """
        from sase.ace.config import get_ace_prompt_stash_trash_limit
        from sase.project_display_names import load_project_display_snapshot

        trash_limit = get_ace_prompt_stash_trash_limit()
        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import read_prompt_stash_lifecycle

        lifecycle = read_prompt_stash_lifecycle(prompt_stash_path())
        entries = tuple(lifecycle.active)
        trash = tuple(lifecycle.trash)
        try:
            snapshot = load_project_display_snapshot()
        except Exception:
            snapshot = None
        return PromptsOverlaySnapshot(
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
            await self._auto_restore_single_entry(overlay.entries[0])  # type: ignore[attr-defined]
            return

        def _on_result(result: object) -> None:
            self._forget_prompts_overlay()  # type: ignore[attr-defined]
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
        self._remember_prompts_overlay(modal)  # type: ignore[attr-defined]
        self.push_screen(  # type: ignore[attr-defined]
            modal,
            _on_result,
        )

    async def _reconcile_trash_limit_on_open(
        self, overlay: PromptsOverlaySnapshot
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
        self._apply_prompt_stash_lifecycle_counts(outcome)  # type: ignore[attr-defined]

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
                self._apply_prompts_stash_result(result.stash)  # type: ignore[attr-defined]
            )
        elif result.tab is PromptsTab.HISTORY and result.history is not None:
            if history_handler is not None:
                history_handler(result.history)
        elif result.tab is PromptsTab.TRASH and result.trash is not None:
            self._spawn_prompt_stash_task(
                self._apply_prompts_trash_result(result.trash)  # type: ignore[attr-defined]
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
