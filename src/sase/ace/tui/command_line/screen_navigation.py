"""Transcript navigation behavior for ``CommandLineScreen``."""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import TYPE_CHECKING, Any, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from sase.ace.tui.command_line.builtins import (
    BuiltinOutcome,
    builtin_name_for,
    render_help,
    render_history,
    run_cd,
    run_clear,
)
from sase.ace.tui.command_line.context import (
    CommandLineContext,
    resolve_launch_cwd,
    resolve_working_context,
    working_context_chip,
)
from sase.ace.tui.command_line.extras import (
    doc_peek_for_highlight,
    doc_peek_visible,
    empty_state_hint,
    empty_state_rows,
    marked_insert_text,
    marked_values_for_kind,
    provider_unavailable_note,
    rank_history_entries,
    selected_entity_kind,
    slot_is_variadic,
)
from sase.ace.tui.command_line.grammar import (
    command_line_grammar_for,
    is_command_line_grammar_pending,
    resolve_command_line,
)
from sase.ace.tui.command_line.input import CommandLineInput
from sase.ace.tui.command_line.policies import (
    append_confirm_flag,
    deny_note_for,
    run_in_terminal,
    submit_route_for,
)
from sase.ace.tui.command_line.popup import (
    CommandLinePopup,
    PopupDecision,
    popup_footer,
)
from sase.ace.tui.command_line.restore import load_block_tail_text
from sase.ace.tui.command_line.screen_constants import (
    COMMAND_LINE_BLOCK_HINTS,
    COMMAND_LINE_IDLE_HINT,
    COMMAND_LINE_INDEXING_HINT,
    COMMAND_LINE_INPUT_HINTS,
    COMMAND_LINE_MENU_HINTS,
    COMMAND_LINE_SEARCH_HINT,
)
from sase.ace.tui.command_line.session import CommandLineBlock, tokenize_command_line
from sase.ace.tui.command_line.signature import signature_hint_line
from sase.ace.tui.command_line.sources import (
    PROVIDER_DEBOUNCE_SECONDS,
    collect_dynamic_candidates,
    needs_provider_fetch,
)
from sase.ace.tui.command_line.submit import (
    PreparedSubmit,
    apply_local_block,
    apply_submit_failure,
    apply_submit_success,
    capture_resolve_context,
    prepare_submit,
    submit_in_worker,
)
from sase.completion.command_line_grammar import LineContext


class CommandLineScreenNavigationMixin:
    """Behavior mixed into the public command-line screen."""

    _walk_anchor: str | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def history_step(self, direction: int) -> None:
        """Walk history filtered by the typed prefix (``↑``/``↓``)."""
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot walk.
            return
        if self._walk_anchor is None:
            self._walk_anchor = widget.text
        self._history.anchor = self._walk_anchor
        cwd = self._working_context.cwd if self._working_context else None
        match = self._history.walk(self._walk_anchor, direction=direction, cwd=cwd)
        self._applying_history = True
        try:
            widget.set_line(match if match is not None else self._walk_anchor)
        finally:
            self._applying_history = False
        self._store_draft()
        self._update_ghost()

    async def hop_to_palette(self) -> None:
        """Dismiss the panel and open the Command Palette."""
        app = self.app
        await self.dismiss(None)
        open_palette = getattr(app, "action_open_command_palette", None)
        if callable(open_palette):
            open_palette()

    def action_toggle_full_height(self) -> None:
        """Toggle the full-height frame (``ctrl+t``)."""
        session = self.session
        session.full_height = not session.full_height
        try:
            frame = self.query_one("#command-line-frame", Vertical)
            frame.set_class(session.full_height, "full-height")
        except Exception:  # noqa: BLE001 - unmounted screen cannot restyle.
            pass

    def action_clear_transcript(self) -> None:
        """Clear finished blocks; running procs are untouched (``ctrl+l``)."""
        self.session.clear_transcript()
        self._refresh_transcript()
        self._update_running()

    def action_hide_panel(self) -> None:
        """Hide the panel; running commands continue and the draft is kept."""
        self._store_draft()
        self.dismiss(None)

    def refresh_transcript(self) -> None:
        """Repaint the transcript and running count from session state."""
        self._refresh_transcript()
        self._update_running()
        self._update_hints()

    def _refresh_transcript(self) -> None:
        try:
            self.transcript.refresh_blocks(
                self.session.blocks,
                selected_id=self.session.selected_block_id,
            )
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            pass

    def _update_hints(self) -> None:
        """Show block keys while a block is selected, input keys otherwise."""
        try:
            keys = self.query_one("#command-line-keys", Static)
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            return
        if self.session.selected_block_id is not None:
            keys.update(COMMAND_LINE_BLOCK_HINTS)
        else:
            keys.update(COMMAND_LINE_INPUT_HINTS)

    # -- NORMAL-mode block navigation --------------------------------------

    #: Forwarded NORMAL-mode keys (from the input widget) to screen handlers.
    _BLOCK_NAV_KEYS = frozenset(
        {
            "j",
            "k",
            "g",
            "G",
            "o",
            "v",
            "K",
            "r",
            "R",
            "e",
            "y",
            "Y",
            "p",
            "x",
            "i",
            "a",
            "enter",
            "up",
            "down",
            "colon",
        }
    )

    def handle_block_nav_key(self, key: str) -> bool:
        """Dispatch one forwarded NORMAL-mode key; False when unhandled."""
        if key not in self._BLOCK_NAV_KEYS:
            return False
        handler = {
            "j": self._select_next,
            "down": self._select_next,
            "k": self._select_prev,
            "up": self._select_prev,
            "g": self._select_first,
            "G": self._select_last,
            "o": self.toggle_selected_expand,
            "enter": self.toggle_selected_expand,
            "v": self.open_selected_in_pager,
            "K": self.kill_selected_block,
            "r": self.rerun_selected_block,
            "R": self.rerun_selected_with_confirm_flag,
            "e": self.edit_selected_block,
            "y": self.copy_selected_output,
            "Y": self.copy_selected_command,
            "p": self.open_selected_in_procs,
            "x": self.remove_selected_block,
            "i": self.focus_input,
            "a": self.focus_input,
            "colon": self.focus_input,
        }[key]
        handler()
        return True

    def _select_next(self) -> None:
        """Select the next block, entering the transcript at the last one."""
        self._after_selection(self.session.move_selection(1))

    def _select_prev(self) -> None:
        """Select the previous block, entering the transcript at the last one."""
        self._after_selection(self.session.move_selection(-1))

    def _select_first(self) -> None:
        """Jump the selection to the first block."""
        self._after_selection(self.session.select_first())

    def _select_last(self) -> None:
        """Jump the selection to the last block."""
        self._after_selection(self.session.select_last())

    def _after_selection(self, block: CommandLineBlock | None) -> None:
        """Repaint after a selection move and lazily load the viewed tail."""
        if block is not None:
            self._ensure_block_tail(block)
        self._refresh_transcript()
        self._update_hints()

    def selected_block(self) -> CommandLineBlock | None:
        """Return the NORMAL-mode selected block, if any."""
        return self.session.selected_block()

    def toggle_selected_expand(self) -> bool:
        """Expand or collapse the selected block (``o`` / ``⏎``)."""
        block = self.selected_block()
        if block is None:
            return False
        block.expanded = not block.expanded
        block.unseen = False
        if block.expanded:
            self._ensure_block_tail(block)
        self._refresh_transcript()
        return True

    def open_selected_in_pager(self) -> bool:
        """Open the selected block's full sanitized log in ``PagerScreen``."""
        block = self.selected_block()
        if block is None:
            return False
        block.unseen = False
        if not block.tail_loaded and block.proc_id is not None:
            run_worker = getattr(self.app, "run_worker", None)
            if callable(run_worker):
                run_worker(self._open_pager_worker(block.block_id), exclusive=False)
                return True
        self._push_block_pager(block)
        return True

    async def _open_pager_worker(self, block_id: str) -> None:
        """Load a block's tail off-thread, then push its pager on the app."""
        block = self.session.block_by_id(block_id)
        if block is None:
            return
        try:
            from sase.ace.tui.command_line import screen as screen_module

            await asyncio.to_thread(screen_module.load_block_tail_text, block)
        except Exception:  # noqa: BLE001 - lazy tails are best effort.
            pass
        # The worker coroutine resumes on the app loop. Re-capture after the
        # await: the block or panel may have gone away while its tail loaded.
        block = self.session.block_by_id(block_id)
        if block is None or self.app.screen is not self:
            return
        self._refresh_transcript()
        self._push_block_pager(block)

    def _push_block_pager(self, block: CommandLineBlock) -> None:
        """Push ``PagerScreen`` for one block's cached output."""
        from rich.text import Text as _Text

        from sase.pager.document import PagerDocument, PagerSection
        from sase.pager.link_scan import PagerOrigin
        from sase.pager.screen import PagerScreen

        from sase.ace.tui.command_line.block_render import sanitize_block_output

        body_text = block.tail_text or "(no output)"
        body = _Text.from_ansi(sanitize_block_output(body_text))
        document = PagerDocument(
            sections=(
                PagerSection(
                    identity=block.block_id,
                    title=f": {block.line}",
                    kind="text",
                    body=body,
                ),
            ),
            title=f": {block.line}",
            origin=PagerOrigin.FILE,
        )
        self.app.push_screen(PagerScreen(document))

    def kill_selected_block(self) -> bool:
        """Kill the selected running proc after confirmation (``K``)."""
        from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
        from sase.ace.tui.modals.confirm_dialog import ConfirmKind
        from sase.ace.tui.modals.procs_store_rows import kill_store_task

        block = self.selected_block()
        if block is None:
            return False
        if not block.running or block.proc_id is None:
            self.notify("Proc already finished", severity="warning")
            return True
        proc_id = block.proc_id

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            error = kill_store_task(proc_id)
            if error is not None:
                self.notify(f"Kill failed: {error}", severity="error")

        self.app.push_screen(
            ConfirmActionModal(
                title="Kill Proc",
                message=f"Kill running proc: {block.line}?",
                kind=ConfirmKind.DANGER,
                confirm_label="Kill",
                cancel_label="Cancel",
            ),
            _on_confirm,
        )
        return True

    def rerun_selected_block(self) -> bool:
        """Rerun the selected block's line as a new block (``r``)."""
        block = self.selected_block()
        if block is None:
            return False
        return self._submit_line(block.line, bypass_dedup=True, select=True)

    def rerun_selected_with_confirm_flag(self) -> bool:
        """Rerun the selected line visibly appended with ``-y`` (``R``)."""
        block = self.selected_block()
        if block is None:
            return False
        return self._submit_line(
            append_confirm_flag(block.line), bypass_dedup=True, select=True
        )

    def edit_selected_block(self) -> bool:
        """Load the selected block's line into the input for editing (``e``)."""
        block = self.selected_block()
        if block is None:
            return False
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot edit.
            return False
        self.session.select_block(None)
        widget.set_line(block.line)
        self._store_draft()
        self._update_ghost()
        self.focus_input()
        self._refresh_transcript()
        self._update_hints()
        return True

    def copy_selected_output(self) -> bool:
        """Copy the selected block's output (``y``)."""
        from sase.ace.tui.actions.clipboard import schedule_copy_delivery

        block = self.selected_block()
        if block is None:
            return False
        if not block.tail_text:
            self.notify("No output available", severity="warning")
            return True
        line_count = block.tail_text.count("\n") + (
            0 if block.tail_text.endswith("\n") else 1
        )
        schedule_copy_delivery(
            self,
            block.tail_text,
            copied_label=f"block output ({line_count} lines)",
            task_name="sase-copy-command-line-output",
        )
        return True

    def copy_selected_command(self) -> bool:
        """Copy the selected block's command line (``Y``)."""
        from sase.ace.tui.actions.clipboard import schedule_copy_delivery

        block = self.selected_block()
        if block is None:
            return False
        schedule_copy_delivery(
            self,
            block.line,
            copied_label="block command",
            task_name="sase-copy-command-line-command",
        )
        return True

    def open_selected_in_procs(self) -> bool:
        """Open Admin Center → Procs with the selected proc focused (``p``)."""
        block = self.selected_block()
        if block is None:
            return False
        if block.proc_id is None:
            self.notify("No proc record for this block", severity="warning")
            return True
        opener = getattr(self.app, "_open_config_center", None)
        if not callable(opener):
            return False
        opener("procs", proc_focus_target=block.proc_id)
        return True

    def remove_selected_block(self) -> bool:
        """Remove the selected block; the proc record stays (``x``)."""
        block = self.selected_block()
        if block is None:
            return False
        self.session.remove_block(block.block_id)
        self._refresh_transcript()
        self._update_running()
        self._update_hints()
        return True

    def focus_input(self) -> bool:
        """Return to the input in INSERT mode (``i`` / ``a`` / ``:``)."""
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen has no input.
            return False
        self.session.select_block(None)
        try:
            widget.focus()
        except Exception:  # noqa: BLE001 - focus is best effort.
            pass
        enter_insert = getattr(widget, "_enter_insert_mode", None)
        if callable(enter_insert):
            try:
                enter_insert()
            except Exception:  # noqa: BLE001 - mode switch is best effort.
                pass
        self._refresh_transcript()
        self._update_hints()
        return True

    # -- screen-binding entry points (input NORMAL mode forwards directly) --

    def action_block_next(self) -> None:
        """Select the next transcript block."""
        self._select_next()

    def action_block_prev(self) -> None:
        """Select the previous transcript block."""
        self._select_prev()

    def action_block_first(self) -> None:
        """Jump to the first transcript block."""
        self._select_first()

    def action_block_last(self) -> None:
        """Jump to the last transcript block."""
        self._select_last()

    def action_block_toggle_expand(self) -> None:
        """Expand or collapse the selected block."""
        self.toggle_selected_expand()

    def action_block_pager(self) -> None:
        """Open the selected block in the pager."""
        self.open_selected_in_pager()

    def action_block_kill(self) -> None:
        """Kill the selected block's proc after confirmation."""
        self.kill_selected_block()

    def action_block_rerun(self) -> None:
        """Rerun the selected block's line."""
        self.rerun_selected_block()

    def action_block_rerun_confirm(self) -> None:
        """Rerun the selected line with ``-y`` appended."""
        self.rerun_selected_with_confirm_flag()

    def action_block_edit(self) -> None:
        """Load the selected block's line into the input."""
        self.edit_selected_block()

    def action_block_copy_output(self) -> None:
        """Copy the selected block's output."""
        self.copy_selected_output()

    def action_block_copy_command(self) -> None:
        """Copy the selected block's command."""
        self.copy_selected_command()

    def action_block_procs(self) -> None:
        """Open Admin Center → Procs on the selected proc."""
        self.open_selected_in_procs()

    def action_block_remove(self) -> None:
        """Remove the selected block from the transcript."""
        self.remove_selected_block()

    def action_block_focus_input(self) -> None:
        """Return to the input in INSERT mode."""
        self.focus_input()

    def _update_running(self) -> None:
        count = len(self.session.running_blocks())
        try:
            running = self.query_one("#command-line-running", Static)
            running.update(f"{count} running")
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            pass

    def _update_chip(self) -> None:
        context = self._working_context
        if context is None:
            return
        try:
            chip = self.query_one("#command-line-chip", Static)
            chip.update(working_context_chip(context))
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            pass

    def _update_ghost(self) -> None:
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen has no ghost.
            return
        cwd = self._working_context.cwd if self._working_context else None
        try:
            widget.suggestion = self._history.ghost(widget.text, cwd=cwd)
        except Exception:  # noqa: BLE001 - ghost text is best effort.
            pass

    # -- grammar-aware completion ------------------------------------------------


__all__ = ["CommandLineScreenNavigationMixin"]
