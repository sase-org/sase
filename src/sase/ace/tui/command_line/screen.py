"""Bottom-anchored Command Line panel screen (beta flag ``ace_command_line``).

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
from textual.binding import Binding
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
from sase.ace.tui.command_line.input import COMMAND_LINE_PREFIX, CommandLineInput
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

#: Idle hint shown in the signature row before the resolver lands.
COMMAND_LINE_IDLE_HINT = "type to search · ⇥ complete · ; Command Palette"
#: Bottom-border key hints for the input state.
COMMAND_LINE_INPUT_HINTS = "⏎ run · ⇥ complete · ↑↓ history · ^R search · esc hide"
#: Bottom-border key hints while the completion menu is active.
COMMAND_LINE_MENU_HINTS = "⏎ accept · ↑↓ move · esc normal"
#: Signature-row text while the grammar loader worker is still in flight.
COMMAND_LINE_INDEXING_HINT = "indexing commands…"
#: Hint row while ``ctrl+r`` history search is active.
COMMAND_LINE_SEARCH_HINT = "history search · ⏎ load · esc exit"
#: Bottom-border key hints while a transcript block is selected (NORMAL mode).
COMMAND_LINE_BLOCK_HINTS = (
    "j/k move · o expand · v pager · K kill · r rerun · e edit · "
    "y copy · p Procs · x remove · i input · esc hide"
)


class CommandLineScreen(ModalScreen[None]):
    """Bottom-anchored ``:`` Command Line drawer."""

    BINDINGS = [
        Binding("ctrl+t", "toggle_full_height", "Full height", show=False),
        Binding("ctrl+l", "clear_transcript", "Clear", show=False),
        Binding("escape", "hide_panel", "Hide", show=False),
        Binding("j", "block_next", "Next block", show=False),
        Binding("k", "block_prev", "Previous block", show=False),
        Binding("up", "block_prev", "Previous block", show=False),
        Binding("down", "block_next", "Next block", show=False),
        Binding("g", "block_first", "First block", show=False),
        Binding("G", "block_last", "Last block", show=False),
        Binding("shift+g", "block_last", "Last block", show=False),
        Binding("o", "block_toggle_expand", "Expand", show=False),
        Binding("enter", "block_toggle_expand", "Expand", show=False),
        Binding("v", "block_pager", "Pager", show=False),
        Binding("K", "block_kill", "Kill", show=False),
        Binding("shift+k", "block_kill", "Kill", show=False),
        Binding("r", "block_rerun", "Rerun", show=False),
        Binding("R", "block_rerun_confirm", "Rerun with -y", show=False),
        Binding("shift+r", "block_rerun_confirm", "Rerun with -y", show=False),
        Binding("e", "block_edit", "Edit", show=False),
        Binding("y", "block_copy_output", "Copy output", show=False),
        Binding("Y", "block_copy_command", "Copy command", show=False),
        Binding("shift+y", "block_copy_command", "Copy command", show=False),
        Binding("p", "block_procs", "Procs", show=False),
        Binding("x", "block_remove", "Remove", show=False),
        Binding("i", "block_focus_input", "Input", show=False),
        Binding("a", "block_focus_input", "Input", show=False),
        Binding("colon", "block_focus_input", "Input", show=False),
    ]

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

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._history = CommandLineHistory()
        self._working_context: CommandLineContext | None = None
        self._walk_anchor: str | None = None
        self._applying_history = False
        self._tail_tokens: dict[str, str] = {}
        self._resolve_context: dict[str, Any] | None = None
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

    def _on_grammar_ready_from_worker(self) -> None:
        """Hop the loader-thread ready signal back to the UI thread."""
        call = getattr(self.app, "call_from_thread", None)
        if callable(call):
            call(self._refresh_completion_after_grammar)

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

    @property
    def transcript(self) -> CommandLineTranscript:
        """Return the transcript widget."""
        return self.query_one(CommandLineTranscript)

    def _store_draft(self) -> None:
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen has no draft.
            return
        session = self.session
        session.draft = widget.text
        try:
            session.draft_cursor = widget.cursor_location[1]
        except Exception:  # noqa: BLE001 - cursor read is best effort.
            pass

    def on_text_area_changed(self, event: Any) -> None:
        """Strip a typed ``sase `` prefix, then refresh draft and ghost text."""
        from textual.widgets import TextArea

        if not isinstance(event, TextArea.Changed):
            return
        widget = event.text_area
        if not isinstance(widget, CommandLineInput):
            return
        text = widget.text
        if text == "sase" or text.startswith("sase "):
            stripped = text[4:].lstrip() if text != "sase" else ""
            try:
                cursor = widget.cursor_location[1]
            except Exception:  # noqa: BLE001 - cursor read is best effort.
                cursor = len(text)
            widget.text = stripped
            try:
                widget.move_cursor((0, max(0, cursor - (len(text) - len(stripped)))))
            except Exception:  # noqa: BLE001 - cursor restore is best effort.
                pass
            return
        if not self._applying_history:
            self._walk_anchor = None
        self._store_draft()
        self._update_ghost()
        self._refresh_completion()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Run the input line when Enter is pressed."""
        if not isinstance(event.control, CommandLineInput):
            return
        self.submit_current_line()

    def submit_current_line(self) -> None:
        """Validate and submit the input line (double-Enter guarded)."""
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot submit.
            return
        self._submit_line(widget.normalized_text())

    def _submit_line(
        self, line: str, *, bypass_dedup: bool = False, select: bool = False
    ) -> bool:
        """Submit *line* as a new block; deliberate reruns bypass the guard."""
        session = self.session
        prepared: PreparedSubmit | None
        if bypass_dedup:
            tokens = tokenize_command_line(line)
            if tokens is None:
                return False
            prepared = PreparedSubmit(tokens=tokens, line=line.strip())
            session.last_submit_line = line.strip()
            try:
                import time as _time

                session.last_submit_at = _time.monotonic()
            except Exception:  # noqa: BLE001 - guard bookkeeping is best effort.
                pass
        else:
            prepared = prepare_submit(session, line, tokens=self._submit_tokens())
        if prepared is None:
            return False
        context = self._submit_context_for(prepared.line)
        local = self._submit_local(prepared, context, clear_input=not bypass_dedup)
        if local is not None:
            return local
        block = session.add_block(prepared.line)
        capture_resolve_context(block, context)
        if not bypass_dedup:
            try:
                widget = self.query_one(CommandLineInput)
            except Exception:  # noqa: BLE001 - unmounted screen cannot submit.
                widget = None
            if widget is not None:
                widget.set_line("")
            session.draft = ""
            session.draft_cursor = 0
            self._walk_anchor = None
        if select:
            session.select_block(block.block_id)
        self._refresh_transcript()
        self._update_running()
        self._update_hints()
        run_worker = getattr(self.app, "run_worker", None)
        if not callable(run_worker):
            apply_submit_failure(block, "worker unavailable")
            self._refresh_transcript()
            return False
        run_worker(
            self._submit_worker(
                block=block,
                tokens=prepared.tokens,
                line=prepared.line,
            ),
            exclusive=False,
        )
        return True

    def _submit_context_for(self, line: str) -> dict[str, Any] | None:
        """Return the resolver context for *line* (cached when still fresh)."""
        if self._resolve_context is not None and self._resolved_line == line:
            return self._resolve_context
        try:
            resolved = resolve_command_line(self.app, line, len(line))
        except Exception:  # noqa: BLE001 - advisory path never raises.
            return None
        return cast("dict[str, Any] | None", resolved)

    def _submit_local(
        self,
        prepared: PreparedSubmit,
        context: dict[str, Any] | None,
        *,
        clear_input: bool,
    ) -> bool | None:
        """Handle built-in, deny, and foreground submits; None means proc path."""
        name = builtin_name_for(prepared.tokens)
        if name is not None:
            self._run_builtin(prepared, name, clear_input=clear_input)
            return True
        route = submit_route_for(context)
        if route == "proc":
            return None
        if route == "deny":
            self._add_local_block(
                prepared.line,
                status="denied",
                text=deny_note_for(context),
                exit_code=None,
                clear_input=clear_input,
                record_history=False,
            )
            return True
        return self._run_foreground(prepared, clear_input=clear_input)

    def _local_working_context(self) -> CommandLineContext:
        """Return the cached working context, or a cheap launch-cwd fallback."""
        if self._working_context is not None:
            return self._working_context
        try:
            cwd = resolve_launch_cwd(self.app)
        except Exception:  # noqa: BLE001 - context reads always degrade.
            cwd = ""
        return CommandLineContext(cwd=cwd, project=None)

    def _add_local_block(
        self,
        line: str,
        *,
        status: str,
        text: str,
        exit_code: int | None,
        clear_input: bool,
        record_history: bool,
    ) -> CommandLineBlock:
        """Create a finished non-proc block (denied, foreground, built-in)."""
        session = self.session
        working = self._local_working_context()
        block = session.add_block(line)
        apply_local_block(block, status=status, text=text, exit_code=exit_code)
        if clear_input:
            try:
                widget = self.query_one(CommandLineInput)
            except Exception:  # noqa: BLE001 - unmounted screen cannot submit.
                widget = None
            if widget is not None:
                widget.set_line("")
            session.draft = ""
            session.draft_cursor = 0
            self._walk_anchor = None
        self._refresh_transcript()
        self._update_running()
        self._update_hints()
        if record_history:
            self._record_local_history(
                line,
                cwd=working.cwd,
                project=working.project,
                exit_code=exit_code,
            )
        return block

    def _run_foreground(self, prepared: PreparedSubmit, *, clear_input: bool) -> bool:
        """Suspend the TUI and run a foreground-policy command in the terminal."""
        working = self._local_working_context()
        try:
            exit_code = run_in_terminal(
                self.app, ["sase", *prepared.tokens], cwd=working.cwd
            )
        except OSError as error:
            session = self.session
            block = session.add_block(prepared.line)
            apply_submit_failure(block, str(error) or type(error).__name__)
            try:
                widget = self.query_one(CommandLineInput)
                widget.set_line(prepared.line)
            except Exception:  # noqa: BLE001 - teardown races degrade silently.
                pass
            self._refresh_transcript()
            self._update_running()
            return False
        self._add_local_block(
            prepared.line,
            status="foreground",
            text="",
            exit_code=exit_code,
            clear_input=clear_input,
            record_history=True,
        )
        return True

    def _run_builtin(
        self, prepared: PreparedSubmit, name: str, *, clear_input: bool
    ) -> None:
        """Run a first-token built-in instantly with no proc."""
        session = self.session
        working = self._local_working_context()
        args = prepared.tokens[1:]
        if name == "cd":
            outcome = run_cd(session, args[0] if args else None, cwd=working.cwd or "")
            self._refresh_working_context(pinned=session.cwd_pin)
        elif name == "clear":
            outcome = run_clear(session)
        elif name == "help":
            outcome = self._builtin_help(args)
        else:
            outcome = render_history(self._history.entries, args[0] if args else None)
        self._add_local_block(
            prepared.line,
            status="builtin",
            text=outcome.text,
            exit_code=outcome.exit_code,
            clear_input=clear_input,
            record_history=True,
        )

    def _builtin_help(self, args: list[str]) -> BuiltinOutcome:
        """Render ``help [command…]`` from ``command_help``."""
        from sase.ace.tui.command_line.grammar import command_line_grammar_for

        handle = command_line_grammar_for(self.app)
        if handle is None:
            return BuiltinOutcome("command index still loading…")
        try:
            view = handle.command_help(list(args))
        except Exception:  # noqa: BLE001 - help lookup is best effort.
            view = None
        return render_help(view, list(args))

    def _refresh_working_context(self, *, pinned: str | None) -> None:
        """Update the chip optimistically after ``cd``, then re-resolve."""
        if pinned:
            self._working_context = CommandLineContext(
                cwd=pinned, project=None, pinned=True
            )
            self._update_chip()
            self._update_ghost()
            return
        run_worker = getattr(self.app, "run_worker", None)
        if not callable(run_worker):
            return

        async def _resolve() -> None:
            try:
                context = await asyncio.to_thread(
                    resolve_working_context, self.app, self.session
                )
            except Exception:  # noqa: BLE001 - context display always degrades.
                return
            self._working_context = context
            self._update_chip()
            self._update_ghost()

        run_worker(_resolve(), exclusive=False)

    def _record_local_history(
        self,
        line: str,
        *,
        cwd: str,
        project: str | None,
        exit_code: int | None,
    ) -> None:
        """Record a non-proc submission off-thread (deny records nothing)."""
        run_worker = getattr(self.app, "run_worker", None)
        if not callable(run_worker):
            return

        async def _record() -> None:
            try:
                await asyncio.to_thread(
                    self._history.record,
                    line,
                    cwd=cwd,
                    project=project,
                    exit_code=exit_code,
                )
            except Exception:  # noqa: BLE001 - history is best effort.
                pass

        try:
            run_worker(_record(), exclusive=False)
        except Exception:  # noqa: BLE001 - history is best effort.
            pass

    async def _submit_worker(
        self, *, block: CommandLineBlock, tokens: list[str], line: str
    ) -> None:
        """Submit tokens as a tagged proc, then attach watches to the block."""
        app = self.app
        session = self.session
        context = self._working_context
        if context is None:
            context = await asyncio.to_thread(resolve_working_context, app, session)
        self._working_context = context
        try:
            width = max(40, int(self.transcript.size.width or 120) - 4)
        except Exception:  # noqa: BLE001 - size read is best effort.
            width = 120
        observer = getattr(app, "_proc_observer", None)
        placeholder_id: str | None = None
        if observer is not None:
            try:
                placeholder = observer.register_pending(
                    proc_type="command",
                    cl_name="",
                    project_file="",
                    display_name=f": {line}",
                    command=["sase", *tokens],
                )
                placeholder_id = placeholder.proc_id
                block.placeholder_id = placeholder_id
            except Exception:  # noqa: BLE001 - placeholder is best effort.
                placeholder_id = None
        try:
            proc = await asyncio.to_thread(
                submit_in_worker,
                tokens=tokens,
                cwd=context.cwd,
                project=context.project,
                width=width,
                session_id=getattr(app, "_proc_session_id", None),
            )
        except Exception as error:  # noqa: BLE001 - submit errors become blocks.
            apply_submit_failure(block, str(error) or type(error).__name__)
            if observer is not None and placeholder_id is not None:
                try:
                    observer.remove_pending(placeholder_id)
                except Exception:  # noqa: BLE001 - cleanup is best effort.
                    pass
            try:
                widget = self.query_one(CommandLineInput)
                widget.set_line(line)
            except Exception:  # noqa: BLE001 - teardown races degrade silently.
                pass
            self._refresh_transcript()
            self._update_running()
            return
        apply_submit_success(block, proc, placeholder_id=placeholder_id)
        if observer is not None:
            try:
                observer.register_exit_watch(
                    proc.proc_id, placeholder_id=placeholder_id
                )
            except Exception:  # noqa: BLE001 - exit watch is best effort.
                pass
            subscribe = getattr(observer, "subscribe_tail", None)
            if callable(subscribe):
                try:
                    self._tail_tokens[block.block_id] = subscribe(proc.proc_id)
                except Exception:  # noqa: BLE001 - tail sub is best effort.
                    pass
        self._refresh_transcript()
        self._update_running()

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
            await asyncio.to_thread(load_block_tail_text, block)
        except Exception:  # noqa: BLE001 - lazy tails are best effort.
            pass
        self._refresh_transcript()
        self.app.call_from_thread(self._push_block_pager, block)

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

    def _refresh_completion(self) -> None:
        """Resolve the line synchronously and repaint popup and signature.

        The keystroke path is synchronous and in memory: the frozen
        grammar handle, in-memory entity sources, and Rust ranking. It
        never spawns a process, never calls ``resolve_ref``, and never
        takes a lock. Provider fetches fan out to a debounced worker.
        """
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen has no popup.
            return
        line = widget.text
        try:
            cursor = widget.cursor_location[1]
        except Exception:  # noqa: BLE001 - cursor read is best effort.
            cursor = len(line)
        started = time.perf_counter()
        if self._history_search_active:
            self._render_history_search(line)
            self._record_keystroke_probe(time.perf_counter() - started, True)
            return
        if not line.strip():
            self._render_empty_state(line)
            self._record_keystroke_probe(time.perf_counter() - started, True)
            return
        self._empty_state_active = False
        context = resolve_command_line(self.app, line, cursor)
        self._resolve_context = context
        self._resolved_line = line
        widget.set_resolve_context(context)
        if context is None:
            self._show_indexing(bool(line.strip()))
            self._record_keystroke_probe(time.perf_counter() - started, False)
            return
        completion = self._complete_line(line, cursor, context)
        completion = self._maybe_prepend_marked_row(context, completion)
        self._last_completion_kind = str(completion.get("kind", "") or "")
        slot = context.get("slot") or {}
        self._popup_state.reset(
            completion.get("items", []),
            typed_text=line,
            replace_start=int(slot.get("replace_start", cursor)),
            replace_end=int(slot.get("replace_end", cursor)),
        )
        self._render_popup(completion)
        self._render_signature()
        self._maybe_fetch_providers(line, cursor, context)
        self._record_keystroke_probe(time.perf_counter() - started, True)

    def _complete_line(
        self, line: str, cursor: int, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Rank candidates for the cursor slot through the Rust handle."""
        handle = command_line_grammar_for(self.app)
        if handle is None:
            return {
                "items": [],
                "total": 0,
                "kind": "",
                "replace_start": cursor,
                "replace_end": cursor,
            }
        slot = context.get("slot") or {}
        value_kind = str(slot.get("value_kind") or "")
        project = self._working_context.project if self._working_context else None
        dynamic = collect_dynamic_candidates(
            self.app, value_kind, project, self._provider_cache
        )
        try:
            return handle.complete(
                line,
                cursor,
                dynamic=dynamic,
                selected=selected_entity_values(self.app),
                limit=100,
            )
        except Exception:  # noqa: BLE001 - advisory path never raises.
            return {
                "items": [],
                "total": 0,
                "kind": "",
                "replace_start": cursor,
                "replace_end": cursor,
            }

    def _maybe_fetch_providers(
        self, line: str, cursor: int, context: dict[str, Any]
    ) -> None:
        """Schedule a debounced provider fetch for the active slot, if any."""
        slot = context.get("slot") or {}
        value_kind = str(slot.get("value_kind") or "")
        if not needs_provider_fetch(value_kind):
            return
        project = self._working_context.project if self._working_context else None
        if self._provider_cache.cached(value_kind, project) is not None:
            return
        generation = self._provider_cache.next_generation()
        old_task, self._provider_task = self._provider_task, None
        if old_task is not None:
            old_task.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # No loop: providers stay quiet, popup keeps statics.
            return
        self._provider_task = loop.create_task(
            self._provider_fetch_task(generation, value_kind, project, line, cursor)
        )

    async def _provider_fetch_task(
        self,
        generation: int,
        value_kind: str,
        project: str | None,
        line: str,
        cursor: int,
    ) -> None:
        """Fetch provider candidates, dropping stale lines (last wins)."""
        from sase.completion.candidates.providers import candidates_for

        await asyncio.sleep(PROVIDER_DEBOUNCE_SECONDS)
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - teardown races degrade silently.
            return
        if widget.text != line:
            return
        try:
            current_cursor = widget.cursor_location[1]
        except Exception:  # noqa: BLE001 - cursor read is best effort.
            current_cursor = len(widget.text)
        if current_cursor != cursor:
            return
        if not self._provider_cache.is_current(generation):
            return
        try:
            fetched = await asyncio.to_thread(
                candidates_for, value_kind, "", project=project, limit=2000
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - provider failure is advisory.
            self._provider_cache.note_unavailable(value_kind, project)
            self._provider_note = provider_unavailable_note(value_kind)
            self._render_popup(self._last_completion())
            return
        if not fetched:
            self._provider_cache.note_unavailable(value_kind, project)
            self._provider_note = provider_unavailable_note(value_kind)
            self._render_popup(self._last_completion())
            return
        items = [
            {
                "value": candidate.value,
                "description": candidate.description,
                "source": "provider",
            }
            for candidate in fetched
        ]
        if not self._provider_cache.commit(generation, value_kind, project, items):
            return  # A newer keystroke already won; drop this result.
        self._provider_note = None
        try:
            widget_now = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - teardown races degrade silently.
            return
        if widget_now.text != line:
            return
        self._refresh_completion()

    def _last_completion(self) -> dict[str, Any]:
        """Rebuild the last completion view from the popup state."""
        slot: dict[str, Any] = {}
        if self._resolve_context is not None:
            slot = self._resolve_context.get("slot") or {}
        return {
            "items": self._popup_state.items,
            "total": len(self._popup_state.items),
            "kind": str(slot.get("value_kind") or ""),
            "replace_start": self._popup_state.replace_start,
            "replace_end": self._popup_state.replace_end,
        }

    # -- completion extras (empty state, history search, doc peek) -------------

    def _help_lookup(self, path: list[str]) -> dict[str, Any] | None:
        """Return the grammar's help view for *path*, or ``None``."""
        handle = command_line_grammar_for(self.app)
        if handle is None:
            return None
        try:
            return handle.command_help(list(path))
        except Exception:  # noqa: BLE001 - help lookup is best effort.
            return None

    def _render_empty_state(self, line: str) -> None:
        """Show RECENT + derived FOR rows while the input line is empty."""
        self._empty_state_active = True
        self._resolve_context = None
        try:
            widget = self.query_one(CommandLineInput)
            widget.set_resolve_context(None)
        except Exception:  # noqa: BLE001 - unmounted screen has no overlay.
            pass
        try:
            selected = selected_entity_values(self.app)
        except Exception:  # noqa: BLE001 - selection is best effort.
            selected = []
        try:
            kind = selected_entity_kind(self.app)
        except Exception:  # noqa: BLE001 - selection is best effort.
            kind = None
        try:
            rows = empty_state_rows(
                self._help_lookup,
                self._history.entries,
                selected_kind=kind,
                selected_value=selected[0] if selected else None,
            )
        except Exception:  # noqa: BLE001 - empty state never breaks open.
            rows = []
        items = [row.to_item() for row in rows]
        self._popup_state.reset(
            items, typed_text=line, replace_start=0, replace_end=len(line)
        )
        self._render_popup(
            {
                "items": items,
                "total": len(items),
                "kind": "recent",
                "replace_start": 0,
                "replace_end": len(line),
            }
        )
        try:
            handle = command_line_grammar_for(self.app)
            count: int | None = len(handle) if handle is not None else None
        except Exception:  # noqa: BLE001 - count is best effort.
            count = None
        try:
            hint_row = self.query_one("#command-line-hint-row", Static)
            hint_row.update(empty_state_hint(count))
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            pass
        self._hide_doc_peek()

    def toggle_history_search(self) -> None:
        """Enter or leave ``ctrl+r`` fuzzy history search."""
        self._history_search_active = not self._history_search_active
        self._refresh_completion()

    def _render_history_search(self, line: str) -> None:
        """Rank history against the typed query with the Rust fuzzy matcher."""
        self._empty_state_active = False
        self._resolve_context = None
        try:
            widget = self.query_one(CommandLineInput)
            widget.set_resolve_context(None)
        except Exception:  # noqa: BLE001 - unmounted screen has no overlay.
            pass
        try:
            ranked = rank_history_entries(line, self._history.entries)
        except Exception:  # noqa: BLE001 - search never breaks typing.
            ranked = []
        items = [
            {
                "insert_text": item.line,
                "display": item.line,
                "description": "history",
                "badge": "history",
                "source": "history",
                "match_runs": item.match_runs,
                "selected": False,
            }
            for item in ranked
        ]
        self._popup_state.reset(
            items, typed_text=line, replace_start=0, replace_end=len(line)
        )
        self._render_popup(
            {
                "items": items,
                "total": len(items),
                "kind": "history",
                "replace_start": 0,
                "replace_end": len(line),
            }
        )
        try:
            hint_row = self.query_one("#command-line-hint-row", Static)
            hint_row.update(COMMAND_LINE_SEARCH_HINT)
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            pass
        self._hide_doc_peek()

    def _accept_stored_row(self) -> bool:
        """Insert the highlighted empty-state/search row; never runs it."""
        state = self._popup_state
        item = state.highlighted
        if item is None and self._history_search_active and state.items:
            item = state.items[0]
        if item is None:
            if self._history_search_active:
                self._history_search_active = False
                self._refresh_completion()
                return True
            return False
        self._history_search_active = False
        self._apply_popup_insert(str(item.get("insert_text", "")))
        return True

    def _maybe_prepend_marked_row(
        self, context: Any, completion: dict[str, Any]
    ) -> dict[str, Any]:
        """Prepend a ``‹N marked›`` row for variadic slots with TUI marks."""
        slot = context.get("slot") or {}
        value_kind = str(slot.get("value_kind") or "")
        if not value_kind:
            return completion
        try:
            path = [str(part) for part in context.get("path", [])]
            if not slot_is_variadic(slot, self._help_lookup, path):
                return completion
            values = marked_values_for_kind(self.app, value_kind)
        except Exception:  # noqa: BLE001 - marked rows are best effort.
            return completion
        insert = marked_insert_text(values)
        if not insert:
            return completion
        row = {
            "insert_text": insert,
            "display": f"‹{len(values)} marked›",
            "description": "insert all marked",
            "badge": value_kind,
            "source": "tui",
            "match_runs": [],
            "selected": False,
        }
        items = [row, *completion.get("items", [])]
        total = int(completion.get("total", len(items) - 1) or 0) + 1
        return {**completion, "items": items, "total": total}

    def _hide_doc_peek(self) -> None:
        """Hide the right-hand doc-peek card."""
        try:
            peek = self.query_one("#command-line-doc-peek", Static)
            peek.display = False
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            pass

    def _render_doc_peek(self) -> None:
        """Show the doc-peek card for a highlighted subcommand or option."""
        try:
            peek = self.query_one("#command-line-doc-peek", Static)
            width = self.size.width
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        if not doc_peek_visible(width):
            peek.display = False
            return
        highlighted = self._popup_state.highlighted
        if highlighted is None:
            peek.display = False
            return
        path: list[str] = []
        if self._resolve_context is not None:
            path = [str(part) for part in self._resolve_context.get("path", [])]
        try:
            card = doc_peek_for_highlight(
                completion_kind=self._last_completion_kind,
                highlighted=highlighted,
                path=path,
                help_lookup=self._help_lookup,
            )
        except Exception:  # noqa: BLE001 - the peek never breaks typing.
            card = ""
        if not card:
            peek.display = False
            return
        peek.update(card)
        peek.display = True

    def _render_popup(self, completion: dict[str, Any]) -> None:
        """Show or hide the floating popup and its footer."""
        try:
            popup = self.query_one(CommandLinePopup)
            footer = self.query_one("#command-line-popup-footer", Static)
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        items = completion.get("items", [])
        try:
            line = self.query_one(CommandLineInput).text
        except Exception:  # noqa: BLE001 - fall back to showing rows.
            line = "x"
        stored_rows = self._empty_state_active or self._history_search_active
        if not items or (not line.strip() and not stored_rows):
            popup.display = False
            footer.display = False
            self._update_keys_hint()
            return
        popup.display = True
        popup.show_items(items)
        kind = str(completion.get("kind", "") or "commands")
        total = int(completion.get("total", len(items)) or len(items))
        footer_text = popup_footer(kind, min(len(items), total), total)
        if self._provider_note:
            footer_text += f"  {self._provider_note}"
        else:
            footer_text += "  ⇥ complete"
        footer.update(footer_text)
        footer.display = True
        self._update_keys_hint()

    def _render_signature(self) -> None:
        """Repaint the signature/hint row from the resolver context."""
        try:
            hint_row = self.query_one("#command-line-hint-row", Static)
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        if self._resolve_context is None:
            if is_command_line_grammar_pending(self.app):
                hint_row.update(COMMAND_LINE_INDEXING_HINT)
            else:
                hint_row.update(COMMAND_LINE_IDLE_HINT)
            return
        hint_row.update(
            signature_hint_line(
                self._resolve_context,
                highlighted_option=self._highlighted_help_option(),
            )
        )
        self._render_doc_peek()

    def _show_indexing(self, has_text: bool) -> None:
        """Show the pre-grammar state: history still works, popup waits."""
        try:
            popup = self.query_one(CommandLinePopup)
            footer = self.query_one("#command-line-popup-footer", Static)
            hint_row = self.query_one("#command-line-hint-row", Static)
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        popup.display = False
        if has_text and is_command_line_grammar_pending(self.app):
            footer.update(COMMAND_LINE_INDEXING_HINT)
            footer.display = True
        else:
            footer.display = False
        if is_command_line_grammar_pending(self.app):
            hint_row.update(COMMAND_LINE_INDEXING_HINT)
        else:
            hint_row.update(COMMAND_LINE_IDLE_HINT)
        self._update_keys_hint()

    def _highlighted_help_option(self) -> dict[str, Any] | None:
        """Return the help record for the menu-highlighted option, if any."""
        highlighted = self._popup_state.highlighted
        if highlighted is None or self._resolve_context is None:
            return None
        insert = str(highlighted.get("insert_text", "") or "")
        token = insert.strip()
        if not token.startswith("-"):
            return None
        path = tuple(str(part) for part in self._resolve_context.get("path", []))
        cache_key = (path, token)
        if cache_key in self._help_cache:
            return self._help_cache[cache_key]
        handle = command_line_grammar_for(self.app)
        if handle is None:
            return None
        try:
            help_view = handle.command_help(list(path))
        except Exception:  # noqa: BLE001 - help lookup is best effort.
            return None
        if not help_view:
            return None
        for option in help_view.get("options", []):
            strings = [str(item) for item in option.get("strings", [])]
            if token in strings or token.rstrip("=") in [
                item.rstrip("=") for item in strings
            ]:
                self._help_cache[cache_key] = option
                return option
        return None

    def _submit_tokens(self) -> list[str] | None:
        """Return the resolver's argv for the current line, if still fresh."""
        if self._resolve_context is None or self._resolved_line is None:
            return None
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot submit.
            return None
        if widget.text != self._resolved_line:
            return None
        argv = self._resolve_context.get("argv") or []
        return [str(token) for token in argv] or None

    async def command_line_handle_key(self, event: Any) -> bool:
        """Apply the zsh menu-select key rules; True when the key is consumed."""
        key = getattr(event, "key", None)
        state = self._popup_state
        decision: PopupDecision | None = None
        if key == "tab":
            decision = state.on_tab()
        elif key == "shift+tab":
            decision = state.on_shift_tab()
        elif key == "ctrl+n":
            decision = state.on_ctrl_n()
        elif key == "ctrl+p":
            decision = state.on_ctrl_p()
        elif key in ("up", "down"):
            if not state.menu_active:
                return False
            decision = state.on_ctrl_n() if key == "down" else state.on_ctrl_p()
        elif key == "enter":
            if self._empty_state_active or self._history_search_active:
                return self._accept_stored_row()
            if not state.menu_active:
                return False
            decision = state.on_enter()
        elif key == "escape":
            if self._history_search_active:
                self._history_search_active = False
                self._refresh_completion()
                return True
            if not state.menu_active:
                return False
            decision = state.on_escape()
        elif key == "ctrl+r":
            self.toggle_history_search()
            return True
        else:
            return False
        return self._apply_popup_decision(decision)

    def _apply_popup_decision(self, decision: PopupDecision) -> bool:
        """Apply a popup state-machine decision; always consumes the key."""
        action = decision.action
        if action in ("accept", "complete-prefix"):
            self._apply_popup_insert(decision.text or "")
            return True
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen cannot move.
            return True
        if action == "activate":
            popup.highlight_index(self._popup_state.index)
            self._render_signature()
            self._update_keys_hint()
            return True
        if action == "move":
            popup.highlight_index(self._popup_state.index)
            self._render_signature()
            return True
        if action == "leave-menu":
            try:
                widget = self.query_one(CommandLineInput)
                widget.set_line(decision.text or "")
            except Exception:  # noqa: BLE001 - teardown races degrade silently.
                pass
            try:
                popup.highlighted = None
            except Exception:  # noqa: BLE001 - highlight clear is best effort.
                pass
            self._render_signature()
            self._update_keys_hint()
            return True
        return False

    def _apply_popup_insert(self, insert_text: str) -> None:
        """Replace the active slot span with the accepted completion."""
        state = self._popup_state
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot insert.
            return
        line = widget.text
        start = max(0, min(state.replace_start, len(line)))
        end = max(start, min(state.replace_end, len(line)))
        widget.text = line[:start] + insert_text + line[end:]
        try:
            widget.move_cursor((0, start + len(insert_text)))
        except Exception:  # noqa: BLE001 - cursor restore is best effort.
            pass
        state.menu_active = False
        state.index = 0

    def _update_keys_hint(self) -> None:
        """Switch the bottom-border hints between input and menu sets."""
        try:
            keys = self.query_one("#command-line-keys", Static)
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            return
        if self._popup_state.menu_active:
            keys.update(COMMAND_LINE_MENU_HINTS)
        else:
            keys.update(COMMAND_LINE_INPUT_HINTS)

    def on_option_list_option_selected(self, event: Any) -> None:
        """Accept a popup row picked with the mouse while the menu is live."""
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen ignores picks.
            return
        source = getattr(event, "option_list", getattr(event, "control", None))
        if source is not popup or not self._popup_state.menu_active:
            return
        highlighted = self._popup_state.highlighted
        if highlighted is None:
            return
        try:
            event.stop()
            event.prevent_default()
        except Exception:  # noqa: BLE001 - event control is best effort.
            pass
        self._apply_popup_insert(str(highlighted.get("insert_text", "")))

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Swap the signature row to the mouse-highlighted option's summary."""
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen ignores highlights.
            return
        source = getattr(event, "option_list", getattr(event, "control", None))
        if source is not popup or popup.echo_guarded:
            return  # Rule 12: programmatic highlights never echo back.
        index = getattr(event, "option_index", None)
        if isinstance(index, int) and self._popup_state.items:
            self._popup_state.index = index % len(self._popup_state.items)
            self._render_signature()

    def _record_keystroke_probe(self, elapsed_seconds: float, indexed: bool) -> None:
        """Append a keystroke-to-popup sample when ``SASE_TUI_PERF=1``."""
        if os.environ.get("SASE_TUI_PERF") != "1":
            return
        try:
            from sase.core.paths import sase_subdir

            path = sase_subdir("perf") / "tui_command_line.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "ts": time.time(),
                            "elapsed_ms": round(elapsed_seconds * 1000, 3),
                            "indexed": indexed,
                        }
                    )
                    + "\n"
                )
        except Exception:  # noqa: BLE001 - probes never break typing.
            pass


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
