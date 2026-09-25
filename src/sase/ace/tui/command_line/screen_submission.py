"""Submission and session behavior for ``CommandLineScreen``."""

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
from sase.ace.tui.command_line.transcript import CommandLineTranscript
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
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.completion.command_line_grammar import LineContext


class CommandLineScreenSubmissionMixin:
    """Behavior mixed into the public command-line screen."""

    _walk_anchor: str | None
    _history_walk_line: str | None
    _working_context: CommandLineContext | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

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
        if self._history_walk_line == widget.text:
            # TextArea posts Changed after ``history_step`` has reset its
            # synchronous guard, so retain the prefix for this one programmatic
            # history walk. Any user edit below starts a fresh walk instead.
            self._history_walk_line = None
        elif not self._applying_history:
            self._walk_anchor = None
            self._history_walk_line = None
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

    def _submit_context_for(self, line: str) -> LineContext | None:
        """Return the resolver context for *line* (cached when still fresh)."""
        if self._resolve_context is not None and self._resolved_line == line:
            return self._resolve_context
        try:
            from sase.ace.tui.command_line import screen as screen_module

            return screen_module.resolve_command_line(self.app, line, len(line))
        except Exception:  # noqa: BLE001 - advisory path never raises.
            return None

    def _submit_local(
        self,
        prepared: PreparedSubmit,
        context: LineContext | None,
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
            from sase.ace.tui.command_line import screen as screen_module

            exit_code = screen_module.run_in_terminal(
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
            from sase.ace.tui.command_line import screen as screen_module

            proc = await asyncio.to_thread(
                screen_module.submit_in_worker,
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


__all__ = ["CommandLineScreenSubmissionMixin"]
