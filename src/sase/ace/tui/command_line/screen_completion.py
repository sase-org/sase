"""Completion behavior for ``CommandLineScreen``."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

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
from sase.ace.tui.command_line.cd_completion import (
    cd_completion_context,
    complete_cd,
    path_request_for_slot,
    source_key_for_slot,
)
from sase.ace.tui.command_line.completion_probe import (
    schedule_command_line_keystroke_probe,
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
    prepend_marked_row,
    provider_empty_note,
    provider_unavailable_note,
    rank_history_entries,
    selected_entity_kind,
    top_level_command_count,
)
from sase.ace.tui.command_line.grammar import (
    command_line_grammar_for,
    is_command_line_grammar_pending,
    resolve_command_line,
)
from sase.ace.tui.command_line.input import CommandLineInput, command_line_keymaps_for
from sase.ace.tui.command_line.policies import (
    append_confirm_flag,
    deny_note_for,
    run_in_terminal,
    submit_route_for,
)
from sase.ace.tui.command_line.popup import CommandLinePopup, popup_footer
from sase.ace.tui.command_line.restore import load_block_tail_text
from sase.ace.tui.command_line.screen_completion_keys import CommandLineScreenKeysMixin
from sase.ace.tui.command_line.screen_constants import (
    COMMAND_LINE_INDEXING_HINT,
    COMMAND_LINE_SEARCH_HINT,
    command_line_idle_hint,
)
from sase.ace.tui.command_line.session import CommandLineBlock, tokenize_command_line
from sase.ace.tui.command_line.signature import signature_hint_line
from sase.ace.tui.command_line.sources import (
    PROVIDER_DEBOUNCE_SECONDS,
    collect_dynamic_candidates,
    needs_provider_fetch,
    path_candidates,
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
from sase.completion.command_line_grammar import LineContext


class CommandLineScreenCompletionMixin(CommandLineScreenKeysMixin):
    """Behavior mixed into the public command-line screen."""

    _history_search_active: bool
    _provider_task: asyncio.Task[None] | None
    _resolved_line: str | None

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

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
        started = widget.take_keypress_stamp() or time.perf_counter()
        if self._history_search_active:
            self._render_history_search(line)
            self._record_keystroke_probe(started, True)
            return
        if not line.strip():
            self._render_empty_state(line)
            self._record_keystroke_probe(started, True)
            return
        self._empty_state_active = False
        context = cd_completion_context(line, cursor) or resolve_command_line(
            self.app, line, cursor
        )
        self._resolve_context = context
        self._resolved_line = line
        widget.set_resolve_context(context)
        if context is None:
            self._show_indexing(bool(line.strip()))
            self._record_keystroke_probe(started, False)
            return
        completion = self._complete_line(line, cursor, context)
        completion = prepend_marked_row(
            context, completion, help_lookup=self._help_lookup, app=self.app
        )
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
        self._record_keystroke_probe(started, True)

    def _complete_line(
        self, line: str, cursor: int, context: LineContext
    ) -> dict[str, Any]:
        """Rank candidates for the cursor slot through the Rust handle."""
        slot = context.get("slot") or {}
        value_kind = str(slot.get("value_kind") or "")
        project = self._working_context.project if self._working_context else None
        source_key = self._source_key(line, cursor, context)
        dynamic = collect_dynamic_candidates(
            self.app,
            value_kind,
            project,
            self._provider_cache,
            source_key=source_key,
        )
        if context.get("builtin") == "cd":
            return complete_cd(line, cursor, context, dynamic)
        handle = command_line_grammar_for(self.app)
        if handle is None:
            return {
                "items": [],
                "total": 0,
                "kind": "",
                "replace_start": cursor,
                "replace_end": cursor,
            }
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

    def _working_cwd(self) -> str:
        """Return the pinned cwd, or empty when the panel has no context."""
        return self._working_context.cwd if self._working_context else ""

    def _path_request(self, line: str, cursor: int, context: LineContext) -> Any | None:
        """Build the pure path scan request for a path/dir slot, if applicable."""
        return path_request_for_slot(line, cursor, context, self._working_cwd())

    def _source_key(self, line: str, cursor: int, context: LineContext) -> str | None:
        """Return a directory-specific cache key for native path rows."""
        return source_key_for_slot(line, cursor, context, self._working_cwd())

    def _maybe_fetch_providers(
        self, line: str, cursor: int, context: LineContext
    ) -> None:
        """Schedule a debounced provider fetch for the active slot, if any."""
        slot = context.get("slot") or {}
        value_kind = str(slot.get("value_kind") or "")
        if not needs_provider_fetch(value_kind, self.app):
            return
        project = self._working_context.project if self._working_context else None
        source_key = self._source_key(line, cursor, context)
        if (
            self._provider_cache.cached(value_kind, project, source_key=source_key)
            is not None
        ):
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
            self._provider_fetch_task(
                generation,
                value_kind,
                project,
                line,
                cursor,
                source_key,
                self._path_request(line, cursor, context),
                use_disk_cache=not self._provider_cache.bypass_disk_cache(
                    value_kind, project
                ),
            )
        )

    def invalidate_provider_cache(self) -> None:
        """Drop cached provider rows after a command finished (UI thread).

        A finished command may have changed what a slot offers (an approved
        plan is no longer pending). Clearing the cache retires every fetch
        already in flight and makes the next fetch skip the providers' disk
        cache. The popup refetches right away when the cursor sits in a
        provider-backed slot; an active menu keeps its rows, and the next
        render refetches instead.
        """
        self._provider_cache.invalidate()
        stale_task, self._provider_task = self._provider_task, None
        if stale_task is not None:
            stale_task.cancel()
        if self._popup_state.menu_active:
            return
        if needs_provider_fetch(self._current_value_kind(), self.app):
            self._refresh_completion()

    def _fetch_still_current(self, line: str, cursor: int) -> bool:
        """Return True while the input still shows *line* with the cursor at *cursor*."""
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - teardown races degrade silently.
            return False
        if widget.text != line:
            return False
        try:
            return bool(widget.cursor_location[1] == cursor)
        except Exception:  # noqa: BLE001 - cursor read is best effort.
            return bool(len(widget.text) == cursor)

    async def _provider_fetch_task(
        self,
        generation: int,
        value_kind: str,
        project: str | None,
        line: str,
        cursor: int,
        source_key: str | None,
        path_request: Any | None,
        *,
        use_disk_cache: bool = True,
    ) -> None:
        """Fetch provider candidates, dropping results for a moved line or cursor."""
        from sase.completion.candidates.providers import candidates_for

        await asyncio.sleep(PROVIDER_DEBOUNCE_SECONDS)
        if not self._fetch_still_current(line, cursor):
            return
        if not self._provider_cache.is_current(generation):
            return
        failed = False
        fetched: list[Any] = []
        try:
            if path_request is not None:
                fetched = await asyncio.to_thread(
                    path_candidates,
                    path_request,
                    directories_only=value_kind == "dir",
                )
            else:
                fetched = await asyncio.to_thread(
                    candidates_for,
                    value_kind,
                    "",
                    project=project,
                    limit=2000,
                    use_disk_cache=use_disk_cache,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - provider failure is advisory.
            failed = True
        # The await let the user keep typing or move the cursor: the result
        # belongs to a line that no longer exists, so drop it (last wins).
        if not self._fetch_still_current(line, cursor):
            return
        if failed:
            self._provider_cache.note_unavailable(
                value_kind, project, source_key=source_key
            )
            self._render_popup_footer()
            return
        items = (
            fetched
            if path_request is not None
            else [
                {
                    "value": candidate.value,
                    "description": candidate.description,
                    "source": "provider",
                }
                for candidate in fetched
            ]
        )
        if not self._provider_cache.commit(
            generation, value_kind, project, items, source_key=source_key
        ):
            return  # A newer keystroke already won; drop this result.
        if items:
            self._refresh_completion()
        else:
            self._render_popup_footer()  # Nothing new to rank: only the note changes.

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
        count = top_level_command_count(self._help_lookup)
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

    def _hide_doc_peek(self) -> None:
        """Hide the right-hand doc-peek card."""
        try:
            peek = self.query_one("#command-line-doc-peek", Static)
            peek.display = False
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        self._doc_peek_text = ""
        self._layout_popup()

    def _render_doc_peek(self) -> None:
        """Show the doc-peek card for a highlighted subcommand or option."""
        try:
            peek = self.query_one("#command-line-doc-peek", Static)
            width = self.size.width
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        if not doc_peek_visible(width):
            self._hide_doc_peek()
            return
        highlighted = self._popup_state.highlighted
        if highlighted is None:
            self._hide_doc_peek()
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
            self._hide_doc_peek()
            return
        peek.update(card)
        peek.display = True
        self._doc_peek_text = card
        self._layout_popup()

    def _current_value_kind(self) -> str:
        """Return the value kind of the slot under the cursor, or ``""``."""
        if self._resolve_context is None or self._history_search_active:
            return ""
        slot = self._resolve_context.get("slot") or {}
        return str(slot.get("value_kind") or "")

    def _provider_footer_note(self) -> str | None:
        """Return the footer note for the current slot's provider, if any.

        The note is derived from the fresh cache entry of the slot's own
        value kind, so it can never leak onto another slot's popup: a failed
        fetch reads ``⚠ <kind> unavailable``, an empty one ``no <kind>``.
        """
        value_kind = self._current_value_kind()
        if not needs_provider_fetch(value_kind, self.app):
            return None
        context = self._resolve_context
        if context is None:
            return None
        project = self._working_context.project if self._working_context else None
        source_key = None
        try:
            widget = self.query_one(CommandLineInput)
            source_key = self._source_key(
                widget.text, widget.cursor_location[1], context
            )
        except Exception:  # noqa: BLE001 - footer must not disturb teardown.
            pass
        health = self._provider_cache.health(value_kind, project, source_key=source_key)
        if health == "failed":
            return provider_unavailable_note(value_kind)
        if health == "empty":
            return provider_empty_note(value_kind)
        return None

    def _render_popup(self, completion: dict[str, Any]) -> None:
        """Show or hide the floating popup and its footer."""
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        self._popup_completion = completion
        items = completion.get("items", [])
        try:
            line = self.query_one(CommandLineInput).text
        except Exception:  # noqa: BLE001 - fall back to showing rows.
            line = "x"
        stored_rows = self._empty_state_active or self._history_search_active
        if not items or (not line.strip() and not stored_rows):
            popup.show_items([])
        else:
            popup.show_items(items)
        self._render_popup_footer()
        self._update_keys_hint()

    def _render_popup_footer(self) -> None:
        """Repaint the popup footer from the last rendered completion."""
        try:
            popup = self.query_one(CommandLinePopup)
            footer = self.query_one("#command-line-popup-footer", Static)
        except Exception:  # noqa: BLE001 - unmounted screen cannot render.
            return
        completion = self._popup_completion
        note = self._provider_footer_note()
        if not popup.display:
            # No rows to caption; an empty or failed provider still says so.
            footer.update(note or "")
            footer.display = bool(note)
            self._layout_popup()
            return
        state = self._popup_state
        items = completion.get("items", [])
        kind = str(completion.get("kind", "") or "commands")
        total = int(completion.get("total", len(items)) or len(items))
        position = state.index + 1 if state.menu_active else min(len(items), total)
        footer.update(
            popup_footer(
                kind, position, total, menu_active=state.menu_active, note=note
            )
        )
        footer.display = True
        self._layout_popup()

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
                hint_row.update(command_line_idle_hint(command_line_keymaps_for(self)))
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
            hint_row.update(command_line_idle_hint(command_line_keymaps_for(self)))
        self._update_keys_hint()
        self._layout_popup()

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

    def _record_keystroke_probe(self, keypress_at: float, indexed: bool) -> None:
        """Schedule a key-to-popup-paint sample when ``SASE_TUI_PERF=1``."""
        schedule_command_line_keystroke_probe(
            self.call_after_refresh, keypress_at, indexed
        )


__all__ = ["CommandLineScreenCompletionMixin"]
