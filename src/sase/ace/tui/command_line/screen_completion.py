"""Completion behavior for ``CommandLineScreen``."""

from __future__ import annotations

import asyncio
import json
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
from sase.ace.tui.command_line.chrome import CommandLineFrame
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
    provider_empty_note,
    provider_unavailable_note,
    rank_history_entries,
    selected_entity_kind,
    slot_is_variadic,
    top_level_command_count,
)
from sase.ace.tui.command_line.grammar import (
    command_line_grammar_for,
    is_command_line_grammar_pending,
    resolve_command_line,
)
from sase.ace.tui.command_line.input import (
    CommandLineInput,
    binding_matches_key,
    command_line_keymaps_for,
)
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
    COMMAND_LINE_INDEXING_HINT,
    COMMAND_LINE_MENU_HINTS,
    COMMAND_LINE_SEARCH_HINT,
    command_line_idle_hint,
    command_line_input_hints,
)
from sase.ace.tui.command_line.session import CommandLineBlock, tokenize_command_line
from sase.ace.tui.command_line.signature import signature_hint_line
from sase.ace.tui.command_line.sources import (
    PROVIDER_DEBOUNCE_SECONDS,
    collect_dynamic_candidates,
    needs_provider_fetch,
    path_candidates,
    path_completion_request,
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
from sase.ace.tui.util.perf import is_enabled as tui_perf_enabled
from sase.ace.tui.util.perf import perf_log_path
from sase.completion.command_line_grammar import LineContext


def _command_line_probe_sample(
    keypress_at: float, model_updated_at: float, painted_at: float, indexed: bool
) -> dict[str, object]:
    """Build one command-line key-to-paint perf sample."""
    return {
        "action": "command_line.complete",
        "tab": "command_line",
        "t_keypress": keypress_at,
        "model_ms": round((model_updated_at - keypress_at) * 1000, 3),
        "paint_ms": round((painted_at - keypress_at) * 1000, 3),
        "indexed": indexed,
    }


def _append_command_line_probe(sample: dict[str, object]) -> None:
    """Append a completed probe from a worker, never from the UI thread."""
    if not tui_perf_enabled():
        return
    try:
        path = perf_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(sample) + "\n")
    except OSError:
        # Probe output is diagnostic only: a read-only or full disk must never
        # affect typing.
        pass


class CommandLineScreenCompletionMixin:
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
        started = time.perf_counter()
        if self._history_search_active:
            self._render_history_search(line)
            self._record_keystroke_probe(started, True)
            return
        if not line.strip():
            self._render_empty_state(line)
            self._record_keystroke_probe(started, True)
            return
        self._empty_state_active = False
        context = self._cd_completion_context(line, cursor) or resolve_command_line(
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
            return self._complete_cd(line, cursor, context, dynamic)
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

    def _cd_completion_context(self, line: str, cursor: int) -> LineContext | None:
        """Resolve the ``cd`` built-in's single completion slot in memory."""
        before_cursor = line[:cursor]
        leading = len(before_cursor) - len(before_cursor.lstrip())
        command_end = leading + 2
        if before_cursor[leading:command_end] != "cd":
            return None
        if len(before_cursor) == command_end:
            return None
        if not before_cursor[command_end].isspace():
            return None
        replace_start = command_end
        while (
            replace_start < len(before_cursor)
            and before_cursor[replace_start].isspace()
        ):
            replace_start += 1
        token = before_cursor[replace_start:]
        # ``cd`` accepts exactly one argument.  Leave editing later text to the
        # normal input rather than replacing a surprising span.
        if any(char.isspace() for char in token):
            return None
        value_kind = "project" if token.startswith("+") else "dir"
        return cast(
            LineContext,
            {
                "builtin": "cd",
                "path": ["cd"],
                "argv": ["cd", token],
                "slot": {
                    "value_kind": value_kind,
                    "replace_start": replace_start,
                    "replace_end": cursor,
                },
            },
        )

    @staticmethod
    def _slot_prefix(line: str, cursor: int, context: LineContext) -> str:
        """Return the current slot text without resolving or touching disk."""
        slot = context.get("slot") or {}
        try:
            start = int(slot.get("replace_start", cursor))
        except (TypeError, ValueError):
            start = cursor
        return line[max(0, min(start, cursor)) : max(0, cursor)]

    def _path_request(self, line: str, cursor: int, context: LineContext) -> Any | None:
        """Build the pure path scan request for a path/dir slot, if applicable."""
        slot = context.get("slot") or {}
        value_kind = str(slot.get("value_kind") or "")
        if value_kind not in {"path", "dir"}:
            return None
        cwd = self._working_context.cwd if self._working_context else ""
        return path_completion_request(self._slot_prefix(line, cursor, context), cwd)

    def _source_key(self, line: str, cursor: int, context: LineContext) -> str | None:
        """Return a directory-specific cache key for native path rows."""
        request = self._path_request(line, cursor, context)
        return None if request is None else request.source_key

    def _complete_cd(
        self,
        line: str,
        cursor: int,
        context: LineContext,
        dynamic: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Render ``cd``'s directory, project, and unpin candidates."""
        slot = context.get("slot") or {}
        value_kind = str(slot.get("value_kind") or "dir")
        typed = self._slot_prefix(line, cursor, context)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        if typed.startswith("-"):
            items.append(
                {
                    "insert_text": "-",
                    "display": "-",
                    "description": "unpin and follow the TUI project",
                    "badge": "dir",
                    "source": "builtin",
                    "match_runs": [],
                    "selected": False,
                }
            )
        for candidate in dynamic:
            raw_value = str(candidate.get("value", "") or "")
            if not raw_value:
                continue
            insert = f"+{raw_value}" if value_kind == "project" else raw_value
            if not insert.casefold().startswith(typed.casefold()) or insert in seen:
                continue
            seen.add(insert)
            items.append(
                {
                    "insert_text": insert,
                    "display": str(candidate.get("display") or insert),
                    "description": str(candidate.get("description") or ""),
                    "badge": str(candidate.get("badge") or value_kind),
                    "source": str(candidate.get("source") or "provider"),
                    "match_runs": [],
                    "selected": False,
                }
            )
        return {
            "items": items,
            "total": len(items),
            "kind": value_kind,
            "replace_start": int(slot.get("replace_start", cursor)),
            "replace_end": int(slot.get("replace_end", cursor)),
        }

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
            )
        )

    def invalidate_provider_cache(self) -> None:
        """Drop cached provider rows after a command finished (UI thread).

        A finished command may have changed what a slot offers (an approved
        plan is no longer pending). The popup refetches right away when the
        cursor sits in a provider-backed slot, unless a menu is active.
        """
        self._provider_cache.invalidate()
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
                    candidates_for, value_kind, "", project=project, limit=2000
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

    def command_line_handle_key(self, event: Any) -> bool:
        """Apply the zsh menu-select key rules; True when the key is consumed.

        The fixed menu keys (Tab, Shift-Tab, ``ctrl+n``/``ctrl+p``,
        ``ctrl+f``/Enter accept, Esc-leaves-menu) follow the zsh
        menu-select contract. History prev/next/search come from the live
        ``ace.keymaps.command_line`` scope instead of literals.
        """
        key = getattr(event, "key", None) or ""
        keymaps = command_line_keymaps_for(self)
        state = self._popup_state
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot complete.
            return False
        if state.typed_text != widget.text:
            # TextArea.Changed is queued separately from Key. A fast typist can
            # therefore press Tab after the widget has accepted text but before
            # its popup state has caught up. Resolve synchronously so Tab never
            # inserts a stale whole-command suggestion at the wrong span.
            self._refresh_completion()
            state = self._popup_state
        decision: PopupDecision | None = None
        prev_match = binding_matches_key(keymaps.history_prev, key)
        next_match = binding_matches_key(keymaps.history_next, key)
        if key == "tab":
            decision = state.on_tab()
        elif key == "shift+tab":
            decision = state.on_shift_tab()
        elif key == "ctrl+n":
            decision = state.on_ctrl_n()
        elif key == "ctrl+p":
            decision = state.on_ctrl_p()
        elif prev_match or next_match:
            if state.menu_active:
                decision = state.on_ctrl_n() if next_match else state.on_ctrl_p()
            else:
                self.history_step(1 if prev_match else -1)
                return True
        elif key == "ctrl+f":
            if not state.menu_active:
                return False
            decision = state.on_enter()
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
        elif binding_matches_key(keymaps.history_search, key):
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
            self._render_popup_footer()
            self._render_signature()
            self._update_keys_hint()
            return True
        if action == "move":
            popup.highlight_index(self._popup_state.index)
            self._render_popup_footer()
            self._render_signature()
            return True
        if action == "leave-menu":
            try:
                widget = self.query_one(CommandLineInput)
                widget.set_line(decision.text or "")
            except Exception:  # noqa: BLE001 - teardown races degrade silently.
                pass
            try:
                popup.clear_highlight()
            except Exception:  # noqa: BLE001 - highlight clear is best effort.
                pass
            self._render_popup_footer()
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
            frame = self.query_one("#command-line-frame", CommandLineFrame)
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            return
        if self._popup_state.menu_active:
            frame.set_key_hints(COMMAND_LINE_MENU_HINTS)
        else:
            frame.set_key_hints(
                command_line_input_hints(command_line_keymaps_for(self))
            )

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
        popup: CommandLinePopup
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen ignores highlights.
            return
        if getattr(event, "option_list", getattr(event, "control", None)) is not popup:
            return
        # Rule 12: the popup swallows echoes of its own programmatic highlights.
        index = popup.user_highlight_index(event)
        if index is None or not 0 <= index < len(self._popup_state.items):
            return
        if index != self._popup_state.index:
            self._popup_state.index = index
            self._render_popup_footer()
            self._render_signature()

    def _record_keystroke_probe(self, keypress_at: float, indexed: bool) -> None:
        """Schedule a key-to-popup-paint sample when ``SASE_TUI_PERF=1``.

        ``_refresh_completion`` has already rendered by the time it calls us.
        Capturing the finish from ``call_after_refresh`` therefore measures the
        visible popup, not merely synchronous resolver work. The JSONL append
        goes through ``asyncio.to_thread`` so this diagnostic never puts disk
        I/O on the input event path.
        """
        if not tui_perf_enabled():
            return
        model_updated_at = time.perf_counter()

        def _after_paint() -> None:
            sample = _command_line_probe_sample(
                keypress_at, model_updated_at, time.perf_counter(), indexed
            )
            try:
                asyncio.get_running_loop().create_task(
                    asyncio.to_thread(_append_command_line_probe, sample)
                )
            except RuntimeError:  # teardown has no live loop.
                pass

        try:
            self.call_after_refresh(_after_paint)
        except Exception:  # noqa: BLE001 - an unmounted panel cannot paint.
            pass


__all__ = ["CommandLineScreenCompletionMixin"]
