"""Bottom-anchored Command Line panel screen (bound to ``:``).

View-only composition over the app-held
:class:`~sase.ace.tui.command_line.session.CommandLineSession`: transcript,
completion popup, input row with the implicit ``❯ sase `` prefix, and a
signature/hint row. Submission creates an optimistic block plus an observer
placeholder at once, then submits in a thread worker; failures turn the
block red and restore the line. Tailing and exit settling reuse the proc
plumbing from the proc-plumbing phase (``ProcLogCursor``, exit watches,
ref-counted tails).

The completion-popup phase wires the frozen ``CommandLineGrammar`` into the
input: every edit resolves synchronously (tokens, slot, diagnostics,
signature, run policy), the floating popup shows Rust-ranked candidates
fed by in-memory TUI entities plus debounced providers, and the signature
row renders the live signature with its policy chips.
NORMAL-mode block navigation (``j``/``k``/``g``/``G`` plus the block action
keys) is handled here; the input widget forwards those keys while in NORMAL
mode so they never edit the line.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, cast

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingsMap
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.command_line.block_render import (
    BLOCK_SPINNER_FRAMES,  # noqa: F401 - re-exported for golden tests.
)
from sase.ace.tui.command_line.builtins import (
    BuiltinOutcome,
    builtin_name_for,
    render_help,
    render_history,
    run_cd,
    run_clear,
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
from sase.ace.tui.command_line.context import (
    CommandLineContext,
    resolve_launch_cwd,
    resolve_working_context,
    working_context_chip,
)
from sase.ace.tui.command_line.policies import (
    append_confirm_flag,
    deny_note_for,
    run_in_terminal,
    submit_route_for,
)
from sase.ace.tui.command_line.grammar import (
    command_line_grammar_for,
    ensure_command_line_grammar_loaded,
    is_command_line_grammar_pending,
    resolve_command_line,
)
from sase.ace.tui.command_line.history import CommandLineHistory
from sase.ace.tui.command_line.input import (
    COMMAND_LINE_PREFIX,
    CommandLineInput,
    command_line_keymaps_for,
)
from sase.ace.tui.keymaps import build_command_line_bindings
from sase.ace.tui.keymaps.app_keymaps import CommandLineKeymaps
from sase.ace.tui.keymaps.defaults import load_builtin_command_line_defaults
from sase.ace.tui.command_line.popup import (
    CommandLinePopup,
    CompletionPopupState,
    PopupDecision,
    popup_footer,
)
from sase.ace.tui.command_line.restore import (
    block_from_proc,
    ensure_block_for_proc,
    load_block_tail_text,
    read_command_line_store_rows,
    refresh_pruned_flags,
    restore_missing_blocks,
)
from sase.ace.tui.command_line.session import (
    CommandLineBlock,
    CommandLineSession,
    command_line_session_for,
    tokenize_command_line,
)
from sase.ace.tui.command_line.signature import signature_hint_line
from sase.ace.tui.command_line.sources import (
    PROVIDER_DEBOUNCE_SECONDS,
    ProviderCache,
    collect_dynamic_candidates,
    needs_provider_fetch,
    selected_entity_values,
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
from sase.ace.tui.command_line.transcript import CommandLineTranscript
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.completion.command_line_grammar import LineContext

#: Idle hint shown in the signature row before the resolver lands.
from sase.ace.tui.command_line.screen_completion import CommandLineScreenCompletionMixin
from sase.ace.tui.command_line.screen_constants import (
    COMMAND_LINE_BLOCK_HINTS,
    COMMAND_LINE_IDLE_HINT,
    COMMAND_LINE_INDEXING_HINT,
    COMMAND_LINE_INPUT_HINTS,
    COMMAND_LINE_MENU_HINTS,
    COMMAND_LINE_SEARCH_HINT,
)
from sase.ace.tui.command_line.screen_navigation import CommandLineScreenNavigationMixin
from sase.ace.tui.command_line.screen_submission import CommandLineScreenSubmissionMixin


class CommandLineScreen(
    CommandLineScreenSubmissionMixin,
    CommandLineScreenNavigationMixin,
    CommandLineScreenCompletionMixin,
    ModalScreen[None],
):
    """Bottom-anchored ``:`` Command Line drawer."""

    #: Instance bindings replace this: they are built from the live
    #: ``ace.keymaps.command_line`` scope (see :meth:`__init__` and
    #: :meth:`on_mount`), so user overrides take effect on open.
    BINDINGS = []

    DEFAULT_CSS = """
    CommandLineScreen {
        align: center bottom;
    }
    #command-line-frame {
        width: 96%;
        max-width: 160;
        height: auto;
        max-height: 65%;
        border: round $primary;
        background: $surface;
    }
    #command-line-frame.full-height {
        height: 100%;
        max-height: 100%;
    }
    #command-line-title-row {
        height: 1;
    }
    #command-line-title {
        width: auto;
    }
    #command-line-chip {
        width: 1fr;
        text-align: right;
    }
    #command-line-popup-row {
        height: auto;
    }
    #command-line-popup {
        width: 1fr;
        height: auto;
        max-height: 9;
        border: round $primary;
        margin: 0 2;
    }
    #command-line-doc-peek {
        width: auto;
        max-width: 60;
        height: auto;
        max-height: 12;
        border: round $primary;
        padding: 0 1;
        margin: 0 2 0 0;
    }
    #command-line-popup-footer {
        height: 1;
        padding: 0 3;
    }
    #command-line-input-row {
        height: 3;
    }
    #command-line-prefix {
        width: auto;
        padding-top: 1;
    }
    #command-line-input {
        width: 1fr;
        height: 3;
    }
    #command-line-hint-row {
        height: 1;
    }
    #command-line-status-row {
        height: 1;
    }
    #command-line-keys {
        width: auto;
    }
    #command-line-running {
        width: 1fr;
        text-align: right;
    }
    """

    def __init__(
        self, *args: Any, keymaps: CommandLineKeymaps | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        seed = keymaps or CommandLineKeymaps(**load_builtin_command_line_defaults())
        self._bindings = BindingsMap(build_command_line_bindings(seed))
        self._history = CommandLineHistory()
        self._working_context: CommandLineContext | None = None
        self._walk_anchor: str | None = None
        self._history_walk_line: str | None = None
        self._applying_history = False
        self._tail_tokens: dict[str, str] = {}
        self._resolve_context: LineContext | None = None
        self._resolved_line: str | None = None
        self._popup_state = CompletionPopupState()
        self._provider_cache = ProviderCache()
        self._provider_task: asyncio.Task[None] | None = None
        self._provider_note: str | None = None
        self._help_cache: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
        self._history_search_active = False
        self._empty_state_active = False
        self._last_completion_kind = ""

    @property
    def session(self) -> CommandLineSession:
        """Return the app-held session backing this screen."""
        return command_line_session_for(self.app)

    def compose(self) -> ComposeResult:
        """Compose the frame: title, transcript, input, hint, status."""
        with Vertical(id="command-line-frame"):
            with Horizontal(id="command-line-title-row"):
                yield Static(
                    Text("❯ Command Line", style="bold #FFD700"),
                    id="command-line-title",
                )
                yield Static("", id="command-line-chip")
            yield CommandLineTranscript(id="command-line-transcript")
            with Horizontal(id="command-line-popup-row"):
                popup = CommandLinePopup()
                popup.display = False
                yield popup
                peek = Static("", id="command-line-doc-peek")
                peek.display = False
                yield peek
            footer = Static("", id="command-line-popup-footer")
            footer.display = False
            yield footer
            with Horizontal(id="command-line-input-row"):
                yield Static(
                    Text(COMMAND_LINE_PREFIX, style="dim"), id="command-line-prefix"
                )
                yield CommandLineInput()
            yield Static(COMMAND_LINE_IDLE_HINT, id="command-line-hint-row")
            with Horizontal(id="command-line-status-row"):
                yield Static(COMMAND_LINE_INPUT_HINTS, id="command-line-keys")
                yield Static("0 running", id="command-line-running")

    async def on_mount(self) -> None:
        """Restore session state, resolve context, and start tailing."""
        self._bindings = BindingsMap(
            build_command_line_bindings(command_line_keymaps_for(self))
        )
        try:
            self.refresh_bindings()
        except Exception:  # noqa: BLE001 - binding refresh is best effort.
            pass
        session = self.session
        frame = self.query_one("#command-line-frame", Vertical)
        if session.full_height:
            frame.add_class("full-height")
        restored_input = self.query_one(CommandLineInput)
        restored_input.set_line(session.draft)
        try:
            restored_input.move_cursor((0, session.draft_cursor))
        except Exception:  # noqa: BLE001 - cursor restore is best effort.
            pass
        pending_focus = session.focus_block_proc_id
        session.focus_block_proc_id = None
        if not session.restored:
            session.restored = True
            run_worker = getattr(self.app, "run_worker", None)
            if callable(run_worker):
                run_worker(self._restore_worker(pending_focus), exclusive=False)
            elif pending_focus is not None:
                self._focus_proc_block(pending_focus)
        elif pending_focus is not None:
            if not self._focus_proc_block(pending_focus):
                run_worker = getattr(self.app, "run_worker", None)
                if callable(run_worker):
                    run_worker(
                        self._ensure_focus_worker(pending_focus), exclusive=False
                    )
        self._refresh_transcript()
        self._update_running()
        self._update_hints()
        restored_input.focus()
        self._history.refresh()
        context = await asyncio.to_thread(resolve_working_context, self.app, session)
        self._working_context = context
        self._update_chip()
        self._update_ghost()
        self.transcript.start_tail_task()
        ensure_command_line_grammar_loaded(
            self.app, on_ready=self._on_grammar_ready_from_worker
        )
        self._refresh_completion()
        self._maybe_show_palette_moved_tip()

    def _maybe_show_palette_moved_tip(self) -> None:
        """Show the one-time ``:``/``;`` flip tip in the hint row."""
        from sase.ace.tui.command_line.palette_moved_tip import (
            COMMAND_LINE_PALETTE_MOVED_TIP,
            has_shown_palette_moved_tip,
            mark_palette_moved_tip_shown,
        )

        try:
            if has_shown_palette_moved_tip():
                return
        except Exception:  # noqa: BLE001 - tip reads always degrade.
            return
        try:
            self.query_one("#command-line-hint-row", Static).update(
                COMMAND_LINE_PALETTE_MOVED_TIP
            )
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        try:
            mark_palette_moved_tip_shown()
        except Exception:  # noqa: BLE001 - marker writes are best effort.
            pass

    def _on_grammar_ready_from_worker(self) -> None:
        """Refresh after the loop-owned grammar loader has completed."""
        self._refresh_completion_after_grammar()

    def _refresh_completion_after_grammar(self) -> None:
        """Refresh the popup once the grammar handle lands (UI thread)."""
        try:
            self._refresh_completion()
        except Exception:  # noqa: BLE001 - refresh is best effort.
            pass

    async def _restore_worker(self, pending_focus: str | None) -> None:
        """Rebuild the transcript from the proc store once per app session."""
        app = self.app
        session = self.session
        try:
            rows = await asyncio.to_thread(read_command_line_store_rows)
        except Exception:  # noqa: BLE001 - restore is best effort.
            rows = []
        try:
            restore_missing_blocks(session, rows)
            refresh_pruned_flags(session, {row.proc_id for row in rows})
            observer = getattr(app, "_proc_observer", None)
            for block in session.blocks:
                if block.running and block.proc_id is not None and observer is not None:
                    try:
                        observer.register_exit_watch(block.proc_id)
                    except Exception:  # noqa: BLE001 - watches are best effort.
                        pass
            if pending_focus is not None:
                self._focus_proc_block(pending_focus)
                if session.block_for_proc(pending_focus) is None:
                    for row in rows:
                        if row.proc_id == pending_focus:
                            rebuilt = block_from_proc(row)
                            if rebuilt is not None:
                                session.blocks.append(rebuilt)
                                self._focus_proc_block(pending_focus)
                            break
        except Exception:  # noqa: BLE001 - restore never breaks the panel.
            pass
        self._refresh_transcript()
        self._update_running()
        self._update_hints()

    async def _ensure_focus_worker(self, proc_id: str) -> None:
        """Add a store-backed block for a Procs jump, then select it."""
        session = self.session
        try:
            await asyncio.to_thread(ensure_block_for_proc, session, proc_id)
        except Exception:  # noqa: BLE001 - focus is best effort.
            pass
        if session.block_for_proc(proc_id) is None:
            try:
                self.notify("Proc record pruned", severity="warning")
            except Exception:  # noqa: BLE001 - notify is best effort.
                pass
            return
        self._focus_proc_block(proc_id)
        self._refresh_transcript()
        self._update_hints()

    def _focus_proc_block(self, proc_id: str) -> bool:
        """Select the block tracking *proc_id*; False when it is missing."""
        session = self.session
        block = session.block_for_proc(proc_id)
        if block is None:
            return False
        session.select_block(block.block_id)
        self._ensure_block_tail(block)
        return True

    def _ensure_block_tail(self, block: CommandLineBlock) -> None:
        """Lazily load a viewed block's tail in a worker (repaints after)."""
        if block.tail_loaded or block.proc_id is None:
            return
        run_worker = getattr(self.app, "run_worker", None)
        if not callable(run_worker):
            return
        run_worker(self._load_tail_worker(block.block_id), exclusive=False)

    async def _load_tail_worker(self, block_id: str) -> None:
        """Read one block's lazy tail off-thread, then repaint."""
        block = self.session.block_by_id(block_id)
        if block is None:
            return
        try:
            await asyncio.to_thread(load_block_tail_text, block)
        except Exception:  # noqa: BLE001 - lazy tails are best effort.
            return
        self._refresh_transcript()

    async def on_unmount(self) -> None:
        """Persist the draft and stop tail polling."""
        self._store_draft()
        task, self._provider_task = self._provider_task, None
        if task is not None:
            task.cancel()
        try:
            self.transcript.stop_tail_task()
        except Exception:  # noqa: BLE001 - teardown is best effort.
            pass
        observer = getattr(self.app, "_proc_observer", None)
        unsubscribe = getattr(observer, "unsubscribe_tail", None)
        for token in self._tail_tokens.values():
            try:
                if callable(unsubscribe):
                    unsubscribe(token)
            except Exception:  # noqa: BLE001 - teardown is best effort.
                pass
        self._tail_tokens.clear()


__all__ = [
    "COMMAND_LINE_BLOCK_HINTS",
    "COMMAND_LINE_IDLE_HINT",
    "COMMAND_LINE_INDEXING_HINT",
    "COMMAND_LINE_INPUT_HINTS",
    "COMMAND_LINE_MENU_HINTS",
    "COMMAND_LINE_PREFIX",
    "COMMAND_LINE_SEARCH_HINT",
    "CommandLineScreen",
]
