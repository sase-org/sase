"""Ghost state, gating, fitting, and reveal scheduling for next-word ghosts.

Split out of ``_next_word_ghost_display``: this mixin owns the ghost
constants, settings gating, ghost visibility checks, the border-hint
surface helpers, the reveal-beat scheduler primitives, and ghost
set/clear. Peek display, ghost validation, the reveal fire callback,
auto trigger, and accepts live in ``_next_word_ghost_peek`` whose
mixin derives from this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from rich.text import Text

from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_GHOST_HINT,
    NextWordGhost,
    build_next_word_ghost_text,
    next_word_ghost_expected,
)
from sase.ace.tui.widgets.next_word_placement import (
    NextWordPlacement,
    classify_next_word_placement,
    fit_next_word_ghost_with_tail,
    next_word_is_last_wrapped_section,
    next_word_rest_of_line,
)

#: Menu rows requested by the ghost-only paths (arming and auto mode). The
#: core computes the gate and ghost before truncating the menu, so zero rows
#: keeps both identical while skipping every row's continuation preview,
#: which cuts real-history predict p95 by about two thirds. Only the explicit
#: menu requests ``NEXT_WORD_MENU_LIMIT`` rows.
NEXT_WORD_GHOST_LIMIT = 0

#: Reveal beat: a typing-triggered ghost shows its border hint only after
#: this pause with text and cursor unchanged. Explicit actions show the
#: hint in the same keystroke.
NEXT_WORD_REVEAL_DELAY_MS = 350

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets.next_word_placement import NextWordPeek
else:
    _MixinBase = object


class NextWordGhostStateMixin(_MixinBase):
    """Ghost state, gating, fitting, and reveal scheduling."""

    if TYPE_CHECKING:
        _file_completion_active: bool
        _next_word_ghost: NextWordGhost | None
        _next_word_hint: str | Text | None
        _next_word_peek: NextWordPeek | None
        _next_word_reveal_generation: int
        _next_word_reveal_timer: Any | None
        _vim_mode: str
        suggestion: str

        @property
        def snippet_session_active(self) -> bool: ...

        def _find_prompt_bar(self) -> Any: ...
        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _prompt_completion_settings(self) -> Any: ...
        def _fire_next_word_reveal(
            self,
            generation: int,
            text: str,
            cursor_offset: int,
        ) -> None: ...

    def _next_word_settings(self) -> tuple[str, int, str]:
        """Return ``(mode, max_words, confidence)`` with safe defaults."""
        getter = getattr(self, "_prompt_completion_settings", None)
        settings = getter() if callable(getter) else None
        mode = getattr(settings, "next_word", "chain")
        max_words = getattr(settings, "next_word_max_words", 4)
        confidence = getattr(settings, "next_word_confidence", "balanced")
        if mode not in {"off", "chain", "auto"}:
            mode = "chain"
        try:
            max_words = max(1, min(8, int(max_words)))
        except (TypeError, ValueError):
            max_words = 4
        if confidence not in {"cautious", "balanced", "eager"}:
            confidence = "balanced"
        return mode, max_words, confidence

    def _next_word_enabled(self) -> bool:
        """Return whether a ghost may arm or answer."""
        mode, _, _ = self._next_word_settings()
        return mode != "off"

    def _next_word_hint_surface(self) -> Any | None:
        """Return the border-hint surface, or ``None`` when unreachable."""
        try:
            return self._find_prompt_bar()
        except Exception:
            return None

    def _next_word_ghost_text(self) -> str | None:
        """Return the visible ghost string, or ``None`` when invalid."""
        ghost = getattr(self, "_next_word_ghost", None)
        if ghost is None:
            return None
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
            suggestion = self.suggestion
        except Exception:
            return None
        expected = next_word_ghost_expected(ghost, text=text, cursor_offset=offset)
        if expected is None or suggestion != expected:
            return None
        try:
            row, _ = self.cursor_location
            anchor_row, _ = self._location_from_absolute(ghost.anchor_offset)
        except Exception:
            return None
        if row != anchor_row:
            return None
        try:
            selection = self.selection
        except Exception:
            selection = None
        if selection is not None and not selection.is_empty:
            return None
        placement = classify_next_word_placement(text, offset)
        if placement not in (
            NextWordPlacement.INLINE_EOL,
            NextWordPlacement.INLINE_TAIL,
        ):
            return None
        if not self._next_word_on_last_wrapped_row():
            return None
        return suggestion

    def _next_word_ghost_visible(self) -> bool:
        """Return whether a valid ghost is currently displayed."""
        return self._next_word_ghost_text() is not None

    def _next_word_ghost_at_eol(self) -> bool:
        """Return whether the visible ghost sits at the true end of line.

        The fish-parity keys (``Right``/``Ctrl+F`` take all, ``Alt+F``
        takes one word) only apply here; before a closing tail they stay
        cursor motion.
        """
        if self._next_word_ghost_text() is None:
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        return (
            classify_next_word_placement(text, offset) is NextWordPlacement.INLINE_EOL
        )

    def _next_word_ghost_allowed(self) -> bool:
        """Return whether a ghost may be shown in the current UI state."""
        if not self._next_word_enabled():
            return False
        if getattr(self, "_vim_mode", "insert") != "insert":
            return False
        if getattr(self, "_file_completion_active", False):
            return False
        if bool(getattr(self, "snippet_session_active", False)):
            return False
        try:
            selection = self.selection
        except Exception:
            selection = None
        if selection is not None and not selection.is_empty:
            return False
        try:
            bar = self._find_prompt_bar()
        except Exception:
            bar = None
        if bar is not None:
            if getattr(bar, "_completion_panel_kind", None) == "jinja":
                return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        if classify_next_word_placement(text, offset) is NextWordPlacement.NONE:
            return False
        # Inside a Jinja tag Jinja owns completion: never show the
        # history next-word ghost there, whether or not its menu is open.
        # Read-only engine probe through the existing widget helper.
        try:
            from sase.ace.tui.widgets.jinja_completion import (
                build_jinja_completion_result,
                jinja_scope_for_editor,
            )

            if (
                build_jinja_completion_result(
                    text, offset, jinja_scope_for_editor(self)
                )
                is not None
            ):
                return False
        except Exception:
            pass
        return True

    def _next_word_on_last_wrapped_row(self) -> bool:
        """Return whether the cursor sits on its line's final wrapped row."""
        try:
            wrap_width = int(getattr(self, "wrap_width", 0) or 0)
        except (TypeError, ValueError):
            wrap_width = 0
        if wrap_width <= 0:
            return True
        try:
            row, col = self.cursor_location
            offsets = self.wrapped_document.get_offsets(row)
        except Exception:
            return True
        try:
            breaks = list(offsets)
        except TypeError:
            return True
        return next_word_is_last_wrapped_section(breaks, col)

    def _next_word_available_width(self) -> int:
        """Return the remaining cells on the cursor's wrapped row."""
        try:
            wrap_width = int(getattr(self, "wrap_width", 0) or 0)
        except (TypeError, ValueError):
            wrap_width = 0
        if wrap_width <= 0:
            return 10**6
        try:
            row, col = self.cursor_location
            offsets = self.wrapped_document.get_offsets(row)
            segment_start = 0
            for break_col in offsets:
                if break_col <= col:
                    segment_start = break_col
                else:
                    break
            return max(0, wrap_width - (col - segment_start))
        except Exception:
            return 10**6

    def _show_next_word_ghost_hint(self) -> None:
        """Show the ``[^T] word  [^L] all`` border hint."""
        surface = self._next_word_hint_surface()
        show = getattr(surface, "show_next_word_hint", None)
        if callable(show):
            try:
                show(NEXT_WORD_GHOST_HINT)
            except Exception:
                pass

    def _show_next_word_transient_hint(self, text: str) -> None:
        """Show a transient ``no guess`` / ``warming`` border hint."""
        self._next_word_hint = text
        surface = self._next_word_hint_surface()
        show = getattr(surface, "show_next_word_hint", None)
        if callable(show):
            try:
                show(text)
            except Exception:
                pass

    def _hide_next_word_hint(self) -> None:
        """Restore the mode subtitle when no ghost or hint is visible."""
        self._next_word_hint = None
        surface = self._next_word_hint_surface()
        hide = getattr(surface, "hide_next_word_hint", None)
        if callable(hide):
            try:
                hide()
            except Exception:
                pass

    def _cancel_next_word_reveal(self) -> None:
        """Stop a pending reveal-beat timer, if any."""
        timer = getattr(self, "_next_word_reveal_timer", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
            self._next_word_reveal_timer = None

    def _schedule_next_word_reveal(self, text: str, cursor_offset: int) -> None:
        """Show the ghost hint after the reveal beat when still current.

        The timer callback is thin and synchronous (tui_perf rule 2): it
        only re-reads text and cursor and shows the hint.
        """
        self._cancel_next_word_reveal()
        generation = int(getattr(self, "_next_word_reveal_generation", 0) or 0) + 1
        self._next_word_reveal_generation = generation
        try:
            self._next_word_reveal_timer = self.set_timer(
                NEXT_WORD_REVEAL_DELAY_MS / 1000,
                lambda: self._fire_next_word_reveal(generation, text, cursor_offset),
            )
        except Exception:
            self._next_word_reveal_timer = None

    def _clear_next_word_ghost(self) -> None:
        """Clear the ghost, cancel its reveal timer, restore the subtitle."""
        self._cancel_next_word_reveal()
        self._next_word_ghost = None
        self._next_word_hint = None
        try:
            self.suggestion = ""
        except Exception:
            pass
        self._hide_next_word_hint()

    def _set_next_word_ghost(
        self,
        words: list[str],
        separator: str,
        *,
        reveal: Literal["immediate", "delayed"] = "immediate",
    ) -> bool:
        """Fit *words* and display them as the ghost; return success.

        Only the inline placements render: ``peek`` and ``none`` return
        ``False`` (an explicit confident guess that cannot be placed falls
        through to the menu). A ``delayed`` reveal shows the ghost text at
        once but waits for the reveal beat before showing its hint.
        """
        if not words:
            return False
        _, max_words, _ = self._next_word_settings()
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        placement = classify_next_word_placement(text, offset)
        if placement not in (
            NextWordPlacement.INLINE_EOL,
            NextWordPlacement.INLINE_TAIL,
        ):
            return False
        if not self._next_word_on_last_wrapped_row():
            return False
        rest = next_word_rest_of_line(text, offset)
        tail = "" if placement is NextWordPlacement.INLINE_EOL else rest
        available = self._next_word_available_width()
        fitted = fit_next_word_ghost_with_tail(
            words, separator, available, max_words, tail
        )
        if not fitted:
            return False
        ghost_text = build_next_word_ghost_text(fitted, separator)
        if not ghost_text:
            return False
        self._next_word_ghost = NextWordGhost(
            anchor_offset=offset, full_text=ghost_text
        )
        self._next_word_peek = None
        try:
            self.suggestion = ghost_text
        except Exception:
            self._next_word_ghost = None
            return False
        if reveal == "delayed":
            self._schedule_next_word_reveal(text, offset)
        else:
            self._cancel_next_word_reveal()
            self._show_next_word_ghost_hint()
        return True


__all__ = [
    "NEXT_WORD_GHOST_LIMIT",
    "NEXT_WORD_REVEAL_DELAY_MS",
    "NextWordGhostStateMixin",
]
