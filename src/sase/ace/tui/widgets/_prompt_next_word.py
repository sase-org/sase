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
            complete_current_word: bool = False,
        ) -> PromptPredictionResult | None: ...
        def _compose_next_word_midword_result(
            self,
            result: PromptPredictionResult | None,
            *,
            reveal: Literal["immediate", "delayed"] = "immediate",
        ) -> bool: ...
        def _cancel_next_word_midword_request(self) -> None: ...
        def _prompt_prediction_is_cold(self) -> bool: ...
        def _schedule_prompt_prediction_load(self) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _extract_token_around_cursor(self) -> tuple[int, int, str] | None: ...
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
        """Clear ghost and peek, disarm the chain, restore the subtitle."""
        self._next_word_chain = None
        try:
            self._cancel_next_word_midword_request()  # type: ignore[attr-defined]
        except Exception:
            pass
        self._clear_next_word_ghost()
        try:
            self._clear_next_word_peek()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_prompt_completion_context_changed(self) -> None:
        """Validate ghost and peek after text/cursor changes, refresh soft."""
        try:
            self._validate_next_word_ghost()
        except Exception:
            pass
        try:
            self._validate_next_word_peek()  # type: ignore[attr-defined]
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

    def _anchor_next_word_chain(
        self, *, midword: bool, typed: bool = False
    ) -> tuple[str, int] | None:
        """Reset the chain, ghost, peek, and hint anchors without predicting.

        Returns the ``(text, offset)`` snapshot, or ``None`` when the chain
        cannot arm (unreadable document or a blocking UI state). A pending
        deferred mid-word request is superseded.
        """
        try:
            self._cancel_next_word_midword_request()  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return None
        self._cancel_next_word_reveal()
        self._next_word_chain = NextWordChain(
            anchor_offset=offset, anchor_text=text, midword=midword, typed=typed
        )
        self._next_word_ghost = None
        try:
            self._next_word_peek = None  # type: ignore[attr-defined]
        except Exception:
            pass
        self._next_word_hint = None
        if not self._next_word_ghost_allowed():
            self._hide_next_word_hint()
            return None
        return (text, offset)

    def _arm_next_word_chain(
        self,
        *,
        reveal: Literal["immediate", "delayed"] = "immediate",
        complete_current_word: bool = False,
        typed: bool = False,
    ) -> None:
        """Arm the chain at the cursor and show a gated ghost when it fits.

        Typing-triggered arms pass ``reveal="delayed"`` so the ghost text
        appears at once while its hint waits for the reveal beat;
        explicit arms show both immediately. With
        *complete_current_word* the core also completes the word being
        typed and the guess composes as suffix plus continuation, with
        old-core silence when the field is missing.
        """
        if not self._next_word_enabled():
            self._clear_next_word_chain()
            return
        anchored = self._anchor_next_word_chain(
            midword=complete_current_word, typed=typed
        )
        if anchored is None:
            return
        text, offset = anchored
        _, max_words, confidence = self._next_word_settings()
        try:
            text_before = text[:offset]
            separator = next_word_leading_separator(text_before)
            result = self._predict_next_words(
                text_before,
                limit=NEXT_WORD_GHOST_LIMIT,
                max_words=max_words,
                confidence=confidence,
                complete_current_word=complete_current_word,
            )
        except Exception:
            return
        if result is None:
            # Cold or disabled: keep the chain armed for an explicit press.
            self._hide_next_word_hint()
            return
        if complete_current_word:
            self._compose_next_word_midword_result(  # type: ignore[attr-defined]
                result, reveal=reveal
            )
            return
        if not getattr(result, "confident", False) or not result.ghost:
            self._hide_next_word_hint()
            return
        if self._set_next_word_ghost(
            list(result.ghost),
            separator,
            reveal=reveal,
        ):
            return
        if self._set_next_word_peek(  # type: ignore[attr-defined]
            list(result.ghost),
            reveal=reveal,
        ):
            return
        self._hide_next_word_hint()

    def _explicit_next_word_request(self) -> bool:
        """Handle ``Ctrl+T`` row 3: ghost, peek, menu, or a transient hint.

        Returns True when the chain was armed (the press is consumed even
        when only a hint is shown). An unrevealed peek is revealed without
        inserting. A confident guess wins as a ghost or peek; otherwise
        the top candidates open the ``next_word`` menu. Structural
        contexts with nothing to offer show the hint instead of a menu.
        """
        if not self._next_word_chain_is_armed():
            return False
        if self._next_word_ghost_visible():
            return False
        try:
            peek_visible = bool(self._next_word_peek_visible())  # type: ignore[attr-defined]
        except Exception:
            peek_visible = False
        if peek_visible:
            return False
        try:
            if bool(self._reveal_next_word_peek()):  # type: ignore[attr-defined]
                return True
        except Exception:
            pass
        _, max_words, confidence = self._next_word_settings()
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
            text_before = text[:offset]
        except Exception:
            return True
        chain = getattr(self, "_next_word_chain", None)
        wants_completion = bool(getattr(chain, "midword", False))
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
                complete_current_word=wants_completion,
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
        if wants_completion:
            # A mid-word chain owns the explicit press the same way: the
            # guess composes as suffix plus continuation, or the press
            # teaches silence. The menu never opens here: its accepts
            # insert whole words and would duplicate the typed prefix.
            if self._compose_next_word_midword_result(  # type: ignore[attr-defined]
                result
            ):
                return True
            self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_HINT)
            return True
        if getattr(result, "confident", False) and result.ghost:
            if self._next_word_ghost_allowed():
                separator = next_word_leading_separator(text_before)
                if self._set_next_word_ghost(list(result.ghost), separator):
                    return True
                if self._set_next_word_peek(  # type: ignore[attr-defined]
                    list(result.ghost),
                ):
                    return True
            # A confident guess that fits neither surface falls through
            # to the menu below.
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
        return self._explicit_next_word_ctrl_t()

    def _typed_next_word_chain_yields_ctrl_t(self) -> bool:
        """Return whether ``Ctrl+T`` should skip an ``auto``-typed chain.

        ``auto`` arms a chain after almost every keystroke, so an armed chain
        alone is not a request. A typed chain owns the press only while its
        guess waits for the reveal beat (row 3 reveals it); otherwise the
        manual dispatcher (row 4) completes the token and requests next words
        itself at a whitespace boundary or a prose word end.
        """
        chain = getattr(self, "_next_word_chain", None)
        if chain is None or not chain.typed or not self._next_word_chain_is_armed():
            return False
        try:
            if self._next_word_peek_pending():  # type: ignore[attr-defined]
                return False
        except Exception:
            pass
        return True

    def _explicit_next_word_ctrl_t(self) -> bool:
        """Run the ``Ctrl+T`` explicit request, teaching recent files on a miss.

        A no-guess outcome at a whitespace boundary (no token under the
        cursor, the old file-history slot) names ``Ctrl+G r``, whether
        the chain was armed by this press or earlier by ``auto`` typing.
        A chain armed by ``auto`` typing yields ``Ctrl+T`` to manual
        completion unless a peek waits for the reveal beat.
        """
        if self._typed_next_word_chain_yields_ctrl_t():
            return False
        consumed = self._explicit_next_word_request()
        if consumed and self._next_word_hint == NEXT_WORD_NO_GUESS_HINT:
            try:
                at_boundary = self._extract_token_around_cursor() is None
            except Exception:
                at_boundary = False
            if at_boundary:
                self._show_next_word_transient_hint(
                    NEXT_WORD_NO_GUESS_RECENT_FILES_HINT
                )
        return consumed

    def _refresh_visible_next_word_surface(self) -> None:
        """Show a ghost or peek when a warm model lands while armed."""
        if not self._next_word_chain_is_armed():
            return
        if self._next_word_ghost_visible():
            return
        try:
            if bool(self._next_word_peek_visible()):  # type: ignore[attr-defined]
                return
        except Exception:
            pass
        if not self._next_word_ghost_allowed():
            return
        chain = getattr(self, "_next_word_chain", None)
        wants_completion = bool(getattr(chain, "midword", False))
        _, max_words, confidence = self._next_word_settings()
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
            result = self._predict_next_words(
                text[:offset],
                limit=NEXT_WORD_GHOST_LIMIT,
                max_words=max_words,
                confidence=confidence,
                complete_current_word=wants_completion,
            )
        except Exception:
            return
        if result is None or not getattr(result, "confident", False):
            return
        if wants_completion:
            # A mid-word chain refreshes as suffix plus continuation: a
            # plain next-word ghost after a half-typed word would be wrong.
            self._compose_next_word_midword_result(  # type: ignore[attr-defined]
                result
            )
            return
        if not result.ghost:
            return
        try:
            separator = next_word_leading_separator(text[:offset])
        except Exception:
            return
        if self._set_next_word_ghost(list(result.ghost), separator):
            return
        try:
            self._set_next_word_peek(list(result.ghost))  # type: ignore[attr-defined]
        except Exception:
            pass
