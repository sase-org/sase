"""Gate note editor with next-word autosuggest.

Hosts the host-neutral ghost display layer in the gate/plan feedback note
editor: inline ghosts and border peeks with the ``Ctrl+T``/``Ctrl+L`` accept
keys. There is no completion menu here, so a non-confident explicit
``Ctrl+T`` shows ``no next-word guess`` instead of opening one.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from rich.text import Text
from textual.events import Key

from sase.ace.tui.widgets._next_word_ghost_display import (
    NEXT_WORD_GHOST_LIMIT,
    NextWordGhostDisplayMixin,
)
from sase.ace.tui.widgets._next_word_prediction_access import (
    NextWordPredictionAccessMixin,
)
from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_NO_GUESS_HINT,
    NEXT_WORD_WARMING_HINT,
    NextWordChain,
    next_word_chain_armed,
    next_word_leading_separator,
)
from sase.ace.tui.widgets.next_word_placement import next_word_midword_eligible
from sase.ace.tui.widgets.prompt_completion import (
    DEFAULT_PROMPT_COMPLETION_SETTINGS,
    PromptCompletionSettings,
)
from sase.ace.tui.widgets.vim_mode_routing import VimModeRoutingMixin
from sase.ace.tui.widgets.vim_text_area import VimTextArea


class GateNoteInput(
    NextWordGhostDisplayMixin,
    NextWordPredictionAccessMixin,
    VimModeRoutingMixin,
    VimTextArea,
):
    """Multi-line vim editor for the reviewer's note, with autosuggest.

    ``Ctrl+T`` takes one word (or reveals a pending peek), ``Ctrl+L``
    takes all, and ``Right``/``Ctrl+F`` take all only at the true end of
    line. ``Alt+F`` takes one word only there. ``Ctrl+T`` is unbound in
    the gate panel and ``VimTextArea`` today; ``Ctrl+F``/``Alt+F`` stay
    cursor motion everywhere else.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("soft_wrap", True)
        kwargs.setdefault("show_line_numbers", False)
        kwargs.setdefault("tab_behavior", "focus")
        self._gate_prediction_project = cast(
            "str | None", kwargs.pop("prediction_project", None)
        )
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.show_line_numbers = False
        self._next_word_chain: NextWordChain | None = None
        self._next_word_ghost = None
        self._next_word_peek = None
        self._next_word_hint: str | Text | None = None
        self._next_word_reveal_timer: Any | None = None
        self._next_word_reveal_generation = 0
        self._next_word_midword_generation = 0
        self._next_word_midword_timer: Any | None = None
        self._file_completion_active = False

    def _prompt_completion_settings(self) -> PromptCompletionSettings:
        """Return prompt completion settings with a safe default."""
        getter = getattr(self.app, "get_prompt_completion_settings", None)
        if callable(getter):
            try:
                value = getter()
            except Exception:
                value = None
            if isinstance(value, PromptCompletionSettings):
                return value
        return DEFAULT_PROMPT_COMPLETION_SETTINGS

    def _prompt_prediction_project(self, text_before_cursor: str) -> str | None:
        """Resolve the gate note's project without disk I/O.

        The gate request carries no project key, so a panel-supplied
        project wins when present; otherwise this falls back to the app's
        cheap in-memory resolver and finally ``None``.
        """
        gate_project = getattr(self, "_gate_prediction_project", None)
        if isinstance(gate_project, str) and gate_project:
            return gate_project
        return super()._prompt_prediction_project(text_before_cursor)

    def _find_prompt_bar(self) -> Any | None:
        """Gate notes have no prompt bar; the hint surface is the editor."""
        return None

    def _next_word_hint_surface(self) -> Any | None:
        """Return the note editor itself as the border-hint surface."""
        return self

    def show_next_word_hint(self, text: str | Text) -> None:
        """Render a ghost, peek, or transient hint in the note border."""
        try:
            self.border_subtitle = text
        except Exception:
            pass

    def hide_next_word_hint(self) -> None:
        """Clear the note border hint without touching layout."""
        try:
            self.border_subtitle = ""
        except Exception:
            pass

    def _replace_absolute_range(
        self,
        start_offset: int,
        end_offset: int,
        replacement: str,
    ) -> None:
        """Replace an absolute note range and put cursor at replacement end."""
        start = self._location_from_absolute(start_offset)
        end = self._location_from_absolute(end_offset)
        self._replace_via_keyboard(replacement, start, end)
        self.cursor_location = self._location_from_absolute(
            start_offset + len(replacement)
        )

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
        """Clear ghost and peek, disarm the chain, restore the border."""
        self._next_word_chain = None
        try:
            self._cancel_next_word_midword_request()
        except Exception:
            pass
        self._clear_next_word_ghost()
        try:
            self._clear_next_word_peek()
        except Exception:
            pass

    def _anchor_next_word_chain(self, *, midword: bool) -> tuple[str, int] | None:
        """Reset chain, ghost, peek, and hint anchors without predicting."""
        try:
            self._cancel_next_word_midword_request()
        except Exception:
            pass
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return None
        self._cancel_next_word_reveal()
        self._next_word_chain = NextWordChain(
            anchor_offset=offset, anchor_text=text, midword=midword
        )
        self._next_word_ghost = None
        try:
            self._next_word_peek = None
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
    ) -> None:
        """Arm the chain at the cursor and show a gated ghost when it fits."""
        if not self._next_word_enabled():
            self._clear_next_word_chain()
            return
        anchored = self._anchor_next_word_chain(midword=complete_current_word)
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
            self._hide_next_word_hint()
            return
        if complete_current_word:
            self._compose_next_word_midword_result(result, reveal=reveal)
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
        if self._set_next_word_peek(list(result.ghost), reveal=reveal):
            return
        self._hide_next_word_hint()

    def _explicit_next_word_request(self) -> bool:
        """Arm and run an explicit request; hint when there is no guess.

        Returns True when the press is consumed. A visible ghost or
        revealed peek belongs to the accept path, so this returns False
        for those (the caller accepts instead). There is no menu here:
        a non-confident guess shows ``no next-word guess``.
        """
        if self._next_word_ghost_visible():
            return False
        try:
            if bool(self._next_word_peek_visible()):
                return False
        except Exception:
            pass
        try:
            if bool(self._reveal_next_word_peek()):
                return True
        except Exception:
            pass
        if not self._next_word_enabled():
            return False
        try:
            text = self.text
            offset = self._absolute_offset(self.cursor_location)
        except Exception:
            return True
        wants_completion = bool(next_word_midword_eligible(text, offset))
        anchored = self._anchor_next_word_chain(midword=wants_completion)
        if anchored is None:
            self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_HINT)
            return True
        text, offset = anchored
        _, max_words, confidence = self._next_word_settings()
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
                text[:offset],
                limit=NEXT_WORD_GHOST_LIMIT,
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
            if self._compose_next_word_midword_result(result):
                return True
            self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_HINT)
            return True
        if getattr(result, "confident", False) and result.ghost:
            if self._next_word_ghost_allowed():
                separator = next_word_leading_separator(text[:offset])
                if self._set_next_word_ghost(list(result.ghost), separator):
                    return True
                if self._set_next_word_peek(list(result.ghost)):
                    return True
        self._show_next_word_transient_hint(NEXT_WORD_NO_GUESS_HINT)
        return True

    def _refresh_visible_next_word_surface(self) -> None:
        """Show a ghost or peek when a warm model lands while armed."""
        if not self._next_word_chain_is_armed():
            return
        if self._next_word_ghost_visible():
            return
        try:
            if bool(self._next_word_peek_visible()):
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
            self._compose_next_word_midword_result(result)
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
            self._set_next_word_peek(list(result.ghost))
        except Exception:
            pass

    def validate_next_word_surfaces(self) -> None:
        """Clear a stale ghost or peek while keeping an armed chain."""
        try:
            self._validate_next_word_ghost()
        except Exception:
            pass
        try:
            self._validate_next_word_peek()
        except Exception:
            pass

    async def _on_key(self, event: Key) -> None:
        """Intercept accept and explicit keys before the vim layer."""
        if getattr(self, "_vim_mode", "insert") == "insert":
            if event.key == "ctrl+l" and (
                self._next_word_ghost_visible() or self._next_word_peek_visible()
            ):
                event.stop()
                event.prevent_default()
                self._accept_next_word_all()
                return
            if event.key == "alt+f" and self._next_word_ghost_at_eol():
                event.stop()
                event.prevent_default()
                self._accept_next_word_one()
                return
            if event.key == "ctrl+t" and (
                self._next_word_ghost_visible() or self._next_word_peek_visible()
            ):
                event.stop()
                event.prevent_default()
                self._accept_next_word_one()
                return
            if event.key == "ctrl+t" and self._explicit_next_word_request():
                event.stop()
                event.prevent_default()
                return
        await super()._on_key(event)
        if getattr(self, "_vim_mode", "insert") == "insert":
            try:
                self._maybe_auto_next_word_ghost(event.character)
            except Exception:
                pass

    def action_cursor_right(self, select: bool = False) -> None:
        """Take the whole ghost at end of line; else move right."""
        try:
            visible = bool(self._next_word_ghost_visible())
        except Exception:
            visible = False
        if visible and not select:
            try:
                at_eol = bool(self._next_word_ghost_at_eol())
            except Exception:
                at_eol = False
            if at_eol:
                try:
                    if bool(self._accept_next_word_all()):
                        return
                except Exception:
                    pass
            try:
                self.suggestion = ""
            except Exception:
                pass
        super().action_cursor_right(select)
        self.validate_next_word_surfaces()

    def _enter_normal_mode(self) -> None:
        """Switch to NORMAL mode, clearing the transient guess."""
        super()._enter_normal_mode()
        try:
            self._clear_next_word_chain()
        except Exception:
            pass

    def on_blur(self) -> None:
        """Clear the transient guess when focus leaves the note."""
        try:
            self._clear_next_word_chain()
        except Exception:
            pass
        super_on_blur = getattr(super(), "on_blur", None)
        if callable(super_on_blur):
            try:
                super_on_blur()
            except Exception:
                pass


__all__ = ["GateNoteInput"]
