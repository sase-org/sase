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
"""

from __future__ import annotations

import asyncio
import json
import os
import time
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
from sase.ace.tui.command_line.session import (
    CommandLineBlock,
    CommandLineSession,
    command_line_session_for,
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
#: Bottom-border key hints while the completion menu is active.
COMMAND_LINE_MENU_HINTS = "⏎ accept · ↑↓ move · esc normal"
#: Signature-row text while the grammar loader worker is still in flight.
COMMAND_LINE_INDEXING_HINT = "indexing commands…"


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
    #command-line-popup {
        height: auto;
        max-height: 9;
        border: round $primary;
        margin: 0 2;
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
            popup = CommandLinePopup()
            popup.display = False
            yield popup
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
        self._refresh_transcript()
        self._update_running()
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
        session = self.session
        line = widget.normalized_text()
        prepared = prepare_submit(session, line, tokens=self._submit_tokens())
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
        context = resolve_command_line(self.app, line, cursor)
        self._resolve_context = context
        self._resolved_line = line
        widget.set_resolve_context(context)
        if context is None:
            self._show_indexing(bool(line.strip()))
            self._record_keystroke_probe(time.perf_counter() - started, False)
            return
        completion = self._complete_line(line, cursor, context)
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
            self._provider_note = f"⚠ {value_kind} unavailable"
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
        if not items or not line.strip():
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
            if not state.menu_active:
                return False
            decision = state.on_enter()
        elif key == "escape":
            if not state.menu_active:
                return False
            decision = state.on_escape()
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
    "COMMAND_LINE_IDLE_HINT",
    "COMMAND_LINE_INDEXING_HINT",
    "COMMAND_LINE_INPUT_HINTS",
    "COMMAND_LINE_MENU_HINTS",
    "COMMAND_LINE_PREFIX",
    "CommandLineScreen",
]
