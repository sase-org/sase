"""History-word cache helpers for prompt completion."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._file_completion_workers import FileCompletionWorkerMixin
from sase.ace.tui.widgets.prompt_word_completion import WordCompletionResult
from sase.history.prompt_word_index import PromptWordIndex

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings


class FileCompletionHistoryMixin(FileCompletionWorkerMixin):
    """Mixin providing warm history-word cache access and result building."""

    if TYPE_CHECKING:

        def _prompt_completion_settings(self) -> PromptCompletionSettings: ...
        def _refresh_history_word_completion(
            self,
            words: list[str] | None = None,
        ) -> None: ...

    def _history_prompt_words(self) -> list[str] | None:
        """Return the app's warm history-word list without touching disk."""
        provider = getattr(self.app, "history_prompt_words", None)
        if not callable(provider):
            return None
        try:
            words = provider()
        except Exception:
            return []
        return words if isinstance(words, list) else None

    def _history_prompt_word_index(self) -> PromptWordIndex | None:
        """Return the app's warm prompt-word index without touching disk."""
        provider = getattr(self.app, "history_prompt_word_index", None)
        if not callable(provider):
            return None
        try:
            index = provider()
        except Exception:
            return None
        return index if isinstance(index, PromptWordIndex) else None

    def _history_prompt_word_deletions(self) -> frozenset[str]:
        """Return the app's warm suppressed-history-word set without disk I/O."""
        provider = getattr(self.app, "history_prompt_word_deletions", None)
        if not callable(provider):
            return frozenset()
        try:
            deletions = provider()
        except Exception:
            return frozenset()
        return deletions if isinstance(deletions, frozenset) else frozenset()

    def _history_word_ranking_mode(self) -> str:
        """Return the configured ``word_ranking`` mode for history words."""
        return self._prompt_completion_settings().word_ranking

    def _history_word_index_available(self) -> bool:
        """Return whether the app exposes a warm prompt-word index provider."""
        return callable(getattr(self.app, "history_prompt_word_index", None))

    def _history_word_source_ready(self) -> bool:
        """Return whether some warm-cache provider exists for history words."""
        if self._history_word_index_available():
            return True
        return callable(getattr(self.app, "history_prompt_words", None))

    def _history_word_cache_is_cold(self) -> bool:
        """Return whether the active warm-cache source has not landed yet."""
        if self._history_word_index_available():
            return self._history_prompt_word_index() is None
        return self._history_prompt_words() is None

    def _build_history_word_result(
        self,
        cursor_offset: int,
        *,
        words: list[str] | None = None,
    ) -> WordCompletionResult | None:
        """Build the active ranking mode's history-word result.

        Prefers the warm :class:`PromptWordIndex` when the app provides one
        (both ``smart`` and ``recent`` ranking read through it, so every row
        is the same shape), and falls back to the plain MRU word-list
        overload for callers and test harnesses without an index. The caller
        is responsible for handling the cold-cache case (see
        :meth:`_history_word_cache_is_cold`) before calling this.
        """
        from sase.ace.tui.widgets.history_word_completion import (
            build_history_word_completion_result,
            build_indexed_history_word_completion_result,
        )

        if self._history_word_index_available():
            index = self._history_prompt_word_index()
            if index is None:
                return None
            return build_indexed_history_word_completion_result(
                self.text,
                cursor_offset,
                index,
                deleted=self._history_prompt_word_deletions(),
                now=time.time(),
                smart=self._history_word_ranking_mode() == "smart",
            )

        if words is None:
            words = self._history_prompt_words()
        if words is None:
            return None
        return build_history_word_completion_result(self.text, cursor_offset, words)

    def _schedule_history_word_completion_load(self) -> None:
        """Ask the app cache to warm for an active cold history menu."""
        warmer = getattr(self.app, "warm_history_prompt_words", None)
        if callable(warmer):
            warmer()

    def _apply_history_word_completion_result(self, words: list[str]) -> None:
        """Apply a completed app-cache load to the active history menu."""
        from sase.ace.tui.widgets.history_word_completion import (
            HISTORY_WORD_COMPLETION_KIND,
        )

        if (
            not self._file_completion_active
            or self._completion_kind != HISTORY_WORD_COMPLETION_KIND
        ):
            return
        self._refresh_history_word_completion(words)
