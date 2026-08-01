"""PromptTextArea plain-word definition and spellcheck fallback."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from sase.core.word_lookup import (
    AddToDictionaryResult,
    DefinitionResult,
    SpellCheckResult,
    WordSpan,
    add_to_personal_dictionary,
    check_spelling,
    extract_lookup_word,
    look_up_definitions,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.modals.spellcheck_panel_modal import SpellcheckChoice
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
        if spelling.status == "correct":
            if span.word.casefold() in self._prompt_misspelled_words():
                self._forget_prompt_misspelling(span.word)
            return False
        if spelling.status != "misspelled":
            return False

        # Record before pushing the panel so an Esc out of it still lands on an
        # already-squiggled word.
        self._record_prompt_misspelling(span.word)

        from sase.ace.tui.modals.spellcheck_panel_modal import (
            SpellcheckPanelModal,
        )

        self.app.push_screen(
            SpellcheckPanelModal(span.word, spelling.suggestions),
            lambda choice: self._apply_spelling_suggestion(span, choice),
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
        choice: SpellcheckChoice | None,
    ) -> None:
        if choice is None:
            # The word stays flagged, which is the point of Esc/cancel.
            return
        if choice.action == "accept":
            self._allow_prompt_misspelling(span.word)
            self.notify(f"'{span.word}' will no longer be flagged as misspelled")
            return
        if choice.action == "dictionary":
            self._add_word_to_personal_dictionary(span.word)
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
        self.replace(choice.suggestion, start, end)
        self.cursor_location = start

    def _notify_word_changed_before_apply(self, word: str) -> None:
        self.notify(
            f"'{word}' changed before the spelling fix could be applied",
            severity="warning",
        )

    def _add_word_to_personal_dictionary(self, word: str) -> None:
        """Schedule the off-thread aspell dictionary add for *word*."""
        self.run_worker(
            self._add_to_personal_dictionary_async(word),
            name="prompt-dictionary-add",
        )

    async def _add_to_personal_dictionary_async(self, word: str) -> None:
        result = await asyncio.to_thread(add_to_personal_dictionary, word)
        if not self.is_mounted:
            return
        self._notify_dictionary_add_result(word, result)

    def _notify_dictionary_add_result(
        self,
        word: str,
        result: AddToDictionaryResult,
    ) -> None:
        if result.status == "added":
            self._forget_prompt_misspelling(word)
            self.notify(f"Added '{word}' to your aspell personal dictionary")
            return
        if result.status == "unavailable":
            self.notify(
                f"aspell is no longer available; '{word}' was not added",
                severity="warning",
            )
            return
        detail = result.detail or "aspell did not accept the word"
        self.notify(f"Could not add '{word}' to aspell: {detail}", severity="error")

    def _word_lookup_request_is_current(self, request_id: int) -> bool:
        return request_id == self._prompt_preview_request_id and self.is_mounted

    def _prompt_misspelled_words(self) -> frozenset[str]:
        provider = getattr(self.app, "misspelled_words", None)
        if not callable(provider):
            return frozenset()
        try:
            words = provider()
        except Exception:
            return frozenset()
        return words if isinstance(words, frozenset) else frozenset()

    def _record_prompt_misspelling(self, word: str) -> None:
        recorder = getattr(self.app, "record_misspelling", None)
        if callable(recorder):
            recorder(word)

    def _forget_prompt_misspelling(self, word: str) -> None:
        forgetter = getattr(self.app, "forget_misspelling", None)
        if callable(forgetter):
            forgetter(word)

    def _allow_prompt_misspelling(self, word: str) -> None:
        allower = getattr(self.app, "allow_word", None)
        if callable(allower):
            allower(word)


__all__ = ["PromptWordLookupMixin"]
