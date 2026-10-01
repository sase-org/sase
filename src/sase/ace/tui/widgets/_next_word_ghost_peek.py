"""Peek display, reveal timing, auto trigger, and accepts for next-word ghosts.

Split out of ``_next_word_ghost_display``: this mixin derives from
``NextWordGhostStateMixin`` (ghost state, gating, fitting, and the
reveal scheduler primitives) and adds the border peek, the reveal-beat
fire callback, ghost/peek validation, the auto trigger, and the
accept actions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._next_word_midword import NextWordMidwordMixin
from sase.ace.tui.widgets.next_word_completion import (
    next_word_chain_armed,
    next_word_has_word_suffix,
    next_word_leading_separator,
    next_word_rest_of_line,
    split_next_word_one,
)
from sase.ace.tui.widgets.next_word_placement import (
    NextWordPeek,
    build_next_word_peek_text,
    next_word_auto_space_eligible,
    trim_next_word_peek_words,
)


class NextWordGhostPeekMixin(NextWordMidwordMixin):
    """Peek state, reveal timing, auto trigger, and accept actions."""

    if TYPE_CHECKING:
        from sase.core.prompt_prediction_wire import PromptPredictionWordCompletion

        _next_word_hint: str | Text | None
        _next_word_peek: NextWordPeek | None
        suggestion: str

        def _maybe_auto_next_word_midword(self, character: str | None) -> bool: ...
        def _accept_next_word_midword_peek_one(self) -> bool: ...
        def _accept_next_word_midword_peek_all(self) -> bool: ...

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
        def _replace_absolute_range(
            self,
            start_offset: int,
            end_offset: int,
            replacement: str,
        ) -> None: ...
        def _arm_next_word_chain(
            self,
            *,
            reveal: Literal["immediate", "delayed"] = "immediate",
            complete_current_word: bool = False,
        ) -> None: ...

    def _next_word_peek_visible(self) -> bool:
        """Return whether a revealed peek is currently displayed."""
        peek = getattr(self, "_next_word_peek", None)
        if peek is None or not peek.revealed or not peek.words:
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        if text != peek.anchor_text or offset != peek.anchor_offset:
            return False
        return True

    def _next_word_peek_pending(self) -> bool:
        """Return whether an unrevealed peek waits for the reveal beat."""
        peek = getattr(self, "_next_word_peek", None)
        if peek is None or peek.revealed or not peek.words:
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        return text == peek.anchor_text and offset == peek.anchor_offset

    def _next_word_peek_available_width(self) -> int:
        """Return the cells available for the peek beside readout and pill."""
        try:
            surface = self._next_word_hint_surface()
        except Exception:
            surface = None
        if surface is None:
            return 10**6
        try:
            size = getattr(surface, "size", None)
            bar_width = int(size.width or 0) if size is not None else 0
        except Exception:
            bar_width = 0
        if bar_width <= 0:
            return 10**6
        usable = max(0, bar_width - 6)
        try:
            from sase.ace.tui.widgets._prompt_cursor_readout import (
                cursor_readout_cell_width,
                cursor_readout_position,
            )

            line, column = cursor_readout_position(self)
            readout_width = cursor_readout_cell_width(line, column)
        except Exception:
            readout_width = 0
        divider_width = cell_len("  ·  ")
        pill_width = 0
        try:
            pill_fn = getattr(surface, "_search_readout_pill", None)
            pill = pill_fn(self) if callable(pill_fn) else None
            if pill is not None:
                pill_width = cell_len(pill.plain)
        except Exception:
            pill_width = 0
        if pill_width:
            return max(0, usable - readout_width - pill_width - (2 * divider_width))
        return max(0, usable - readout_width - divider_width)

    def _next_word_theme_variables(self) -> dict[str, str] | None:
        """Return the app theme variables for peek styling, if reachable."""
        try:
            variables = self.app.theme_variables
        except Exception:
            return None
        if not isinstance(variables, dict):
            try:
                variables = dict(variables)
            except Exception:
                return None
        return variables

    def _build_next_word_peek_text(self, words: list[str]) -> Text | None:
        """Build the degraded peek ``Text`` for *words* at the live width."""
        return build_next_word_peek_text(
            words,
            variables=self._next_word_theme_variables(),
            available_width=self._next_word_peek_available_width(),
        )

    def _show_next_word_peek_text(self, peek_text: Text) -> None:
        """Show a built peek ``Text`` on the border-hint surface."""
        self._next_word_hint = peek_text
        surface = self._next_word_hint_surface()
        show = getattr(surface, "show_next_word_hint", None)
        if callable(show):
            try:
                show(peek_text)
            except Exception:
                pass

    def _fire_next_word_reveal(
        self,
        generation: int,
        text: str,
        cursor_offset: int,
    ) -> None:
        """Show a delayed ghost hint or peek when the snapshot matches.

        The callback stays thin and synchronous: it only re-reads text
        and cursor, then shows the pending hint or builds the peek.
        """
        self._next_word_reveal_timer = None
        if generation != getattr(self, "_next_word_reveal_generation", 0):
            return
        try:
            current_text = self.text
            current_offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return
        if current_text != text or current_offset != cursor_offset:
            return
        if self._next_word_ghost_text() is not None:
            self._show_next_word_ghost_hint()
            return
        if self._next_word_peek_pending():
            self._reveal_next_word_peek()

    def _clear_next_word_peek(self) -> None:
        """Clear the peek, cancel its reveal timer, restore the subtitle."""
        self._cancel_next_word_reveal()
        self._next_word_peek = None
        self._next_word_hint = None
        self._hide_next_word_hint()

    def _validate_next_word_peek(self) -> None:
        """Clear a stale peek while keeping an armed chain when valid."""
        peek = getattr(self, "_next_word_peek", None)
        if peek is None:
            return
        if self._next_word_peek_visible() or self._next_word_peek_pending():
            return
        self._cancel_next_word_reveal()
        self._next_word_peek = None
        chain = getattr(self, "_next_word_chain", None)
        if chain is None:
            self._hide_next_word_hint()
            return
        try:
            armed = next_word_chain_armed(
                chain,
                text=self.text,
                cursor_offset=self._absolute_offset(self.cursor_location),
            )
        except Exception:
            armed = False
        if not armed or self._next_word_hint is None:
            self._hide_next_word_hint()

    def _reveal_next_word_peek(self) -> bool:
        """Reveal a pending peek immediately; return success.

        A peek that has not been revealed is not visible, so ``Ctrl+T``
        treats it as an explicit request: this reveals it without
        inserting anything.
        """
        peek = getattr(self, "_next_word_peek", None)
        if peek is None or not peek.words:
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        if text != peek.anchor_text or offset != peek.anchor_offset:
            self._validate_next_word_peek()
            return False
        peek_text = self._build_next_word_peek_text(list(peek.words))
        if peek_text is None:
            self._clear_next_word_peek()
            return False
        self._cancel_next_word_reveal()
        self._next_word_peek = NextWordPeek(
            anchor_offset=peek.anchor_offset,
            anchor_text=peek.anchor_text,
            words=peek.words,
            revealed=True,
            word_completion=peek.word_completion,
        )
        self._show_next_word_peek_text(peek_text)
        return True

    def _set_next_word_peek(
        self,
        words: list[str],
        *,
        reveal: Literal["immediate", "delayed"] = "immediate",
        word_completion: PromptPredictionWordCompletion | None = None,
    ) -> bool:
        """Trim *words* and show them as the border peek; return success.

        The redundancy trim drops words the text after the cursor already
        has; width degradation drops trailing preview words before hints.
        A ``delayed`` reveal stores the peek unrevealed until the beat. An
        explicit peek shows immediately. The ghost is cleared: only one
        surface is ever visible. A mid-word peek carries the core's
        *word_completion* so its accepts finish the typed word via the
        suffix instead of re-inserting the whole word.
        """
        if not words:
            return False
        _, max_words, _ = self._next_word_settings()
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        capped = list(words[: max(1, max_words)])
        rest = next_word_rest_of_line(text, offset)
        trimmed = trim_next_word_peek_words(capped, rest)
        if not trimmed:
            return False
        self._next_word_ghost = None
        try:
            self.suggestion = ""
        except Exception:
            pass
        if reveal == "delayed":
            self._next_word_peek = NextWordPeek(
                anchor_offset=offset,
                anchor_text=text,
                words=tuple(trimmed),
                revealed=False,
                word_completion=word_completion,
            )
            self._schedule_next_word_reveal(text, offset)
            return True
        peek_text = self._build_next_word_peek_text(trimmed)
        if peek_text is None:
            self._next_word_peek = None
            return False
        self._cancel_next_word_reveal()
        self._next_word_peek = NextWordPeek(
            anchor_offset=offset,
            anchor_text=text,
            words=tuple(trimmed),
            revealed=True,
            word_completion=word_completion,
        )
        self._show_next_word_peek_text(peek_text)
        return True

    def _validate_next_word_ghost(self) -> None:
        """Clear a stale ghost while keeping an armed chain when valid.

        The reveal timer is shared with the peek: when no ghost exists
        but a peek is pending or visible, the timer belongs to the peek
        and is left alone.
        """
        ghost = getattr(self, "_next_word_ghost", None)
        if ghost is None:
            if self._next_word_peek_pending() or self._next_word_peek_visible():
                return
            self._cancel_next_word_reveal()
            return
        if self._next_word_ghost_text() is None:
            self._cancel_next_word_reveal()
            self._next_word_ghost = None
            try:
                self.suggestion = ""
            except Exception:
                pass
            chain = getattr(self, "_next_word_chain", None)
            if chain is None:
                self._hide_next_word_hint()
                return
            try:
                armed = next_word_chain_armed(
                    chain,
                    text=self.text,
                    cursor_offset=self._absolute_offset(self.cursor_location),
                )
            except Exception:
                armed = False
            # Chain still armed but ghost went stale (e.g. typed past
            # it): keep the chain so an explicit press can re-offer.
            if not armed or self._next_word_hint is None:
                self._hide_next_word_hint()

    def _maybe_auto_next_word_ghost(self, character: str | None) -> bool:
        """Show a gated ghost or peek after a typed trigger in ``auto`` mode.

        Any typed non-word character following a word token predicts next
        words; a typed word character with no word character after the
        cursor requests a mid-word completion instead. Inline placements
        render at once as ghost text; peeks and hints wait for the reveal
        beat. Everything else follows the chain contract.
        """
        if character is None or len(character) != 1 or not character.isprintable():
            return False
        if character.isalnum() or character in {"-", "_", "'", "’"}:
            return self._maybe_auto_next_word_midword(character)
        mode, _, _ = self._next_word_settings()
        if mode != "auto":
            return False
        if self._next_word_ghost_visible() or self._next_word_peek_visible():
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
        self._arm_next_word_chain(reveal="delayed")
        return self._next_word_ghost_visible()

    def _accept_next_word_peek_one(self) -> bool:
        """Insert the peek's first word with menu separator rules.

        One undo step, then predict again immediately so the next guess
        shows without flicker. A trailing space is added when an
        identifier character follows, with the cursor landing after the
        word, exactly like the next-word menu accept. A mid-word peek
        instead finishes the typed word via its completion suffix.
        """
        peek = getattr(self, "_next_word_peek", None)
        if peek is None or not peek.words:
            return False
        if getattr(peek, "word_completion", None) is not None:
            return self._accept_next_word_midword_peek_one()
        if not self._next_word_peek_visible():
            return False
        word = peek.words[0]
        if not word:
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        separator = next_word_leading_separator(text[:offset])
        has_suffix = next_word_has_word_suffix(text, offset)
        insertion = f"{separator}{word}"
        if has_suffix:
            insertion = f"{insertion} "
        try:
            self._replace_absolute_range(offset, offset, insertion)
        except Exception:
            return False
        if has_suffix:
            try:
                self.cursor_location = self._location_from_absolute(
                    offset + len(separator) + len(word)
                )
            except Exception:
                pass
        self._arm_next_word_chain()
        return True

    def _accept_next_word_peek_all(self) -> bool:
        """Insert every peek word with menu separator rules, then re-arm.

        A mid-word peek instead inserts its suffix plus every preview
        word, mirroring the mid-word ghost text.
        """
        peek = getattr(self, "_next_word_peek", None)
        if peek is None or not peek.words:
            return False
        if getattr(peek, "word_completion", None) is not None:
            return self._accept_next_word_midword_peek_all()
        if not self._next_word_peek_visible():
            return False
        words = [word for word in peek.words if word]
        if not words:
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return False
        separator = next_word_leading_separator(text[:offset])
        has_suffix = next_word_has_word_suffix(text, offset)
        insertion = f"{separator}{' '.join(words)}"
        if has_suffix:
            insertion = f"{insertion} "
        try:
            self._replace_absolute_range(offset, offset, insertion)
        except Exception:
            return False
        if has_suffix:
            try:
                self.cursor_location = self._location_from_absolute(
                    offset + len(separator) + len(" ".join(words))
                )
            except Exception:
                pass
        self._arm_next_word_chain()
        return True

    def _accept_next_word_one(self) -> bool:
        """Insert the ghost's or peek's first word, then predict again."""
        ghost_text = self._next_word_ghost_text()
        if ghost_text is not None:
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
        return self._accept_next_word_peek_one()

    def _accept_next_word_all(self) -> bool:
        """Insert the whole ghost or peek, then arm the chain again."""
        ghost_text = self._next_word_ghost_text()
        if ghost_text is not None:
            try:
                offset = self._absolute_offset(self.cursor_location)
                self._replace_absolute_range(offset, offset, ghost_text)
            except Exception:
                return False
            self._arm_next_word_chain()
            return True
        return self._accept_next_word_peek_all()


__all__ = ["NextWordGhostPeekMixin"]
