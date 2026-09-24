"""Bottom-anchored Command Line panel screen (beta flag ``ace_command_line``).

View-only composition over the app-held
:class:`~sase.ace.tui.command_line.session.CommandLineSession`: transcript,
input row with the implicit ``❯ sase `` prefix, and a signature/hint row.
Submission creates an optimistic block plus an observer placeholder at once,
then submits in a thread worker; failures turn the block red and restore the
line. Tailing and exit settling reuse the proc plumbing from the
proc-plumbing phase (``ProcLogCursor``, exit watches, ref-counted tails).
"""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.command_line.block_render import (
    BLOCK_SPINNER_FRAMES,  # noqa: F401 - re-exported for golden tests.
)
from sase.ace.tui.command_line.context import (
    CommandLineContext,
    resolve_working_context,
    working_context_chip,
)
from sase.ace.tui.command_line.history import CommandLineHistory
from sase.ace.tui.command_line.input import COMMAND_LINE_PREFIX, CommandLineInput
from sase.ace.tui.command_line.session import (
    CommandLineBlock,
    CommandLineSession,
    command_line_session_for,
)
from sase.ace.tui.command_line.submit import (
    apply_submit_failure,
    apply_submit_success,
    prepare_submit,
    submit_in_worker,
)
from sase.ace.tui.command_line.transcript import CommandLineTranscript
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea

#: Idle hint shown in the signature row before the resolver lands.
COMMAND_LINE_IDLE_HINT = "type to search · ⇥ complete · ; Command Palette"
#: Bottom-border key hints for the input state.
COMMAND_LINE_INPUT_HINTS = "⏎ run · ⇥ complete · ↑↓ history · ^R search · esc hide"


class CommandLineScreen(ModalScreen[None]):
    """Bottom-anchored ``:`` Command Line drawer."""

    BINDINGS = [
        Binding("ctrl+t", "toggle_full_height", "Full height", show=False),
        Binding("ctrl+l", "clear_transcript", "Clear", show=False),
        Binding("escape", "hide_panel", "Hide", show=False),
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
        self._refresh_transcript()
        self._update_running()
        restored_input.focus()
        self._history.refresh()
        context = await asyncio.to_thread(resolve_working_context, self.app, session)
        self._working_context = context
        self._update_chip()
        self._update_ghost()
        self.transcript.start_tail_task()

    async def on_unmount(self) -> None:
        """Persist the draft and stop tail polling."""
        self._store_draft()
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
        session = self.session
        prepared = prepare_submit(session, widget.normalized_text())
        if prepared is None:
            return
        block = session.add_block(prepared.line)
        widget.set_line("")
        session.draft = ""
        session.draft_cursor = 0
        self._walk_anchor = None
        self._refresh_transcript()
        self._update_running()
        run_worker = getattr(self.app, "run_worker", None)
        if not callable(run_worker):
            apply_submit_failure(block, "worker unavailable")
            self._refresh_transcript()
            return
        run_worker(
            self._submit_worker(
                block=block,
                tokens=prepared.tokens,
                line=prepared.line,
            ),
            exclusive=False,
        )

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

    def _refresh_transcript(self) -> None:
        try:
            self.transcript.refresh_blocks(self.session.blocks)
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            pass

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


__all__ = [
    "COMMAND_LINE_IDLE_HINT",
    "COMMAND_LINE_INPUT_HINTS",
    "COMMAND_LINE_PREFIX",
    "CommandLineScreen",
]
