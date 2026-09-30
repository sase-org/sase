"""Prompt-only next-word chain: arming, the Ctrl+T ladder, and the menu.

Ghost display (state, fitting, accepts, reveal timing, auto trigger) lives
in the host-neutral :class:`NextWordGhostDisplayMixin`; this mixin only
adds the prompt's chain, the explicit-request ladder, and the
``next_word`` menu. The Rust core owns gating.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.widgets._next_word_ghost_display import (
    NEXT_WORD_GHOST_LIMIT,
    NextWordGhostDisplayMixin,
)
from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_NO_GUESS_HINT,
    NEXT_WORD_NO_GUESS_RECENT_FILES_HINT,
    NEXT_WORD_WARMING_HINT,
    NextWordChain,
    next_word_chain_armed,
    next_word_leading_separator,
)
from sase.ace.tui.widgets.next_word_menu import (
    NEXT_WORD_COMPLETION_KIND,
    NEXT_WORD_MENU_LIMIT,
    build_next_word_completion_candidates,
    next_word_fallback_at_word_end,
)

if TYPE_CHECKING:
    from sase.core.prompt_prediction_wire import PromptPredictionResult


class PromptNextWordMixin(NextWordGhostDisplayMixin):
    """Mixin providing the ghost-text next-word chain for PromptTextArea."""

    if TYPE_CHECKING:
        _completion_kind: str
        _file_completion_active: bool
        _file_completion_candidates: list[Any]
        _file_completion_index: int
        _next_word_chain: NextWordChain | None

        def _find_prompt_bar(self) -> Any: ...
        def _predict_next_words(
            self,
            text_before_cursor: str,
            *,
            limit: int = 5,
            max_words: int = 4,
            confidence: str = "balanced",
        ) -> PromptPredictionResult | None: ...
        def _prompt_prediction_is_cold(self) -> bool: ...
        def _schedule_prompt_prediction_load(self) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _update_file_completion_panel(self, token: str) -> None: ...

    def _next_word_chain_is_armed(self) -> bool:
        """Return whether the chain still matches the document."""
        if not self._next_word_enabled():
            return False
        chain = getattr(self, "_next_word_chain", None)
        if chain is None:
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        return next_word_chain_armed(chain, text=text, cursor_offset=offset)

    def _clear_next_word_chain(self) -> None:
        """Clear the ghost, disarm the chain, and restore the subtitle."""
        self._next_word_chain = None
        self._clear_next_word_ghost()

    def _on_prompt_completion_context_changed(self) -> None:
        """Validate the ghost after text or cursor changes, then refresh soft."""
        try:
            self._validate_next_word_ghost()
        except Exception:
            pass
        try:
            if not self._next_word_chain_is_armed():
                self._hide_next_word_hint()
        except Exception:
            pass
        try:
            super()._on_prompt_completion_context_changed()  # type: ignore[misc]
        except Exception:
            pass

    def _arm_next_word_chain(
        self, *, reveal: Literal["immediate", "delayed"] = "immediate"
    ) -> None:
        """Arm the chain at the cursor and show a gated ghost when it fits.

        Typing-triggered arms pass ``reveal="delayed"`` so the ghost text
        appears at once while its hint waits for the reveal beat;
        explicit arms show both immediately.
        """
        if not self._next_word_enabled():
            self._clear_next_word_chain()
            return
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return
        self._cancel_next_word_reveal()
        self._next_word_chain = NextWordChain(anchor_offset=offset, anchor_text=text)
        self._next_word_ghost = None
        self._next_word_hint = None
        if not self._next_word_ghost_allowed():
            self._hide_next_word_hint()
            return
        _, max_words, confidence = self._next_word_settings()
        try:
            text_before = text[:offset]
            separator = next_word_leading_separator(text_before)
            result = self._predict_next_words(
                text_before,
                limit=NEXT_WORD_GHOST_LIMIT,
                max_words=max_words,
                confidence=confidence,
            )
        except Exception:
            return
        if result is None:
            # Cold or disabled: keep the chain armed for an explicit press.
            self._hide_next_word_hint()
            return
        if not getattr(result, "confident", False) or not result.ghost:
            self._hide_next_word_hint()
            return
        if not self._set_next_word_ghost(
            list(result.ghost),
            separator,
            reveal=reveal,
        ):
            self._hide_next_word_hint()

    def _explicit_next_word_request(self) -> bool:
        """Handle ``Ctrl+T`` row 3: ghost, menu, or a transient hint.

        Returns True when the chain was armed (the press is consumed even
        when only a hint is shown). A confident ghost wins; otherwise the
        top candidates open the ``next_word`` menu, including when a ghost
        cannot be shown (peek placement or no width). Structural contexts
        with nothing to offer show the hint instead of a menu.
        """
        if not self._next_word_chain_is_armed():
            return False
        if self._next_word_ghost_visible():
            return False
        _, max_words, confidence = self._next_word_settings()
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
            text_before = text[:offset]
        except Exception:
            return True
        try:
            is_cold = bool(self._prompt_prediction_is_cold())
        except Exception:
            is_cold = False
        if is_cold:
            try:
                self._schedule_prompt_prediction_load()
            except Exception:
                pass
            self._show_next_word_transient_hint(NEXT_WORD_WARMING_HINT)
            return True
        try:
            result = self._predict_next_words(
                text_before,
                limit=NEXT_WORD_MENU_LIMIT,
                max_words=max_words,
                confidence=confidence,
            )
        except Exception:
            result = None
        if result is None:
            try:
                cold_now = bool(self._prompt_prediction_is_cold())
            except Exception:
                cold_now = False
            if cold_now:
                try:
                    self._schedule_prompt_prediction_load()
                except Exception:
                    pass
                self._show_next_word_transient_hint(NEXT_WORD_WARMING_HINT)
            else:
                self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_HINT)
            return True
        if getattr(result, "confident", False) and result.ghost:
            if self._next_word_ghost_allowed():
                separator = next_word_leading_separator(text_before)
                if self._set_next_word_ghost(list(result.ghost), separator):
                    return True
            # A confident ghost that cannot be shown (peek placement or no
            # width) falls through to the menu below.
        return self._open_next_word_menu_for_result(result)

    def _open_next_word_menu_for_result(self, result: PromptPredictionResult) -> bool:
        """Open the menu for *result*'s candidates, or hint when empty.

        Always consumes the press: blocked or evidence-free contexts show
        the transient hint and never open a menu.
        """
        if result.blocked_reason:
            self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_HINT)
            return True
        candidates = build_next_word_completion_candidates(
            result, limit=NEXT_WORD_MENU_LIMIT
        )
        if not candidates:
            self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_HINT)
            return True
        return self._open_next_word_menu(candidates)

    def _open_next_word_menu(self, candidates: list[Any]) -> bool:
        """Show an explicit next-word menu over the armed chain."""
        if not candidates:
            return False
        self._completion_kind = NEXT_WORD_COMPLETION_KIND
        self._file_completion_active = True
        self._file_completion_candidates = list(candidates)
        self._file_completion_index = 0
        self._hide_next_word_hint()
        self._update_file_completion_panel("")
        return True

    def _try_next_word_word_end_fallback(self) -> bool:
        """Arm the chain and run an explicit request at a prose word end.

        Ladder row 4b: ``Ctrl+T`` at the end of a prose word with no
        current-word candidate behaves like an explicit next-word request.
        Anywhere else the press stays unconsumed.
        """
        if not self._next_word_enabled():
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        if not next_word_fallback_at_word_end(text, offset):
            return False
        self._arm_next_word_chain()
        if self._next_word_ghost_visible():
            return True
        return self._explicit_next_word_request()

    def _try_next_word_boundary_request(self) -> bool:
        """Arm the chain and run an explicit request at a whitespace boundary.

        Boundary ``Ctrl+T`` (no token under the cursor) owns the old
        file-history slot when next-word is enabled: arm the chain at the
        cursor, show a visible ghost, or run an explicit request. A
        no-guess outcome teaches the moved menu with the
        ``[^G r] recent files`` hint. With next-word off the press stays
        unconsumed so the dispatcher falls through to file history.
        """
        if not self._next_word_enabled():
            return False
        self._arm_next_word_chain()
        if self._next_word_ghost_visible():
            return True
        consumed = self._explicit_next_word_request()
        if consumed and self._next_word_hint == NEXT_WORD_NO_GUESS_HINT:
            self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_RECENT_FILES_HINT)
        return consumed

    def _refresh_visible_next_word_surface(self) -> None:
        """Show a ghost when a warm model lands while the chain is armed."""
        if not self._next_word_chain_is_armed():
            return
        if self._next_word_ghost_visible():
            return
        if not self._next_word_ghost_allowed():
            return
        _, max_words, confidence = self._next_word_settings()
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
            result = self._predict_next_words(
                text[:offset],
                limit=NEXT_WORD_GHOST_LIMIT,
                max_words=max_words,
                confidence=confidence,
            )
        except Exception:
            return
        if result is None or not getattr(result, "confident", False):
            return
        if not result.ghost:
            return
        try:
            separator = next_word_leading_separator(text[:offset])
        except Exception:
            return
        self._set_next_word_ghost(list(result.ghost), separator)
