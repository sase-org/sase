"""Reusable ``TextArea`` with the full vim + readline editing layer.

``VimTextArea`` bundles the vim mixin tower (normal / visual modes, motions,
operators, counts, registers, dot-repeat, surround, text objects) plus the
line-rendering mixin into a standalone widget that any host can drop in. It owns
the vim state, the mode transitions, the lean key dispatcher, and the
readline-style insert bindings.

Everything the vim tower needs from its host is funneled through a small set of
overridable *host hooks* (mode-display rendering, ``g``-prefix dispatch/hints,
undo/redo notifications, and the search / preview / jump callouts). The defaults
here keep a bare ``VimTextArea`` fully functional -- the mode is surfaced on the
widget's own border, and the prompt-only callouts are inert. ``PromptTextArea``
subclasses this and overrides the hooks to route through its ``PromptInputBar``.
"""

from __future__ import annotations

from typing import Any

from textual.events import Key
from textual.widgets import TextArea

from sase.ace.tui.widgets._line_rendering import LineRenderingMixin
from sase.ace.tui.widgets._vim_normal import VimNormalModeMixin
from sase.ace.tui.widgets._vim_normal_state import VisualMutation
from sase.ace.tui.widgets._vim_registers import VimRegister
from sase.ace.tui.widgets._vim_search import SearchDirection

__all__ = ["VimTextArea"]


_MODE_TITLES = {
    "insert": "[INSERT]",
    "normal": "[NORMAL]",
    "visual": "[VISUAL]",
    "visual_line": "[V-LINE]",
}


class VimTextArea(VimNormalModeMixin, LineRenderingMixin, TextArea):
    """A ``TextArea`` with vim normal/visual modes and readline insert keys.

    Enter and other structural keys are intentionally *not* bound here so a host
    (or the single-line subclass) can decide what they do. Only the generic
    readline cursor bindings live on this base; ``ctrl+w`` / ``ctrl+u`` /
    ``ctrl+k`` / ``ctrl+z`` come from Textual's ``TextArea`` defaults.
    """

    BINDINGS = [
        ("ctrl+a", "cursor_line_start", "Start"),
        ("ctrl+e", "cursor_line_end", "End"),
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("alt+f", "cursor_word_right", "Forward word"),
        ("alt+b", "cursor_word_left", "Backward word"),
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._vim_mode: str = "insert"
        self._pending_keys: str = ""
        self._count_prefix: str = ""
        self._pending_count: int | None = None
        self._pending_operator: str = ""
        self._pending_operator_count: int = 1
        self._pending_surround_range: (
            tuple[str, tuple[int, int], tuple[int, int]] | None
        ) = None
        self._pending_change_surround_locations: (
            tuple[
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
                tuple[int, int],
            ]
            | None
        ) = None
        self._mutation_key_buffer: list[str] = []
        self._mutation_count: int = 1
        self._last_mutation_keys: list[str] = []
        self._last_mutation_count: int = 1
        self._last_mutation_insert: str | None = None
        self._last_visual_mutation: VisualMutation | None = None
        self._dot_insert_capture_offset: int | None = None
        self._replaying_dot: bool = False
        self._last_char_search: tuple[str, str] | None = None
        self._vim_register: VimRegister = VimRegister()
        self._visual_anchor: tuple[int, int] | None = None
        self._visual_cursor: tuple[int, int] | None = None
        self._pending_visual_surround_range: (
            tuple[str, tuple[int, int], tuple[int, int], int] | None
        ) = None

    # -- Offset helpers (used pervasively by the vim tower) --------------------

    def _absolute_offset(self, location: tuple[int, int]) -> int:
        """Convert a document location to an absolute character offset."""
        row, col = location
        return sum(len(self.document.get_line(r)) + 1 for r in range(row)) + col

    def _location_from_absolute(self, offset: int) -> tuple[int, int]:
        """Convert an absolute character offset to a document location."""
        remaining = max(0, offset)
        for row in range(self.document.line_count):
            line_len = len(self.document.get_line(row))
            if remaining <= line_len:
                return row, remaining
            remaining -= line_len + 1
        last_row = self.document.line_count - 1
        return last_row, len(self.document.get_line(last_row))

    # -- Lean key dispatch -----------------------------------------------------

    def _has_pending_normal_state(self) -> bool:
        """Return whether a partial NORMAL-mode sequence is mid-composition."""
        return bool(self._pending_keys or self._pending_operator or self._count_prefix)

    def _swallow_unhandled_vim_key(self, event: Key) -> None:
        """Consume a printable NORMAL/VISUAL key the vim layer did not handle.

        In vim an unmapped printable NORMAL-mode key is a no-op; letting it bubble
        instead hands it to whatever app-level binding owns that character -- e.g.
        bare ``space`` would reach ``start_agent_home``, which unmounts the prompt
        bar and rewrites its text to history as cancelled. Only printable keys are
        swallowed, so the structural keys hosts rely on (``enter``, ``escape``,
        ``tab``, every ctrl/alt chord) keep bubbling as before.
        """
        if not event.is_printable:
            return
        if self._host_claims_unhandled_vim_key(event):
            return
        event.stop()
        event.prevent_default()

    async def _on_key(self, event: Key) -> None:
        """Route keys through the vim tower, then fall back to ``TextArea``.

        Keys the vim layer consumes are stopped. Unconsumed printable keys are
        also swallowed in NORMAL/VISUAL mode; only non-printable keys bubble so
        host-level bindings (confirm, cancel, etc.) keep working. In INSERT mode
        this is a thin passthrough to ``TextArea`` (with ``Escape`` dropping into
        NORMAL mode), matching the prompt widget's behavior.

        ``Escape`` is two-stage: INSERT -> NORMAL, then a NORMAL-mode ``Escape``
        with a pending count/operator/prefix clears it. A NORMAL-mode ``Escape``
        with nothing pending is left unconsumed so a host (e.g. a modal) can act
        on it -- typically to back out.

        Textual invokes every ``_on_key`` in the MRO (until one calls
        ``prevent_default``), so a subclass that runs its own vim dispatch first
        (``PromptTextArea``) marks the event via ``_handle_normal_mode_key`` /
        ``_handle_visual_mode_key``. This base handler then no-ops on that marked
        event rather than dispatching it a second time (a re-dispatch would see
        the state the first pass already mutated -- e.g. a cleared count).
        """
        if self._vim_mode in ("visual", "visual_line"):
            if getattr(event, "_vim_tower_dispatched", False):
                self._swallow_unhandled_vim_key(event)
                return
            if self._handle_visual_mode_key(event):
                event.stop()
                event.prevent_default()
                return
            self._swallow_unhandled_vim_key(event)
            return

        if self._vim_mode == "normal":
            if getattr(event, "_vim_tower_dispatched", False):
                self._swallow_unhandled_vim_key(event)
                return
            if event.key == "escape" and not self._has_pending_normal_state():
                return
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
                return
            self._swallow_unhandled_vim_key(event)
            return

        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        await super()._on_key(event)

    # -- Mode transitions ------------------------------------------------------

    def _enter_normal_mode(self) -> None:
        """Switch to vim NORMAL mode with relative line numbers."""
        self._finish_dot_insert_capture()
        self._clear_visual_state()
        self._vim_mode = "normal"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_surround_range = None
        self._pending_change_surround_locations = None
        self._pending_visual_surround_range = None
        self.read_only = True
        self._sync_vim_cursor_class()
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = True
        self._update_vim_mode_display()

    def _enter_insert_mode(self) -> None:
        """Switch to vim INSERT mode."""
        self._clear_visual_state()
        self._vim_mode = "insert"
        self._pending_operator = ""
        self._pending_operator_count = 1
        self._pending_surround_range = None
        self._pending_change_surround_locations = None
        self._pending_visual_surround_range = None
        self.read_only = False
        self._sync_vim_cursor_class()
        self.show_line_numbers = self.document.line_count > 1
        self.highlight_cursor_line = False
        self._update_vim_mode_display()

    # -- Readline line-hop actions (shadow the ``TextArea`` defaults) ----------

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Move to end of line, or end of next line if already there."""
        row, col = self.cursor_location
        line_end = len(self.document.get_line(row))
        if col >= line_end and row < self.document.line_count - 1:
            next_end = len(self.document.get_line(row + 1))
            self.move_cursor((row + 1, next_end), select=select)
        else:
            self.move_cursor((row, line_end), select=select)

    def action_cursor_line_start(self, select: bool = False) -> None:
        """Move to start of line, or start of previous line if already there."""
        row, col = self.cursor_location
        if col == 0 and row > 0:
            self.move_cursor((row - 1, 0), select=select)
        else:
            self.move_cursor((row, 0), select=select)

    # -- Host hooks (safe defaults; subclasses override to reach their host) ---

    def _host_claims_unhandled_vim_key(self, event: Key) -> bool:
        """Return whether the host owns this unhandled printable key. Default: no.

        Overridden by hosts that deliberately bind a printable NORMAL-mode key the
        vim layer leaves free -- the AXE entry editor's value cells let ``q`` reach
        the sheet's quit binding.
        """
        return False

    def _normal_open_below_insert_text(self, row: int) -> str:
        """Return the structural text inserted by NORMAL-mode ``o``."""
        return "\n"

    def _normal_open_above_insert_text(self, row: int) -> str:
        """Return the structural text inserted by NORMAL-mode ``O``."""
        return "\n"

    def _normal_join_next_line_text(self, next_line: str) -> str:
        """Return the pulled-up line NORMAL-mode ``J`` folds in. Default: verbatim."""
        return next_line

    def _normalize_normal_open_below_replay_text(self, insert_text: str) -> str:
        """Normalize captured ``o`` text after structural replay. Default: identity."""
        return insert_text

    def _normalize_normal_open_above_replay_text(self, insert_text: str) -> str:
        """Normalize captured ``O`` text after structural replay. Default: identity."""
        return insert_text

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        """Render the current mode + pending indicator on the widget border.

        Hosts that own a richer chrome (a prompt bar, a status line, ...) should
        override this to route the mode/indicator there instead. Border titles
        parse Rich markup, so the literal mode brackets are escaped.
        """
        title = _MODE_TITLES.get(self._vim_mode, "")
        self.border_title = title.replace("[", r"\[")
        self.border_subtitle = indicator.replace("[", r"\[")

    def _dispatch_host_g_prefix_key(self, key: str) -> bool:
        """Give the host a chance to own a ``g<key>`` sequence. Default: no."""
        return False

    def _show_pending_g_hints(self) -> None:
        """Reveal the host's ``g``-prefix continuation hints. Default: no-op."""

    def _hide_pending_g_hints(self) -> None:
        """Hide the host's ``g``-prefix continuation hints. Default: no-op."""

    def _notify_host_text_undo(self, before_text: str, after_text: str) -> None:
        """Notify the host that a NORMAL-mode undo changed the text. Default: no-op."""

    def _notify_host_text_redo(self, before_text: str, after_text: str) -> None:
        """Notify the host that a NORMAL-mode redo changed the text. Default: no-op."""

    def _start_prompt_search(self, direction: SearchDirection) -> None:
        """Open the host's incremental search (``/`` / ``?``). Default: inert."""

    def _repeat_prompt_search(
        self,
        *,
        reverse: bool = False,
        count: int = 1,
    ) -> bool:
        """Repeat the host's last search (``n`` / ``N``). Default: inert."""
        return True

    def _clear_prompt_search(self, *, clear_highlights: bool = False) -> None:
        """Tear down the host's active search command line. Default: no-op."""

    def _clear_search_highlights(self, *, refresh: bool = True) -> None:
        """Clear the host's search highlights. Default: no-op."""

    def _flash_yank(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        """Briefly highlight a just-yanked region. Default: no-op."""

    def _preview_token_under_cursor(self) -> None:
        """Preview the token under the cursor (``K``). Default: inert."""

    def _jump_to_definition_under_cursor(self) -> None:
        """Jump to the definition under the cursor (``ctrl+]``). Default: inert."""
