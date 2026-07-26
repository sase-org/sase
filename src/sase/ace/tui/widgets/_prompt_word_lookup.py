"""PromptTextArea plain-word definition and spellcheck fallback."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sase.core.word_lookup import (
    DefinitionResult,
    SpellCheckResult,
    WordSpan,
    check_spelling,
    extract_lookup_word,
    look_up_definitions,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class PromptWordLookupMixin(_MixinBase):
    """Resolve definitions or spelling suggestions for a prompt word."""

    if TYPE_CHECKING:
        _prompt_preview_request_id: int

    def _lookup_word_under_cursor(self) -> bool:
        """Schedule a word lookup when the cursor is on a plain word."""
        row, col = self.cursor_location
        span = extract_lookup_word(self.document.get_line(row), row, col)
        if span is None:
            return False

        self._prompt_preview_request_id += 1
        request_id = self._prompt_preview_request_id
        self.run_worker(
            self._resolve_word_lookup_async(span, request_id=request_id),
            name=f"prompt-word-lookup:{request_id}",
        )
        return True

    async def _resolve_word_lookup_async(
        self,
        span: WordSpan,
        *,
        request_id: int,
    ) -> None:
        spelling = await asyncio.to_thread(check_spelling, span.word)
        if not self._word_lookup_request_is_current(request_id):
            return
        if self._handle_spelling_terminal_result(span, spelling):
            return

        definitions = await asyncio.to_thread(look_up_definitions, span.word)
        if not self._word_lookup_request_is_current(request_id):
            return
        self._handle_definition_result(
            span,
            definitions,
            spelling_unavailable=spelling.status == "unavailable",
        )

    def _handle_spelling_terminal_result(
        self,
        span: WordSpan,
        spelling: SpellCheckResult,
    ) -> bool:
        if spelling.status == "error":
            detail = spelling.detail or "unknown aspell error"
            self.notify(
                f"Could not spell-check '{span.word}': {detail}",
                severity="error",
            )
            return True
        if spelling.status != "misspelled":
            return False
        if not spelling.suggestions:
            self.notify(
                f"'{span.word}' is not in the dictionary (no suggestions)",
                severity="warning",
            )
            return True

        from sase.ace.tui.modals.spellcheck_panel_modal import (
            SpellcheckPanelModal,
        )

        self.app.push_screen(
            SpellcheckPanelModal(span.word, spelling.suggestions),
            lambda suggestion: self._apply_spelling_suggestion(span, suggestion),
        )
        return True

    def _handle_definition_result(
        self,
        span: WordSpan,
        definitions: DefinitionResult,
        *,
        spelling_unavailable: bool,
    ) -> None:
        if definitions.status == "ok":
            from sase.ace.tui.modals.word_definition_modal import (
                WordDefinitionModal,
            )

            self.app.push_screen(WordDefinitionModal(span.word, definitions.sections))
            return
        if definitions.status == "unavailable":
            self.notify(
                "Install `dict` for word definitions "
                "(`sase doctor -D` shows optional tools)",
                severity="warning",
            )
            return
        if definitions.status == "no_match":
            message = f"No definition found for '{span.word}'"
            if spelling_unavailable:
                message += "; install aspell for spelling suggestions"
            self.notify(message, severity="information")
            return

        detail = definitions.detail or "unknown dict error"
        self.notify(
            f"Could not look up '{span.word}': {detail}",
            severity="error",
        )

    def _apply_spelling_suggestion(
        self,
        span: WordSpan,
        suggestion: str | None,
    ) -> None:
        if suggestion is None:
            return

        if span.row >= self.document.line_count:
            self._notify_word_changed_before_apply(span.word)
            return
        line = self.document.get_line(span.row)
        if line[span.start_col : span.end_col] != span.word:
            self._notify_word_changed_before_apply(span.word)
            return

        start = (span.row, span.start_col)
        end = (span.row, span.end_col)
        self.replace(suggestion, start, end)
        self.cursor_location = start

    def _notify_word_changed_before_apply(self, word: str) -> None:
        self.notify(
            f"'{word}' changed before the spelling fix could be applied",
            severity="warning",
        )

    def _word_lookup_request_is_current(self, request_id: int) -> bool:
        return request_id == self._prompt_preview_request_id and self.is_mounted


__all__ = ["PromptWordLookupMixin"]
