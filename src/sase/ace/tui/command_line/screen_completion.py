"""Completion behavior for ``CommandLineScreen``."""

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


class CommandLineScreenCompletionMixin:
    """Behavior mixed into the public command-line screen."""

    _history_search_active: bool
    _provider_note: str | None
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
        self, line: str, cursor: int, context: LineContext
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
        self, line: str, cursor: int, context: LineContext
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
        value_kind = ""
        if self._resolve_context is not None:
            slot = self._resolve_context.get("slot") or {}
            value_kind = str(slot.get("value_kind") or "")
        return {
            "items": self._popup_state.items,
            "total": len(self._popup_state.items),
            "kind": value_kind,
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
        """Apply the zsh menu-select key rules; True when the key is consumed.

        The fixed menu keys (Tab, Shift-Tab, ``ctrl+n``/``ctrl+p``,
        ``ctrl+f``/Enter accept, Esc-leaves-menu) follow the zsh
        menu-select contract. History prev/next/search come from the live
        ``ace.keymaps.command_line`` scope instead of literals.
        """
        key = getattr(event, "key", None) or ""
        keymaps = command_line_keymaps_for(self)
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
            keys.update(command_line_input_hints(command_line_keymaps_for(self)))

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
        if source is not popup or bool(getattr(popup, "echo_guarded", False)):
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


__all__ = ["CommandLineScreenCompletionMixin"]
