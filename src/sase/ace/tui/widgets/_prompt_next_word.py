"""Ghost-text next-word chain for the prompt input.

Arms after every word commit, shows gated predictions as Textual
``suggestion`` ghost text with a border hint, and lets ``Ctrl+T``/``Alt+F``
take one word while ``Ctrl+F``/``Right``/``Ctrl+L`` take all. The Rust core
owns gating; this mixin only formats, fits, and clears the ghost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_GHOST_HINT,
    NEXT_WORD_NO_GUESS_HINT,
    NEXT_WORD_WARMING_HINT,
    NextWordChain,
    NextWordGhost,
    build_next_word_ghost_text,
    fit_next_word_ghost,
    next_word_auto_space_eligible,
    next_word_chain_armed,
    next_word_ghost_expected,
    next_word_leading_separator,
    next_word_rest_of_line,
    split_next_word_one,
)
from sase.ace.tui.widgets.next_word_menu import (
    NEXT_WORD_COMPLETION_KIND,
    NEXT_WORD_MENU_LIMIT,
    build_next_word_completion_candidates,
    next_word_fallback_at_word_end,
)

#: Menu rows requested by the ghost-only paths (arming and auto mode). The
#: core computes the gate and ghost before truncating the menu, so zero rows
#: keeps both identical while skipping every row's continuation preview,
#: which cuts real-history predict p95 by about two thirds. Only the explicit
#: menu requests ``NEXT_WORD_MENU_LIMIT`` rows.
_NEXT_WORD_GHOST_LIMIT = 0

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.core.prompt_prediction_wire import PromptPredictionResult
else:
    _MixinBase = object


class PromptNextWordMixin(_MixinBase):
    """Mixin providing the ghost-text next-word chain for PromptTextArea."""

    if TYPE_CHECKING:
        _completion_kind: str
        _file_completion_active: bool
        _file_completion_candidates: list[Any]
        _file_completion_index: int
        _next_word_chain: NextWordChain | None
        _next_word_ghost: NextWordGhost | None
        _next_word_hint: str | None
        _vim_mode: str
        suggestion: str

        @property
        def snippet_session_active(self) -> bool: ...

        def _find_prompt_bar(self) -> Any: ...
        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _replace_absolute_range(
            self,
            start_offset: int,
            end_offset: int,
            replacement: str,
        ) -> None: ...
        def _prompt_completion_settings(self) -> Any: ...
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
        def _soft_completion_blocked(self) -> bool: ...

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
        """Return whether the chain may arm or answer."""
        mode, _, _ = self._next_word_settings()
        return mode != "off"

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
        if next_word_rest_of_line(text, offset).strip() != "":
            return None
        return suggestion

    def _next_word_ghost_visible(self) -> bool:
        """Return whether a valid ghost is currently displayed."""
        return self._next_word_ghost_text() is not None

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
            bar = self._find_prompt_bar()
        except Exception:
            bar = None
        if bar is not None:
            if getattr(bar, "_completion_panel_kind", None) == "jinja":
                return False
            if getattr(bar, "_mode", "prompt") == "feedback":
                return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        if next_word_rest_of_line(text, offset).strip() != "":
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

    def _next_word_text_before_cursor(self) -> str:
        """Return the document text before the cursor."""
        offset = self._absolute_offset(self.cursor_location)
        return self.text[:offset]

    def _show_next_word_ghost_hint(self) -> None:
        """Show the ``[^T] word  [^F] all`` border hint."""
        try:
            bar = self._find_prompt_bar()
        except Exception:
            return
        show = getattr(bar, "show_next_word_hint", None)
        if callable(show):
            try:
                show(NEXT_WORD_GHOST_HINT)
            except Exception:
                pass

    def _show_next_word_transient_hint(self, text: str) -> None:
        """Show a transient ``no guess`` / ``warming`` border hint."""
        self._next_word_hint = text
        try:
            bar = self._find_prompt_bar()
        except Exception:
            return
        show = getattr(bar, "show_next_word_hint", None)
        if callable(show):
            try:
                show(text)
            except Exception:
                pass

    def _hide_next_word_hint(self) -> None:
        """Restore the mode subtitle when no ghost or hint is visible."""
        self._next_word_hint = None
        try:
            bar = self._find_prompt_bar()
        except Exception:
            return
        hide = getattr(bar, "hide_next_word_hint", None)
        if callable(hide):
            try:
                hide()
            except Exception:
                pass

    def _clear_next_word_chain(self) -> None:
        """Clear the ghost, disarm the chain, and restore the subtitle."""
        self._next_word_chain = None
        self._next_word_ghost = None
        self._next_word_hint = None
        try:
            self.suggestion = ""
        except Exception:
            pass
        self._hide_next_word_hint()

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

    def _validate_next_word_ghost(self) -> None:
        """Clear a stale ghost while keeping an armed chain when valid."""
        ghost = getattr(self, "_next_word_ghost", None)
        if ghost is None:
            return
        if self._next_word_ghost_text() is None:
            self._next_word_ghost = None
            try:
                self.suggestion = ""
            except Exception:
                pass
            if getattr(self, "_next_word_chain", None) is None:
                self._hide_next_word_hint()
            elif not self._next_word_chain_is_armed():
                self._hide_next_word_hint()
            else:
                # Chain still armed but ghost went stale (e.g. typed past
                # it): keep the chain so an explicit press can re-offer.
                if self._next_word_hint is None:
                    self._hide_next_word_hint()

    def _set_next_word_ghost(self, words: list[str], separator: str) -> bool:
        """Fit *words* and display them as the ghost; return success."""
        if not words:
            return False
        _, max_words, _ = self._next_word_settings()
        available = self._next_word_available_width()
        fitted = fit_next_word_ghost(words, separator, available, max_words)
        if not fitted:
            return False
        ghost_text = build_next_word_ghost_text(fitted, separator)
        if not ghost_text:
            return False
        try:
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        self._next_word_ghost = NextWordGhost(
            anchor_offset=offset, full_text=ghost_text
        )
        try:
            self.suggestion = ghost_text
        except Exception:
            self._next_word_ghost = None
            return False
        self._show_next_word_ghost_hint()
        return True

    def _arm_next_word_chain(self) -> None:
        """Arm the chain at the cursor and show a gated ghost when it fits."""
        if not self._next_word_enabled():
            self._clear_next_word_chain()
            return
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return
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
                limit=_NEXT_WORD_GHOST_LIMIT,
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
        if not self._set_next_word_ghost(list(result.ghost), separator):
            self._hide_next_word_hint()

    def _maybe_auto_next_word_ghost(self, character: str | None) -> bool:
        """Show a gated ghost right after a typed space in ``auto`` mode.

        Only the space keystroke predicts: the space must follow a word
        token at end of line and the ghost preconditions must hold. The
        chain is armed at the cursor and the ghost carries no leading
        separator (the text before the cursor already ends with the
        typed space). Everything else follows the ghost-chain contract.
        """
        if character != " ":
            return False
        mode, _, _ = self._next_word_settings()
        if mode != "auto":
            return False
        if self._next_word_ghost_visible():
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        if not next_word_auto_space_eligible(text, offset):
            return False
        if not self._next_word_ghost_allowed():
            return False
        self._arm_next_word_chain()
        return self._next_word_ghost_visible()

    def _accept_next_word_one(self) -> bool:
        """Insert the ghost's first word, then predict again without flicker."""
        ghost_text = self._next_word_ghost_text()
        if ghost_text is None:
            return False
        insert = split_next_word_one(ghost_text)
        if not insert:
            return False
        try:
            offset = self._absolute_offset(self.cursor_location)
            self._replace_absolute_range(offset, offset, insert)
        except Exception:
            return False
        self._arm_next_word_chain()
        return True

    def _accept_next_word_all(self) -> bool:
        """Insert the whole ghost, then arm the chain again."""
        ghost_text = self._next_word_ghost_text()
        if ghost_text is None:
            return False
        try:
            offset = self._absolute_offset(self.cursor_location)
            self._replace_absolute_range(offset, offset, ghost_text)
        except Exception:
            return False
        self._arm_next_word_chain()
        return True

    def _explicit_next_word_request(self) -> bool:
        """Handle ``Ctrl+T`` row 3: ghost, menu, or a transient hint.

        Returns True when the chain was armed (the press is consumed even
        when only a hint is shown). A confident ghost wins; otherwise the
        top candidates open the ``next_word`` menu, including when a ghost
        cannot be shown (mid-line or no width). Structural contexts with
        nothing to offer show the hint instead of a menu.
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
            # A confident ghost that cannot be shown (mid-line or no width)
            # falls through to the menu below.
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
                limit=_NEXT_WORD_GHOST_LIMIT,
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
